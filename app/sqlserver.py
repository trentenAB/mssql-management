"""Read audit files on SQL Server's filesystem; never interpret binary files locally."""
import hashlib
from collections import defaultdict
from datetime import timezone
from .definitions import prepare_definition, normalize_definition

ACTION_NAMES = ('CREATE', 'ALTER', 'DROP', 'INSERT', 'UPDATE', 'DELETE')


class SqlServer:
    def __init__(self, connection_string, database):
        self.connection_string = connection_string
        self.database = database

    def connect(self):
        import pyodbc
        connection = pyodbc.connect(self.connection_string, timeout=10, autocommit=False)
        # Configuration, never browser input; quote identifiers defensively.
        connection.execute('USE [' + self.database.replace(']', ']]') + ']')
        connection.execute('SET XACT_ABORT ON; SET LOCK_TIMEOUT 10000;')
        connection.timeout = 30
        return connection

    def import_events(self, path):
        connection = self.connect()
        try:
            cursor = connection.cursor()
            # Query the authoritative mapping for this server rather than guessing IDs.
            cursor.execute("SELECT DISTINCT action_id, name FROM sys.dm_audit_actions WHERE action_id IS NOT NULL AND action_in_log = 1 AND name IN ('CREATE','ALTER','DROP','INSERT','UPDATE','DELETE')")
            actions = {str(r[0]).strip(): str(r[1]).strip() for r in cursor.fetchall()}
            if not actions:
                raise ValueError('No supported audit actions found on this SQL Server.')
            placeholders = ','.join('?' for _ in actions)
            cursor.execute(f'''SELECT event_time, sequence_number, action_id, succeeded,
                session_server_principal_name, server_principal_name, database_name,
                schema_name, object_name, statement, file_name, audit_file_offset,
                sequence_group_id, class_type
                FROM sys.fn_get_audit_file(?, DEFAULT, DEFAULT)
                WHERE database_name = ? AND action_id IN ({placeholders})
                  AND object_name IS NOT NULL AND object_name <> ''
                ORDER BY event_time, file_name, audit_file_offset, sequence_number''',
                path, self.database, *actions.keys())
            columns = [c[0] for c in cursor.description]
            groups = defaultdict(list)
            for values in cursor:
                row = dict(zip(columns, values))
                group = row['sequence_group_id']
                # SQL Server 2016+ sequence groups identify fragments across buffers/files.
                key = bytes(group).hex() if group is not None else f"{row['file_name']}:{row['audit_file_offset']}:{row['sequence_number']}"
                groups[key].append(row)
            events = []
            for key, rows in groups.items():
                rows.sort(key=lambda r: r['sequence_number'])
                first = rows[0]
                statement = ''.join(r['statement'] or '' for r in rows)
                numbers = [r['sequence_number'] for r in rows]
                fragments_ok = numbers == list(range(1, len(numbers)+1))
                # No end-of-sequence flag exists. A full-size final fragment is ambiguous.
                fragments_ok = fragments_ok and len(rows[-1]['statement'] or '') < 4000
                sql, reason = prepare_definition(statement, first['schema_name'] or 'dbo', first['object_name'])
                action = actions[str(first['action_id']).strip()]
                if not fragments_ok:
                    reason = 'Audit fragments may be incomplete or truncated; review only.'
                if not first['succeeded']:
                    reason = 'Audit permission check failed; review only.'
                if action not in ('CREATE','ALTER'):
                    reason = 'DML and DROP events are activity records, not deployable definitions.'
                kind = {'V':'VIEW','P':'PROCEDURE','FN':'FUNCTION','IF':'FUNCTION','TF':'FUNCTION','U':'TABLE'}.get(str(first['class_type']).strip(), 'OBJECT')
                # Audit class codes are not always sys.objects type codes; prefer definition header.
                import re
                match = re.search(r'\b(?:CREATE(?:\s+OR\s+ALTER)?|ALTER)\s+(TABLE|VIEW|PROCEDURE|PROC|FUNCTION)\b', statement, re.I)
                if match:
                    kind = match[1].upper().replace('PROC', 'PROCEDURE') if match[1].upper() == 'PROC' else match[1].upper()
                dt = first['event_time']
                timestamp = dt.replace(tzinfo=timezone.utc).isoformat() if dt.tzinfo is None else dt.isoformat()
                events.append(dict(database_name=self.database, schema_name=first['schema_name'] or 'dbo',
                    name=first['object_name'], kind=kind,
                    event_key=hashlib.sha256((self.database + ':' + key).encode()).hexdigest(),
                    statement=statement, actor=first['session_server_principal_name'] or first['server_principal_name'] or '(unknown)',
                    occurred_at=timestamp, action=action, action_id=str(first['action_id']).strip(),
                    permission_succeeded=int(first['succeeded']), complete=int(not reason and bool(sql)),
                    note=reason or 'Audit success records a permission check, not transaction commit. Review before applying.',
                    source='audit'))
            return events, actions
        finally:
            connection.close()

    def state(self, obj, connection=None):
        owned = connection is None
        connection = connection or self.connect()
        try:
            qualified = '[' + obj['schema_name'].replace(']', ']]') + '].[' + obj['name'].replace(']', ']]') + ']'
            row = connection.execute('''SELECT SUSER_SNAME(), IS_SRVROLEMEMBER('sysadmin'),
                HAS_PERMS_BY_NAME(?, 'OBJECT', 'ALTER'), HAS_PERMS_BY_NAME(?, 'SCHEMA', 'ALTER'),
                OBJECT_DEFINITION(OBJECT_ID(?)), OBJECT_ID(?),
                HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'CREATE VIEW'),
                HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'CREATE PROCEDURE'),
                HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'CREATE FUNCTION')''',
                qualified, obj['schema_name'], qualified, qualified).fetchone()
            kind_permission = {'VIEW':row[6], 'PROCEDURE':row[7], 'FUNCTION':row[8]}.get(obj['kind'], 0)
            allowed = row[1] == 1 or (row[5] is not None and row[2] == 1) or (row[5] is None and row[3] == 1 and kind_permission == 1)
            visible = row[5] is None or row[4] is not None
            # Cannot safely compare an encrypted or hidden existing definition.
            return dict(actor=row[0], allowed=bool(allowed and visible), definition=row[4],
                        fingerprint=hashlib.sha256((row[4] or '<absent>').encode()).hexdigest(), exists=row[5] is not None)
        finally:
            if owned:
                connection.close()

    def apply(self, obj, version, expected_fingerprint):
        sql, reason = prepare_definition(version['statement'], obj['schema_name'], obj['name'])
        if reason or not version['complete'] or version['source'] != 'audit':
            raise ValueError(reason or 'This version cannot be applied.')
        connection = self.connect()
        try:
            # Serialize application deployments. External DDL can still race; documented limitation.
            connection.execute("BEGIN TRANSACTION")
            lock = f"mssql-history:{self.database}:{obj['schema_name']}:{obj['name']}"
            result = connection.execute("DECLARE @r int; EXEC @r = sys.sp_getapplock @Resource=?, @LockMode='Exclusive', @LockOwner='Transaction', @LockTimeout=10000; SELECT @r", lock).fetchone()
            if result[0] < 0:
                raise ValueError('Another deployment holds the object lock. Retry after it finishes.')
            state = self.state(obj, connection)
            if not state['allowed']:
                raise PermissionError('The connected SQL login cannot alter this object or its definition is hidden.')
            if state['fingerprint'] != expected_fingerprint:
                raise ValueError('The live definition changed. Reload and review before applying.')
            connection.execute('SET ANSI_NULLS ON; SET QUOTED_IDENTIFIER ON;')
            connection.execute(sql)
            actual = self.state(obj, connection)['definition']
            if normalize_definition(actual) != normalize_definition(sql):
                raise ValueError('SQL Server definition did not match the selected version; deployment rolled back.')
            connection.commit()
            return state['actor']
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
