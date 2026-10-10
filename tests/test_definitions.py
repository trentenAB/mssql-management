import pytest
from app.definitions import prepare_definition, normalize_definition


@pytest.mark.parametrize('sql', [
    'CREATE VIEW dbo.Example AS SELECT 1 AS x;',
    '-- note\nALTER VIEW [dbo].[Example] AS SELECT \'-- literal\' AS x;',
    'CREATE OR ALTER FUNCTION dbo.Example(@n int) RETURNS int AS BEGIN RETURN @n+1; END;',
    'ALTER PROCEDURE dbo.Example AS BEGIN SELECT COUNT(*) AS Total FROM dbo.Items; END;',
    'ALTER PROCEDURE dbo.Example AS BEGIN SELECT 1; SELECT 2; END;',
    'ALTER PROCEDURE dbo.Example AS BEGIN SELECT CASE WHEN 1=1 THEN 2 END AS x; END;',
])
def test_complete_modules(sql):
    prepared, reason=prepare_definition(sql,'dbo','Example')
    assert reason is None
    assert prepared.startswith('CREATE OR ALTER')


@pytest.mark.parametrize('sql',[
    'UPDATE dbo.Example SET x=1;',
    'CREATE TABLE dbo.Example(id int);',
    'ALTER TABLE dbo.Example ADD x int;',
    'DROP VIEW dbo.Example;',
    'CREATE VIEW other.Example AS SELECT 1;',
    'CREATE VIEW db.dbo.Example AS SELECT 1;',
    'CREATE VIEW dbo.Other AS SELECT 1;',
    'CREATE VIEW dbo.Example AS SELECT 1; DROP TABLE dbo.Items;',
    'CREATE VIEW dbo.Example AS SELECT 1;\nGO\nDROP TABLE dbo.Items;',
    'ALTER PROCEDURE dbo.Example AS BEGIN SELECT 1; END; DROP TABLE dbo.Items;',
])
def test_ineligible_statements(sql):
    assert prepare_definition(sql,'dbo','Example')[0] is None


def test_comment_and_verb_normalization():
    assert normalize_definition('-- x\nALTER VIEW dbo.v AS SELECT 1;') == normalize_definition('CREATE OR ALTER VIEW dbo.v AS SELECT 1;')
