import sqlite3
from datetime import datetime, timezone

SCHEMA = '''
CREATE TABLE IF NOT EXISTS objects (
 id INTEGER PRIMARY KEY, database_name TEXT NOT NULL, schema_name TEXT NOT NULL,
 name TEXT NOT NULL, kind TEXT NOT NULL, applied_version_id INTEGER,
 UNIQUE(database_name, schema_name, name)
);
CREATE TABLE IF NOT EXISTS versions (
 id INTEGER PRIMARY KEY, object_id INTEGER NOT NULL REFERENCES objects(id),
 event_key TEXT UNIQUE NOT NULL, statement TEXT NOT NULL, actor TEXT NOT NULL,
 occurred_at TEXT NOT NULL, action TEXT NOT NULL, action_id TEXT NOT NULL,
 permission_succeeded INTEGER NOT NULL, complete INTEGER NOT NULL, note TEXT NOT NULL,
 source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deployments (
 id INTEGER PRIMARY KEY, object_id INTEGER NOT NULL REFERENCES objects(id),
 version_id INTEGER NOT NULL REFERENCES versions(id), actor TEXT NOT NULL,
 applied_at TEXT NOT NULL
);
'''


def connect(path):
    db = sqlite3.connect(path, timeout=20)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA journal_mode=WAL')
    return db


def initialize(path, demo=False):
    with connect(path) as db:
        db.executescript(SCHEMA)
        if demo and not db.execute('SELECT 1 FROM objects LIMIT 1').fetchone():
            fixtures = [
                ('ActiveCustomers', 'VIEW', [
                    ('2026-01-12T09:20:00Z', 'alex.chen', 'CREATE', 'CREATE VIEW dbo.ActiveCustomers AS\nSELECT CustomerId, Name, Email\nFROM dbo.Customers\nWHERE IsActive = 1;'),
                    ('2026-02-03T14:32:00Z', 'maya.patel', 'ALTER', 'ALTER VIEW dbo.ActiveCustomers AS\nSELECT CustomerId, Name, Email, Region\nFROM dbo.Customers\nWHERE IsActive = 1;'),
                    ('2026-02-18T11:05:00Z', 'alex.chen', 'ALTER', 'ALTER VIEW dbo.ActiveCustomers AS\nSELECT CustomerId, Name, Email, Region\nFROM dbo.Customers\nWHERE IsActive = 1\n  AND DeletedAt IS NULL;')]),
                ('GetOrderSummary', 'PROCEDURE', [
                    ('2026-01-15T08:00:00Z', 'sam.rivera', 'CREATE', 'CREATE PROCEDURE dbo.GetOrderSummary\n    @CustomerId int\nAS\nBEGIN\n    SELECT SUM(Total) AS Total\n    FROM dbo.Orders\n    WHERE CustomerId = @CustomerId;\nEND;'),
                    ('2026-02-09T16:10:00Z', 'maya.patel', 'ALTER', 'ALTER PROCEDURE dbo.GetOrderSummary\n    @CustomerId int\nAS\nBEGIN\n    SELECT COUNT(*) AS OrderCount, SUM(Total) AS Total\n    FROM dbo.Orders\n    WHERE CustomerId = @CustomerId\n      AND Status = \'Completed\';\nEND;')]),
                ('CalculateTax', 'FUNCTION', [('2026-02-01T10:00:00Z', 'sam.rivera', 'CREATE', 'CREATE FUNCTION dbo.CalculateTax(@Amount decimal(18,2))\nRETURNS decimal(18,2)\nAS\nBEGIN\n    RETURN @Amount * 0.08;\nEND;')]),
                ('Customers', 'TABLE', [
                    ('2026-01-10T09:00:00Z', 'alex.chen', 'CREATE', 'CREATE TABLE dbo.Customers (\n    CustomerId int PRIMARY KEY,\n    Name nvarchar(200),\n    Email nvarchar(320),\n    IsActive bit\n);'),
                    ('2026-02-03T14:00:00Z', 'maya.patel', 'ALTER', 'ALTER TABLE dbo.Customers ADD Region nvarchar(80);'),
                    ('2026-02-18T10:50:00Z', 'alex.chen', 'UPDATE', 'UPDATE dbo.Customers SET IsActive = 0 WHERE CustomerId = 42;')])]
            from .definitions import prepare_definition
            for name, kind, entries in fixtures:
                for index, (timestamp, actor, action, statement) in enumerate(entries):
                    _, reason = prepare_definition(statement, 'dbo', name)
                    add_event(db, dict(database_name='CommerceDemo', schema_name='dbo', name=name, kind=kind,
                        event_key=f'demo:{name}:{index}', statement=statement, actor=actor, occurred_at=timestamp,
                        action=action, action_id={'CREATE':'CR','ALTER':'AL','UPDATE':'UP'}[action],
                        permission_succeeded=1, complete=not reason, note=reason or '', source='demo'))


def add_event(db, event):
    db.execute('INSERT OR IGNORE INTO objects(database_name,schema_name,name,kind) VALUES(?,?,?,?)',
               tuple(event[k] for k in ('database_name','schema_name','name','kind')))
    if event['kind'] != 'OBJECT':
        db.execute('UPDATE objects SET kind=? WHERE database_name=? AND schema_name=? AND name=?',
                   (event['kind'],event['database_name'],event['schema_name'],event['name']))
    object_id = db.execute('SELECT id FROM objects WHERE database_name=? AND schema_name=? AND name=?',
                          tuple(event[k] for k in ('database_name','schema_name','name'))).fetchone()[0]
    keys = ('event_key','statement','actor','occurred_at','action','action_id','permission_succeeded','complete','note','source')
    result = db.execute(f'INSERT OR IGNORE INTO versions(object_id,{",".join(keys)}) VALUES({",".join("?" for _ in range(11))})',
                       (object_id, *(event[k] for k in keys)))
    return result.rowcount


def utcnow():
    return datetime.now(timezone.utc).isoformat()
