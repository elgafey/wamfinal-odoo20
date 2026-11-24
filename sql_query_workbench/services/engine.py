# Part of SQL Query Workbench. Copyright Viyug Infotech. License LGPL-3.
"""Read-only execution on a separate database connection.

Every call borrows its own connection, creates the shadow views that hide
protected columns (temporary, so they live in pg_temp, which PostgreSQL
searches first), switches the transaction to READ ONLY with a statement/lock
timeout, fetches at most ``row_limit + 1`` rows and always rolls back, which
drops the views. It never uses the request cursor, so nothing the query does
can reach Odoo's transaction.
"""
import base64
import datetime
import decimal
import json
import time
import uuid

import psycopg2

from odoo import sql_db
from odoo.tools import SQL

TIMEOUT_CODES = {'57014'}  # query_canceled (statement_timeout)


class QueryFailed(Exception):
    def __init__(self, message, status='error', position=None, line=None, pgcode=None):
        super().__init__(message)
        self.message, self.status = message, status
        self.position, self.line, self.pgcode = position, line, pgcode


def jsonable(value):
    """Python value from psycopg2 -> JSON-friendly value for the grid."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if value == value and value not in (float('inf'), float('-inf')) else str(value)
    if isinstance(value, decimal.Decimal):
        return float(value) if value.is_finite() else str(value)
    if isinstance(value, datetime.datetime):
        return value.isoformat(sep=' ', timespec='seconds')
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, datetime.timedelta):
        return str(value)
    if isinstance(value, (bytes, memoryview, bytearray)):
        return f'<binary {len(bytes(value))} bytes>'
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, default=str, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def _line_of(query, position):
    if not position:
        return None
    return query[:max(int(position) - 1, 0)].count('\n') + 1


def _create_shadow(cr, shadow):
    """CREATE TEMPORARY VIEW for each (name, body, columns); returns {view oid: (name, columns)}.

    A read-only transaction refuses CREATE, so this runs first and the caller
    switches to read-only afterwards. Fails closed if an unqualified name does
    not resolve to its view (e.g. a search_path that puts pg_temp later).
    """
    try:
        for name, body, _cols in shadow:
            cr.execute(SQL("CREATE TEMPORARY VIEW %s AS %s", SQL.identifier(name), body), log_exceptions=False)
    except psycopg2.Error as e:
        raise QueryFailed(f"Protected columns could not be hidden for this run: {e.pgerror or e}", 'blocked') from None
    names = [name for name, _b, _c in shadow]
    cr.execute("""
        SELECT c.oid, c.relname FROM pg_class c
         WHERE c.relnamespace = pg_my_temp_schema() AND c.relname = ANY(%s)
           AND c.oid = to_regclass(quote_ident(c.relname))
    """, [names])
    oids = {name: oid for oid, name in cr.fetchall()}
    if set(oids) != set(names):
        raise QueryFailed("Protected columns could not be hidden for this run; the query was not executed.",
                          'blocked')
    return {oids[name]: (name, cols) for name, _b, cols in shadow}


def run(dbname, query, params, timeout_ms, row_limit, *, raw=False, shadow=()):
    """Execute ``query`` (driver syntax) with ``params`` in a read-only transaction.

    shadow: [(relation name, SQL body, column names)] from sql.workbench._protection.

    Returns dict(description, rows, truncated, duration_ms, types, sources) where
    types maps type oid -> (name, category) and sources maps column index ->
    (table_name, column_name) for columns read straight from a table.
    raw=True returns the python values (exports); otherwise rows are JSON-friendly.
    """
    # the read-only pool opens READ ONLY transactions, where CREATE is refused
    cr = sql_db.db_connect(dbname, readonly=not shadow).cursor()
    try:
        views = _create_shadow(cr, shadow) if shadow else {}
        cr.execute("SET LOCAL transaction_read_only = on")
        cr.execute("SET LOCAL statement_timeout = %s" % int(timeout_ms))
        cr.execute("SET LOCAL lock_timeout = %s" % max(int(timeout_ms) // 2, 1))
        start = time.monotonic()
        try:
            cr.execute(query, params, log_exceptions=False)
            description = cr.description or []
            rows = cr.fetchmany(row_limit + 1) if description else []
        except psycopg2.Error as e:
            duration = int((time.monotonic() - start) * 1000)
            status = 'timeout' if e.pgcode in TIMEOUT_CODES else 'error'
            message = (e.pgerror or str(e)).strip()
            if status == 'timeout':
                message = f"Stopped after the {int(timeout_ms) // 1000} s statement timeout. {message}"
            position = getattr(getattr(e, 'diag', None), 'statement_position', None)
            mogrified = ''
            try:
                mogrified = cr.mogrify(query, params).decode()
            except Exception:  # noqa: BLE001 - only used to locate the error line
                mogrified = query
            err = QueryFailed(message, status, position, _line_of(mogrified, position), e.pgcode)
            err.duration_ms = duration
            raise err from None
        duration = int((time.monotonic() - start) * 1000)
        truncated = len(rows) > row_limit
        rows = rows[:row_limit]
        cr.rollback()  # end the user statement's transaction before catalog lookups
        cr.execute("SET TRANSACTION READ ONLY")
        oids = sorted({c.type_code for c in description})
        types = {}
        if oids:
            cr.execute("SELECT oid, format_type(oid, NULL), typcategory FROM pg_type WHERE oid = ANY(%s)", [oids])
            types = {oid: (name, cat) for oid, name, cat in cr.fetchall()}
        pairs = sorted({(c.table_oid, c.table_column) for c in description
                        if c.table_oid and c.table_column and c.table_oid not in views})
        sources = {idx: (views[c.table_oid][0], views[c.table_oid][1][c.table_column - 1])
                   for idx, c in enumerate(description) if c.table_oid in views and c.table_column}
        if pairs:
            cr.execute("""
                SELECT a.attrelid, a.attnum, c.relname, a.attname
                  FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
                 WHERE (a.attrelid, a.attnum) IN %s
            """, [tuple(pairs)])
            names = {(r[0], r[1]): (r[2], r[3]) for r in cr.fetchall()}
            for idx, col in enumerate(description):
                if (col.table_oid, col.table_column) in names:
                    sources[idx] = names[(col.table_oid, col.table_column)]
        if not raw:
            rows = [[jsonable(v) for v in row] for row in rows]
        return {
            'description': [(c.name, c.type_code) for c in description],
            'rows': rows, 'truncated': truncated, 'duration_ms': duration,
            'types': types, 'sources': sources,
        }
    finally:
        cr.rollback()
        cr.close()


def relation_rows(dbname, relations):
    """{relname: reltuples} for the given relation names (read-only connection)."""
    if not relations:
        return {}
    cr = sql_db.db_connect(dbname, readonly=True).cursor()
    try:
        cr.execute("SELECT relname, reltuples FROM pg_class WHERE relname = ANY(%s)", [list(relations)])
        return {name: max(int(rows), 0) for name, rows in cr.fetchall()}
    finally:
        cr.rollback()
        cr.close()


def flatten_plan(plan, seq_scan_rows, rel_rows):
    """EXPLAIN (FORMAT JSON) output -> list of nodes with depth and cost share."""
    root = plan[0] if isinstance(plan, list) else plan
    top = root['Plan']
    total = top.get('Total Cost') or 0
    nodes = []

    def walk(node, depth):
        rel = node.get('Relation Name')
        est_rel = rel_rows.get(rel, 0) if rel else 0
        cost = node.get('Total Cost') or 0
        nodes.append({
            'depth': depth,
            'node_type': node.get('Node Type'),
            'relation': rel or '',
            'alias': node.get('Alias') if node.get('Alias') != rel else '',
            'index': node.get('Index Name') or '',
            'join_type': node.get('Join Type') or '',
            'strategy': node.get('Strategy') or '',
            'condition': node.get('Index Cond') or node.get('Hash Cond') or node.get('Merge Cond')
            or node.get('Join Filter') or node.get('Filter') or '',
            'est_rows': node.get('Plan Rows'),
            'total_cost': cost,
            'cost_share': round(cost * 100.0 / total, 1) if total else 0,
            'actual_rows': node.get('Actual Rows'),
            'actual_ms': node.get('Actual Total Time'),
            'loops': node.get('Actual Loops'),
            'table_rows': est_rel,
            'seq_scan_warning': node.get('Node Type') == 'Seq Scan' and est_rel >= seq_scan_rows,
        })
        for child in node.get('Plans', []):
            walk(child, depth + 1)

    walk(top, 0)
    return {
        'nodes': nodes,
        'planning_ms': root.get('Planning Time'),
        'execution_ms': root.get('Execution Time'),
        'total_cost': total,
    }


def b64(data):
    return base64.b64encode(data).decode()
