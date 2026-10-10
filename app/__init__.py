import difflib
import hmac
import os
import secrets
import time
from datetime import timedelta
from pathlib import Path
from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from . import store
from .definitions import normalize_definition
from .sqlserver import SqlServer


def odbc_value(value):
    return '{' + value.replace('}', '}}') + '}'


def create_app(config=None):
    app = Flask(__name__)
    demo = os.getenv('DEMO_MODE', 'true').lower() == 'true'
    app.config.update(SECRET_KEY=os.getenv('FLASK_SECRET_KEY') or secrets.token_hex(32),
        DEMO_MODE=demo, DATABASE=os.getenv('HISTORY_DATABASE', str(Path(app.instance_path) / ('demo.sqlite3' if demo else 'history.sqlite3'))),
        SQLSERVER_HOST=os.getenv('SQLSERVER_HOST', ''), SQLSERVER_DATABASE=os.getenv('SQLSERVER_DATABASE', ''),
        AUDIT_FILE_PATTERN=os.getenv('AUDIT_FILE_PATTERN', ''),
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE', 'false').lower() == 'true',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8), MAX_CONTENT_LENGTH=16*1024)
    if config:
        app.config.update(config)
    if not app.config['DEMO_MODE']:
        if not (os.getenv('FLASK_SECRET_KEY') or (config or {}).get('SECRET_KEY')):
            raise RuntimeError('FLASK_SECRET_KEY is required in connected mode.')
        if not app.config['SQLSERVER_HOST'] or not app.config['SQLSERVER_DATABASE']:
            raise RuntimeError('SQLSERVER_HOST and SQLSERVER_DATABASE are required in connected mode.')
    Path(app.config['DATABASE']).parent.mkdir(parents=True, exist_ok=True)
    store.initialize(app.config['DATABASE'], app.config['DEMO_MODE'])
    # Credentials stay server-side, never in Flask's signed (unencrypted) cookies.
    app.extensions['sql_sessions'] = {}
    app.extensions['login_attempts'] = {}

    @app.before_request
    def prepare_request():
        g.db = store.connect(app.config['DATABASE'])
        session.setdefault('csrf_token', secrets.token_urlsafe(32))
        if request.method == 'POST':
            supplied = request.form.get('csrf_token', '')
            if not hmac.compare_digest(supplied, session['csrf_token']):
                abort(400, 'Invalid CSRF token. Reload the page and retry.')
        token = session.get('sql_token')
        now = time.time()
        credentials = app.extensions['sql_sessions']
        for key in list(credentials):
            if credentials[key][1] < now:
                del credentials[key]
        g.backend = credentials.get(token, (None, 0))[0]
        # Fake backend is useful for isolated integration tests only.
        if app.testing and app.config.get('TEST_BACKEND'):
            g.backend = app.config['TEST_BACKEND']
        if not app.config['DEMO_MODE'] and not g.backend and request.endpoint not in ('login','static'):
            return redirect(url_for('login'))

    @app.teardown_request
    def teardown(_error):
        db = g.pop('db', None)
        if db:
            db.close()

    @app.after_request
    def secure_response(response):
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.context_processor
    def context():
        return dict(demo=app.config['DEMO_MODE'], csrf_token=session.get('csrf_token'),
                    connected=bool(getattr(g, 'backend', None)), database_name=app.config['SQLSERVER_DATABASE'])

    @app.route('/login', methods=['GET','POST'])
    def login():
        if app.config['DEMO_MODE']:
            return redirect(url_for('index'))
        if request.method == 'POST':
            # Small in-process limiter for local/single-worker use, no unbounded key growth.
            attempts = app.extensions['login_attempts']
            now = time.time()
            for key in list(attempts):
                if now - attempts[key][0] > 300:
                    del attempts[key]
            ip = request.remote_addr or 'unknown'
            start, count = attempts.get(ip, (now, 0))
            if count >= 10:
                abort(429, 'Too many login attempts. Retry in five minutes.')
            attempts[ip] = (start, count+1)
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            if not username or not password or len(username) > 128:
                flash('Enter your SQL Server username and password.', 'error')
            else:
                connection_string = ';'.join([
                    'DRIVER={ODBC Driver 18 for SQL Server}',
                    'SERVER=' + odbc_value(app.config['SQLSERVER_HOST']),
                    'DATABASE=' + odbc_value(app.config['SQLSERVER_DATABASE']),
                    'UID=' + odbc_value(username), 'PWD=' + odbc_value(password),
                    'Encrypt=yes', 'TrustServerCertificate=no'])
                backend = SqlServer(connection_string, app.config['SQLSERVER_DATABASE'])
                try:
                    conn = backend.connect()
                    conn.close()
                except Exception:
                    flash('SQL Server login failed. Check credentials, network access, and the server certificate.', 'error')
                else:
                    old_token = session.get('sql_token')
                    app.extensions['sql_sessions'].pop(old_token, None)
                    session.clear()
                    session['csrf_token'] = secrets.token_urlsafe(32)
                    token = secrets.token_urlsafe(32)
                    app.extensions['sql_sessions'][token] = (backend, now+8*3600)
                    session['sql_token'] = token
                    session['login_name'] = username
                    session.permanent = True
                    attempts.pop(ip, None)
                    return redirect(url_for('index'))
        return render_template('login.html')

    @app.post('/logout')
    def logout():
        app.extensions['sql_sessions'].pop(session.get('sql_token'), None)
        session.clear()
        return redirect(url_for('login'))

    @app.get('/')
    def index():
        objects = g.db.execute('''SELECT o.*, count(v.id) version_count, max(v.occurred_at) updated_at
            FROM objects o LEFT JOIN versions v ON v.object_id=o.id
            GROUP BY o.id ORDER BY o.name''').fetchall()
        selected = request.args.get('object', type=int)
        if not selected and objects:
            selected = objects[0]['id']
        obj = next((o for o in objects if o['id'] == selected), None)
        if selected and not obj:
            abort(404)
        versions = []
        left = right = None
        diff_rows = []
        live_state = None
        live_error = None
        current_id = None
        current_label = 'Latest recorded · assumed'
        deployments = []
        if obj:
            versions = g.db.execute('SELECT * FROM versions WHERE object_id=? ORDER BY occurred_at DESC,id DESC', (obj['id'],)).fetchall()
            definitions = [v for v in versions if v['action'] in ('CREATE','ALTER')]
            current_id = definitions[0]['id'] if definitions else None
            if g.backend:
                try:
                    live_state = g.backend.state(obj)
                    if live_state['allowed']:
                        current_label = 'Verified against live database'
                        matching_ids = [v['id'] for v in versions if v['complete'] and normalize_definition(v['statement']) == normalize_definition(live_state['definition'])]
                        current_id = obj['applied_version_id'] if obj['applied_version_id'] in matching_ids else (matching_ids[0] if matching_ids else None)
                        if current_id is None:
                            current_label = 'Live definition has no matching recorded version'
                except Exception:
                    live_error = 'Live permission and definition check failed. Deployment is unavailable.'
            by_id = {v['id']:v for v in versions}
            left_id = request.args.get('left', type=int)
            right_id = request.args.get('right', type=int)
            if (left_id is not None and left_id not in by_id) or (right_id is not None and right_id not in by_id):
                abort(400, 'Both versions must belong to the selected object.')
            right = by_id.get(right_id) if right_id else (versions[0] if versions else None)
            left = by_id.get(left_id) if left_id else (versions[1] if len(versions)>1 else right)
            if left and right:
                old, new = left['statement'].splitlines(), right['statement'].splitlines()
                for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
                    if tag == 'equal':
                        diff_rows.extend(('equal', i+1, j+1, old[i]) for i,j in zip(range(i1,i2),range(j1,j2)))
                    else:
                        diff_rows.extend(('delete', i+1, '', old[i]) for i in range(i1,i2))
                        diff_rows.extend(('insert', '', j+1, new[j]) for j in range(j1,j2))
            deployments = g.db.execute('SELECT * FROM deployments WHERE object_id=? ORDER BY id DESC LIMIT 10', (obj['id'],)).fetchall()
        return render_template('index.html', objects=objects, obj=obj, versions=versions, left=left, right=right,
            diff_rows=diff_rows, live_state=live_state, live_error=live_error, current_id=current_id,
            current_label=current_label, deployments=deployments,
            added=sum(r[0]=='insert' for r in diff_rows), removed=sum(r[0]=='delete' for r in diff_rows))

    @app.post('/import')
    def import_audit():
        if not g.backend or app.config['DEMO_MODE']:
            abort(403, 'Audit ingestion requires a SQL Server login in connected mode.')
        path = app.config['AUDIT_FILE_PATTERN']
        if not path or not path.lower().endswith('.sqlaudit'):
            flash('Configure AUDIT_FILE_PATTERN with a server-side .sqlaudit path or wildcard.', 'error')
            return redirect(url_for('index'))
        try:
            events, actions = g.backend.import_events(path)
            with g.db:
                count = sum(store.add_event(g.db, event) for event in events)
            flash(f'Imported {count} new events. Action IDs: ' + ', '.join(f'{name}={code}' for code,name in sorted(actions.items())), 'success')
        except Exception:
            # Do not expose connection strings, file paths or SQL errors in the browser/logs.
            flash('Audit import failed. Verify audit-read permissions, the server-side path, and SQL Server 2016+ support.', 'error')
        return redirect(url_for('index'))

    @app.post('/versions/<int:version_id>/apply')
    def apply_version(version_id):
        if app.config['DEMO_MODE'] or not g.backend:
            abort(403, 'Demo mode is read-only. Connect with your own SQL login to deploy.')
        version = g.db.execute('SELECT * FROM versions WHERE id=?', (version_id,)).fetchone()
        if not version:
            abort(404)
        obj = g.db.execute('SELECT * FROM objects WHERE id=?', (version['object_id'],)).fetchone()
        if obj['database_name'] != app.config['SQLSERVER_DATABASE']:
            abort(403, 'Version does not belong to the configured database.')
        if request.form.get('confirm') != f"{obj['schema_name']}.{obj['name']}":
            abort(400, 'Type the exact schema.object name to confirm deployment.')
        if not version['complete'] or version['source'] != 'audit':
            abort(400, 'This event is not a complete deployable definition.')
        try:
            actor = g.backend.apply(obj, version, request.form.get('fingerprint', ''))
        except PermissionError:
            abort(403, 'Your SQL login does not have the necessary permissions.')
        except ValueError as exc:
            flash(str(exc), 'error')
        except Exception:
            flash('Deployment failed. SQL Server rejected the operation; no application deployment was committed.', 'error')
        else:
            try:
                with g.db:
                    g.db.execute('UPDATE objects SET applied_version_id=? WHERE id=?', (version_id,obj['id']))
                    g.db.execute('INSERT INTO deployments(object_id,version_id,actor,applied_at) VALUES(?,?,?,?)',
                                 (obj['id'],version_id,actor,store.utcnow()))
            except Exception:
                flash('SQL deployment committed, but local deployment history could not be saved. Reload to verify the live definition.', 'error')
            else:
                flash(f'Applied version #{version_id} as {actor}.', 'success')
        return redirect(url_for('index', object=obj['id'], right=version_id))

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(429)
    def error_page(error):
        return render_template('error.html', error=error), error.code

    return app
