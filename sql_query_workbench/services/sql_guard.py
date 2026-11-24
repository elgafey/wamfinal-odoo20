# Part of SQL Query Workbench. Copyright Viyug Infotech. License LGPL-3.
"""Static checks for workbench SQL, independent of Odoo.

The guard is the first of three layers (guard, READ ONLY transaction with a
statement timeout, unconditional rollback). It tokenizes the statement while
skipping string literals, quoted text and comments, then:

* accepts exactly one SELECT, WITH or EXPLAIN statement,
* refuses write/DDL/transaction keywords and server-side functions that act
  outside the transaction (file access, backend signals, advisory locks,
  settings, dynamic SQL helpers),
* refuses tables and columns from the denylists,
* turns ``:name`` placeholders into driver parameters (values are never
  formatted into the SQL text).
"""
import re

ALLOWED_FIRST = {'select', 'with', 'explain'}

FORBIDDEN_WORDS = {
    'insert', 'update', 'delete', 'merge', 'truncate', 'create', 'alter', 'drop',
    'grant', 'revoke', 'copy', 'vacuum', 'reindex', 'cluster', 'lock', 'refresh',
    'notify', 'listen', 'unlisten', 'execute', 'prepare', 'deallocate', 'set',
    'begin', 'commit', 'rollback', 'savepoint', 'into', 'do', 'call', 'import',
    'security', 'checkpoint', 'discard', 'load', 'reassign',
}

# exact function names, then prefixes / fragments
FORBIDDEN_FUNCTIONS = {
    'set_config', 'pg_reload_conf', 'pg_rotate_logfile', 'pg_terminate_backend',
    'pg_cancel_backend', 'pg_stat_file', 'pg_notify', 'ts_stat', 'pg_promote',
    'pg_switch_wal', 'pg_create_restore_point', 'pg_log_backend_memory_contexts',
    'pg_import_system_collations', 'ts_rewrite', 'nextval', 'setval', 'currval', 'lastval',
}
FORBIDDEN_PREFIXES = (
    'pg_read_', 'pg_ls_', 'pg_file', 'lo_', 'dblink', 'pg_advisory', 'pg_try_advisory',
    'pg_logical_', 'pg_replication_', 'pg_create_', 'pg_drop_', 'pg_backup_',
    'pg_start_backup', 'pg_stop_backup', 'pg_wal_replay',
    'pg_temp', 'pg_toast',  # the shadow views live in pg_temp; toast tables hold raw column data
)
FORBIDDEN_FRAGMENTS = ('_to_xml',)  # query_to_xml, table_to_xml... run SQL given as text

BUILTIN_PARAMS = ('user_id', 'company_id', 'company_ids', 'today', 'lang')

_IDENT_RE = re.compile(r'[A-Za-z_\u0080-￿][A-Za-z0-9_$\u0080-￿]*')
_PARAM_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
_NUMBER_RE = re.compile(r'(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?')
_DOLLAR_RE = re.compile(r'\$([A-Za-z_][A-Za-z0-9_]*)?\$')


class SqlGuardError(ValueError):
    """Statement refused by the guard (message is shown to the user)."""


def tokenize(sql):
    """Return tokens as (kind, value, start, end).

    kinds: ident (lower-cased), qident (quoted identifier, as written),
    string, number, param (name without the colon), op.
    Comments and whitespace are dropped.
    """
    tokens, i, n = [], 0, len(sql)
    while i < n:
        c = sql[i]
        if c.isspace():
            i += 1
        elif sql.startswith('--', i):
            j = sql.find('\n', i)
            i = n if j < 0 else j
        elif sql.startswith('/*', i):
            depth, j = 1, i + 2
            while j < n and depth:
                if sql.startswith('/*', j):
                    depth, j = depth + 1, j + 2
                elif sql.startswith('*/', j):
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            if depth:
                raise SqlGuardError("Unterminated comment.")
            i = j
        elif c in 'uU' and sql[i + 1:i + 3] in ('&"', "&'"):
            # U&"..." names could spell a denylisted table with escapes
            raise SqlGuardError("Unicode-escaped names and strings (U&) are not supported.")
        elif c == "'" or (c in 'eEbBxXnN' and sql[i + 1:i + 2] == "'"):
            escape = c in 'eE'
            j = i + (1 if c == "'" else 2)
            while True:
                if j >= n:
                    raise SqlGuardError("Unterminated string literal.")
                if escape and sql[j] == '\\':
                    j += 2
                    continue
                if sql[j] == "'":
                    if sql[j + 1:j + 2] == "'":
                        j += 2
                        continue
                    break
                j += 1
            tokens.append(('string', sql[i:j + 1], i, j + 1))
            i = j + 1
        elif c == '"':
            j = i + 1
            while True:
                j = sql.find('"', j)
                if j < 0:
                    raise SqlGuardError("Unterminated quoted identifier.")
                if sql[j + 1:j + 2] == '"':
                    j += 2
                    continue
                break
            tokens.append(('qident', sql[i + 1:j].replace('""', '"'), i, j + 1))
            i = j + 1
        elif c == '$' and _DOLLAR_RE.match(sql, i):
            tag = _DOLLAR_RE.match(sql, i).group(0)
            j = sql.find(tag, i + len(tag))
            if j < 0:
                raise SqlGuardError("Unterminated dollar-quoted string.")
            tokens.append(('string', sql[i:j + len(tag)], i, j + len(tag)))
            i = j + len(tag)
        elif c == ':':
            if sql[i + 1:i + 2] == ':':
                tokens.append(('op', '::', i, i + 2))
                i += 2
            elif (m := _PARAM_RE.match(sql, i + 1)):
                tokens.append(('param', m.group(0), i, m.end()))
                i = m.end()
            else:
                tokens.append(('op', ':', i, i + 1))
                i += 1
        elif (m := _IDENT_RE.match(sql, i)):
            tokens.append(('ident', m.group(0).lower(), i, m.end()))
            i = m.end()
        elif (m := _NUMBER_RE.match(sql, i)):
            tokens.append(('number', m.group(0), i, m.end()))
            i = m.end()
        else:
            tokens.append(('op', c, i, i + 1))
            i += 1
    return tokens


