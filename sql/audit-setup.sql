-- TEMPLATE ONLY: review paths, database name, scope, retention and permissions first.
-- Run on SQL Server 2016 SP1+ as an authorized DBA. Directory must already exist
-- on the SQL Server host and be writable by its service account.
USE master;
GO
CREATE SERVER AUDIT ObjectHistoryAudit
TO FILE (FILEPATH = '/var/opt/mssql/audit/', MAXSIZE = 256 MB, MAX_ROLLOVER_FILES = 20)
WITH (ON_FAILURE = CONTINUE);
GO
ALTER SERVER AUDIT ObjectHistoryAudit WITH (STATE = ON);
GO
-- Replace YourDatabase before executing.
USE [YourDatabase];
GO
CREATE DATABASE AUDIT SPECIFICATION ObjectHistorySpecification
FOR SERVER AUDIT ObjectHistoryAudit
ADD (SCHEMA_OBJECT_CHANGE_GROUP),
ADD (DATABASE_OBJECT_CHANGE_GROUP),
-- DML capture can be extremely high volume and may expose sensitive values.
ADD (INSERT ON DATABASE::[YourDatabase] BY [public]),
ADD (UPDATE ON DATABASE::[YourDatabase] BY [public]),
ADD (DELETE ON DATABASE::[YourDatabase] BY [public])
WITH (STATE = ON);
GO
-- Authoritative IDs on THIS server. Typically CR, AL, DR, IN, UP, DL.
SELECT DISTINCT action_id, name, class_desc, covering_action_name
FROM sys.dm_audit_actions
WHERE name IN ('CREATE', 'ALTER', 'DROP', 'INSERT', 'UPDATE', 'DELETE')
ORDER BY name, action_id;
GO
