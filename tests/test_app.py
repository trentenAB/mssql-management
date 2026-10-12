import pytest
from app import create_app, odbc_value
from app import store
from conftest import csrf


def test_demo_history_diff_and_headers(client):
    response = client.get('/')
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    for expected in ['ActiveCustomers', 'alex.chen', 'maya.patel', '2026-02-18', 'Currently applied · assumed', 'DeletedAt IS NULL', 'diff-line insert', 'Demo mode is read-only']:
        assert expected in text
    assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']
    assert response.headers['Cache-Control'] == 'no-store'


def test_any_two_versions_and_reversed_diff(client):
    response = client.get('/?object=1&left=3&right=1')
    assert response.status_code == 200
    assert 'diff-line delete' in response.get_data(as_text=True)
    assert client.get('/?object=1&left=4&right=1').status_code == 400
    assert client.get('/?object=1&left=999').status_code == 400
    assert client.get('/?object=999').status_code == 404


def test_csrf_and_demo_deployment_forbidden(client):
    assert client.post('/versions/1/apply').status_code == 400
    token = csrf(client)
    assert client.post('/versions/1/apply', data={'csrf_token':token}).status_code == 403
    assert client.post('/import', data={'csrf_token':token}).status_code == 403


def test_sql_is_escaped_in_definition_and_diff(app, client):
    with store.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE versions SET statement=? WHERE id=3", ("ALTER VIEW dbo.ActiveCustomers AS SELECT '<script>alert(1)</script>';",))
    body = client.get('/').get_data(as_text=True)
    assert '<script>alert(1)</script>' not in body
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in body


def test_demo_seeding_is_repeatable(app):
    store.initialize(app.config['DATABASE'], True)
    with store.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT count(*) FROM versions').fetchone()[0] == 9


@pytest.mark.parametrize('object_id, record_ids', [
    (1, [3, 2, 1]), (2, [5, 4]), (3, [6]), (4, [9, 8, 7]),
])
def test_versions_start_at_one_for_each_existing_object(app, client, object_id, record_ids):
    with store.connect(app.config['DATABASE']) as db:
        versions = store.versions_for_object(db, object_id)
        assert [v['id'] for v in versions] == record_ids
        assert [v['version_number'] for v in versions] == list(range(len(record_ids), 0, -1))
        for v in versions:
            assert store.version_by_id(db, v['id'])['version_number'] == v['version_number']
    body = client.get(f'/?object={object_id}&right={record_ids[-1]}').get_data(as_text=True)
    assert 'Selected version <span class="muted">#1</span>' in body
    assert f'value="{record_ids[-1]}" selected>#1 ·' in body


def test_earlier_audit_imports_are_numbered_chronologically_without_changing_ids(app):
    with store.connect(app.config['DATABASE']) as db:
        event = dict(db.execute('SELECT * FROM versions WHERE id=5').fetchone())
        event.update(database_name='CommerceDemo', schema_name='dbo', name='GetOrderSummary',
                     kind='PROCEDURE', event_key='earlier-import', occurred_at='2025-12-01T00:00:00Z')
        store.add_event(db, event)
        versions = store.versions_for_object(db, 2)
        assert [v['id'] for v in versions] == [5, 4, 10]
        assert [v['version_number'] for v in versions] == [3, 2, 1]
        assert store.version_by_id(db, 4)['version_number'] == 2
        assert store.version_by_id(db, 9999) is None


class FakeBackend:
    allowed = True
    definition = 'CREATE VIEW dbo.ActiveCustomers AS SELECT 1;'
    applied = False

    def state(self, _obj):
        return dict(actor='real.sql.login', allowed=self.allowed, definition=self.definition, fingerprint='current-hash')

    def apply(self, obj, version, fingerprint):
        if not self.allowed:
            raise PermissionError()
        if fingerprint != 'current-hash':
            raise ValueError('The live definition changed.')
        self.applied = True
        self.definition = version['statement']
        return 'real.sql.login'

    def import_events(self, _path):
        event = dict(database_name='CommerceDemo',schema_name='dbo',name='ActiveCustomers',kind='VIEW',
                     event_key='audit:test',statement=self.definition,actor='original.author',
                     occurred_at='2026-03-01T00:00:00Z',action='ALTER',action_id='AL',
                     permission_succeeded=1,complete=1,note='',source='audit')
        return [event], {'AL':'ALTER'}


@pytest.fixture
def connected(app):
    backend = FakeBackend()
    app.config.update(DEMO_MODE=False, SQLSERVER_HOST='test-host', SQLSERVER_DATABASE='CommerceDemo',
                      AUDIT_FILE_PATTERN='/audit/*.sqlaudit', TEST_BACKEND=backend)
    return app.test_client(), backend


