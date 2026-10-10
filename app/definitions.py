"""Conservative eligibility checks; SQL Server remains the permission authority."""
import re
import sqlparse
from sqlparse import lexer, tokens

IDENT = r'(?:\[(?:[^\]]|\]\])+\]|"(?:[^"]|"")+"|[A-Za-z_][\w@$#]*)'
HEADER = re.compile(rf'^\s*(CREATE\s+OR\s+ALTER|CREATE|ALTER)\s+(VIEW|PROC(?:EDURE)?|FUNCTION)\s+({IDENT})(?:\s*\.\s*({IDENT}))?(?=\s|\()', re.I)


def unquote(name):
    if name.startswith('['):
        return name[1:-1].replace(']]', ']')
    if name.startswith('"'):
        return name[1:-1].replace('""', '"')
    return name


def prepare_definition(statement, schema, name):
    # Strip comments using a lexer, so comment-like text in strings is retained.
    clean = sqlparse.format(statement or '', strip_comments=True).strip()
    match = HEADER.match(clean)
    if not match:
        return None, 'Only complete CREATE/ALTER VIEW, PROCEDURE, or FUNCTION definitions can be applied.'
    parsed_schema = unquote(match[3]) if match[4] else 'dbo'
    parsed_name = unquote(match[4] or match[3])
    if (parsed_schema.casefold(), parsed_name.casefold()) != (schema.casefold(), name.casefold()):
        return None, 'The definition header does not match the audited object.'
    if re.search(r'^\s*GO(?:\s|$)', clean, re.I | re.M):
        return None, 'Multiple batches (GO) are not supported.'
    if len(sqlparse.split(clean)) != 1:
        # sqlparse's generic splitter misreads some T-SQL procedure blocks (e.g.
        # COUNT(*) AS ...). Independently verify a balanced outer BEGIN/END body.
        meaningful = [(kind, value.upper()) for kind, value in lexer.tokenize(clean)
                      if kind not in tokens.Whitespace and kind not in tokens.Comment]
        begin = next((i for i, (kind, value) in enumerate(meaningful)
                      if kind in tokens.Keyword and value == 'BEGIN'), None)
        if begin is None:
            return None, 'Multi-statement batches are review-only. Use one complete module definition.'
        depth = 0
        end = None
        for index in range(begin, len(meaningful)):
            kind, value = meaningful[index]
            if kind in tokens.Keyword and value in ('BEGIN', 'CASE'):
                if value == 'BEGIN' and index+1 < len(meaningful) and meaningful[index+1][1] in ('TRAN', 'TRANSACTION', 'DISTRIBUTED'):
                    return None, 'Explicit transaction blocks require manual review.'
                depth += 1
            elif kind in tokens.Keyword and value == 'END':
                depth -= 1
                if depth == 0:
                    end = index
                    break
        if end is None or any(value != ';' for _, value in meaningful[end+1:]):
            return None, 'Statements outside the module body require manual review.'
    return 'CREATE OR ALTER' + clean[match.end(1):], None


def normalize_definition(statement):
    # Compare exact module text except for CREATE vs ALTER and surrounding whitespace.
    text = sqlparse.format((statement or '').replace('\r\n', '\n'), strip_comments=True).strip()
    return re.sub(r'^\s*(CREATE\s+OR\s+ALTER|CREATE|ALTER)\b', 'CREATE OR ALTER', text, count=1, flags=re.I)