def _is_forbidden_function(name):
    return (name in FORBIDDEN_FUNCTIONS or name.startswith(FORBIDDEN_PREFIXES)
            or any(f in name for f in FORBIDDEN_FRAGMENTS))


def split_list(text):
    """'a, b\\nc' -> {'a', 'b', 'c'} (lower-case)."""
    return {p.strip().lower() for p in re.split(r'[\s,;]+', text or '') if p.strip()}


def analyse(sql, denied_tables=(), denied_columns=()):
    """Check one statement. Returns dict(kind, params, tokens, end).

    kind: 'select' or 'explain'; params: placeholder names in order of first use;
    end: offset where the statement ends (trailing semicolons excluded).
    Raises SqlGuardError with a user-facing message.
    """
    tokens = tokenize(sql or '')
    while tokens and tokens[-1][1] == ';':
        tokens.pop()
    if not tokens:
        raise SqlGuardError("The query is empty.")
    if any(t[1] == ';' for t in tokens if t[0] == 'op'):
        raise SqlGuardError("Only one statement can be run at a time. Remove the extra ';'.")
    k = 0
    while k < len(tokens) and tokens[k][1] == '(':
        k += 1
    first = tokens[k][1] if k < len(tokens) and tokens[k][0] == 'ident' else ''
    if first not in ALLOWED_FIRST:
        raise SqlGuardError(
            "Only SELECT, WITH and EXPLAIN statements are allowed. The workbench is read-only.")
    kind = 'explain' if first == 'explain' else 'select'
    if kind == 'explain':
        k += 1
        if k < len(tokens) and tokens[k][1] == '(':
            depth = 0
            while k < len(tokens):
                depth += {'(': 1, ')': -1}.get(tokens[k][1], 0) if tokens[k][0] == 'op' else 0
                k += 1
                if depth == 0:
                    break
        while k < len(tokens) and tokens[k][0] == 'ident' and tokens[k][1] in ('analyze', 'analyse', 'verbose'):
            k += 1
        if k >= len(tokens) or tokens[k][1] not in ('select', 'with') or tokens[k][0] != 'ident':
            raise SqlGuardError("EXPLAIN is only allowed on a SELECT or WITH statement.")
    denied_tables = {t.lower() for t in denied_tables}
    denied_columns = {c.lower() for c in denied_columns}
    params = []
    for kind_, value, _s, _e in tokens:
        if kind_ == 'param':
            if value not in params:
                params.append(value)
            continue
        if kind_ not in ('ident', 'qident'):
            continue
        low = value.lower()
        if kind_ == 'ident' and low in FORBIDDEN_WORDS:
            raise SqlGuardError(f"'{value.upper()}' is not allowed: the workbench only reads data.")
        if _is_forbidden_function(low):
            raise SqlGuardError(f"The function or object '{value}' is blocked by the workbench.")
        if low in denied_tables:
            raise SqlGuardError(f"The table '{value}' is on the denylist (Settings > SQL Workbench).")
        if low in denied_columns:
            raise SqlGuardError(f"The column '{value}' is on the denylist (Settings > SQL Workbench).")
    return {'kind': kind, 'params': params, 'tokens': tokens, 'end': tokens[-1][3]}


def relation_names(analysis):
    """Every identifier of the statement, as PostgreSQL resolves it (a superset
    of the relations it can read: a relation cannot be reached without its name)."""
    return {v for k, v, _s, _e in analysis['tokens'] if k in ('ident', 'qident')}


def check_protected(analysis, shadowed, refused_views=()):
    """Refuse ways around the shadow views of tables holding protected columns.

    shadowed: relations replaced by a temporary view for this run. A qualified
    name (public.res_users) would skip the view, so it is refused.
    refused_views: existing views built on protected columns.
    """
    tokens = analysis['tokens']
    for i, (kind, value, _s, _e) in enumerate(tokens):
        if kind not in ('ident', 'qident'):
            continue
        if value in refused_views:
            raise SqlGuardError(f"The view '{value}' reads protected columns and is blocked by the workbench.")
        if value in shadowed and i and tokens[i - 1][:2] == ('op', '.'):
            raise SqlGuardError(
                f"Write '{value}' without a schema name: it holds protected columns "
                "(Settings > SQL Workbench).")


def to_driver_sql(sql, analysis):
    """Rewrite ':name' placeholders as '%(name)s' and escape every other '%'.

    The result is meant for cursor.execute(query, dict_of_values): the driver
    binds the values, so they are never concatenated into the statement.
    """
    out, pos = [], 0
    for kind, value, start, end in analysis['tokens']:
        if kind == 'param':
            out.append(sql[pos:start].replace('%', '%%'))
            out.append(f'%({value})s')
            pos = end
    out.append(sql[pos:analysis['end']].replace('%', '%%'))
    return ''.join(out)


def mask_match(column, patterns):
    """True if a result column name looks like a credential (not a foreign key)."""
    low = (column or '').lower()
    if low.endswith(('_id', '_ids')):
        return False
    return any(p in low for p in patterns)
