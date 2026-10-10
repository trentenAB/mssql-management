from datetime import datetime
import pytest
from app.sqlserver import SqlServer

COLUMNS = ['event_time','sequence_number','action_id','succeeded','session_server_principal_name',
           'server_principal_name','database_name','schema_name','object_name','statement',
           'file_name','audit_file_offset','sequence_group_id','class_type']


class AuditConnection:
    description=[(name,) for name in COLUMNS]
    closed=False
    def __init__(self,rows): self.rows=rows; self.calls=[]
    def cursor(self): return self
    def execute(self,sql,*params): self.calls.append((sql,params)); return self
    def fetchall(self): return [('CR','CREATE'),('AL','ALTER'),('IN','INSERT'),('UP','UPDATE'),('DL','DELETE'),('DR','DROP')]
    def __iter__(self): return iter(self.rows)
    def close(self): self.closed=True


def audit_row(sql,seq=1,group=b'one',action='AL',success=True):
    return (datetime(2026,1,1),seq,action,success,'alice','alice','db','dbo','v',sql,'/audit/a.sqlaudit',123,group,'V')


def test_ingestion_reassembles_fragments_and_labels_dml(monkeypatch):
    connection=AuditConnection([
        audit_row('ALTER VIEW dbo.v AS '), audit_row('SELECT 1;',2),
        audit_row('UPDATE dbo.v SET x=1;',group=b'two',action='UP'),
        audit_row('ALTER VIEW dbo.v AS SELECT 2;',group=b'three',success=False)])
    backend=SqlServer('not-used','db')
    monkeypatch.setattr(backend,'connect',lambda:connection)
    events,actions=backend.import_events('/audit/*.sqlaudit')
    assert events[0]['statement']=='ALTER VIEW dbo.v AS SELECT 1;'
    assert events[0]['complete']==1 and events[0]['actor']=='alice'
    assert events[0]['occurred_at'].endswith('+00:00')
    assert events[1]['complete']==0 and events[1]['action']=='UPDATE'
    assert events[2]['complete']==0
    assert actions['DL']=='DELETE'
    assert connection.closed
    assert connection.calls[1][1][:2]==('/audit/*.sqlaudit','db')


@pytest.mark.parametrize('rows', [
    [audit_row('ALTER VIEW dbo.v AS SELECT 1;',seq=2)],
    [audit_row('ALTER VIEW dbo.v AS ' + 'x'*3981)],
])
def test_incomplete_fragments_cannot_deploy(monkeypatch,rows):
    connection=AuditConnection(rows)
    backend=SqlServer('unused','db')
    monkeypatch.setattr(backend,'connect',lambda:connection)
    events,_=backend.import_events('/audit/*.sqlaudit')
    assert not events[0]['complete']


class ApplyConnection:
    committed=False
    rolled_back=False
    closed=False
    executed=[]
    def execute(self,sql,*args): self.executed.append(sql); return self
    def fetchone(self): return [0]
    def commit(self): self.committed=True
    def rollback(self): self.rolled_back=True
    def close(self): self.closed=True


@pytest.mark.parametrize('mode',['success','denied','stale','mismatch'])
def test_transactional_apply(monkeypatch,mode):
    connection=ApplyConnection()
    connection.executed=[]
    backend=SqlServer('unused','db')
    monkeypatch.setattr(backend,'connect',lambda:connection)
    calls=0
    def state(obj,conn=None):
        nonlocal calls
        calls+=1
        return dict(actor='sql.actor', allowed=mode!='denied', fingerprint='other' if mode=='stale' else 'hash',
                    definition='CREATE OR ALTER VIEW dbo.v AS SELECT 1;' if mode!='mismatch' else 'different')
    monkeypatch.setattr(backend,'state',state)
    obj={'schema_name':'dbo','name':'v'}
    version={'statement':'ALTER VIEW dbo.v AS SELECT 1;', 'complete':1,'source':'audit'}
    if mode=='success':
        assert backend.apply(obj,version,'hash')=='sql.actor'
        assert connection.committed and not connection.rolled_back
    else:
        with pytest.raises((ValueError,PermissionError)):
            backend.apply(obj,version,'hash')
        assert connection.rolled_back and not connection.committed
    assert connection.closed
    if mode in ('denied','stale'):
        assert not any(sql.startswith('CREATE OR ALTER') for sql in connection.executed)