def test_import_dedupe_and_apply_tracks_actual_login(app, connected):
    client, backend = connected
    token = csrf(client)
    for _ in range(2):
        assert client.post('/import',data={'csrf_token':token}).status_code == 302
    with store.connect(app.config['DATABASE']) as db:
        version_id = db.execute("SELECT id FROM versions WHERE event_key='audit:test'").fetchone()[0]
        assert db.execute("SELECT count(*) FROM versions WHERE event_key='audit:test'").fetchone()[0] == 1
    response = client.post(f'/versions/{version_id}/apply',data={'csrf_token':token,'confirm':'dbo.ActiveCustomers','fingerprint':'current-hash'},follow_redirects=True)
    assert response.status_code == 200
    assert backend.applied
    assert 'Verified against live database' in response.get_data(as_text=True)
    with store.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT actor FROM deployments').fetchone()[0] == 'real.sql.login'
        assert db.execute('SELECT applied_version_id FROM objects WHERE id=1').fetchone()[0] == version_id


def test_permissions_and_stale_changes_block_write(app, connected):
    client, backend = connected
    token = csrf(client)
    client.post('/import',data={'csrf_token':token})
    with store.connect(app.config['DATABASE']) as db:
        version_id=db.execute("SELECT id FROM versions WHERE event_key='audit:test'").fetchone()[0]
    backend.allowed=False
    assert client.post(f'/versions/{version_id}/apply',data={'csrf_token':token,'confirm':'dbo.ActiveCustomers','fingerprint':'current-hash'}).status_code == 403
    backend.allowed=True
    response=client.post(f'/versions/{version_id}/apply',data={'csrf_token':token,'confirm':'dbo.ActiveCustomers','fingerprint':'stale'},follow_redirects=True)
    assert 'live definition changed' in response.get_data(as_text=True)
    assert not backend.applied
    assert client.post(f'/versions/{version_id}/apply',data={'csrf_token':token,'confirm':'wrong'}).status_code == 400
    assert client.post('/versions/7/apply',data={'csrf_token':token,'confirm':'dbo.Customers'}).status_code == 400


def test_connected_mode_requires_login_and_configuration(tmp_path):
    with pytest.raises(RuntimeError):
        create_app({'DEMO_MODE':False,'SECRET_KEY':'test','DATABASE':str(tmp_path/'missing.sqlite3')})
    app=create_app({'TESTING':True,'DEMO_MODE':False,'SECRET_KEY':'test','SQLSERVER_HOST':'host',
                    'SQLSERVER_DATABASE':'db','DATABASE':str(tmp_path/'db.sqlite3')})
    client=app.test_client()
    assert client.get('/').location.endswith('/login')
    assert client.get('/login').status_code == 200
    client.get('/login')
    with client.session_transaction() as s:
        token=s['csrf_token']
    for _ in range(10):
        assert client.post('/login',data={'csrf_token':token,'username':'','password':''}).status_code == 200
    assert client.post('/login',data={'csrf_token':token}).status_code == 429


def test_credentials_are_not_stored_in_cookie(tmp_path, monkeypatch):
    from app.sqlserver import SqlServer
    class Connection:
        def close(self): pass
    monkeypatch.setattr(SqlServer,'connect',lambda self: Connection())
    app=create_app({'TESTING':True,'DEMO_MODE':False,'SECRET_KEY':'test','SQLSERVER_HOST':'host',
                    'SQLSERVER_DATABASE':'db','DATABASE':str(tmp_path/'db.sqlite3')})
    client=app.test_client()
    client.get('/login')
    with client.session_transaction() as s: token=s['csrf_token']
    response=client.post('/login',data={'csrf_token':token,'username':'alice','password':'private-password'})
    assert response.status_code == 302
    with client.session_transaction() as s:
        assert 'password' not in s and 'connection_string' not in s
        token=s['csrf_token']
        sql_token=s['sql_token']
    assert 'private-password' in app.extensions['sql_sessions'][sql_token][0].connection_string
    client.post('/logout',data={'csrf_token':token})
    assert sql_token not in app.extensions['sql_sessions']
    assert odbc_value('x};UID=evil') == '{x}};UID=evil}'


def test_selected_applied_version_wins_when_definitions_are_identical(app, connected):
    client, backend = connected
    with store.connect(app.config['DATABASE']) as db:
        definition = db.execute('SELECT statement FROM versions WHERE id=1').fetchone()[0]
        db.execute('UPDATE versions SET statement=? WHERE id=3', (definition,))
        db.execute('UPDATE objects SET applied_version_id=1 WHERE id=1')
    backend.definition = definition
    body=client.get('/?object=1').get_data(as_text=True)
    assert 'Version #1 · Verified against live database' in body


def test_applying_object_local_version_keeps_original_record_id(app, connected):
    client, backend = connected
    with store.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE versions SET source='audit' WHERE id=4")
    token = csrf(client)
    before = client.get('/?object=2&right=4').get_data(as_text=True)
    assert 'Apply version #1' in before
    assert 'action="/versions/4/apply"' in before
    response = client.post('/versions/4/apply', data={
        'csrf_token': token, 'confirm': 'dbo.GetOrderSummary', 'fingerprint': 'current-hash',
    }, follow_redirects=True)
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'Applied version #1 as real.sql.login.' in body
    assert 'Version #1 · Verified against live database' in body
    assert 'Version #1 · real.sql.login ·' in body
    assert backend.applied
    assert 'GetOrderSummary' in backend.definition
    with store.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT applied_version_id FROM objects WHERE id=2').fetchone()[0] == 4
        assert db.execute('SELECT version_id FROM deployments WHERE object_id=2').fetchone()[0] == 4
