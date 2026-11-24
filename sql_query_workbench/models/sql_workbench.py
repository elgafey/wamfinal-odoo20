# Part of SQL Query Workbench. Copyright Viyug Infotech. License LGPL-3.
import datetime
import json
import logging

import pytz
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import SQL, date_utils

from ..services import engine
from ..services.sql_guard import (
    BUILTIN_PARAMS, SqlGuardError, analyse, check_protected, mask_match, relation_names, split_list, to_driver_sql,
)

_logger = logging.getLogger(__name__)

PREFIX = 'sql_query_workbench.'
DEFAULTS = {
    'row_limit': 2000,
    'timeout': 30,
    'export_limit': 100000,
    'retention_days': 90,
    'seq_scan_rows': 10000,
    'denied_tables': 'ir_config_parameter, res_users_apikeys, auth_totp_device, ir_mail_server, '
                     'fetchmail_server, iap_account, payment_provider, pg_statistic, pg_stats, '
                     'pg_stats_ext, pg_stats_ext_exprs',
    'denied_columns': 'password, totp_secret, smtp_pass',
    'mask_patterns': 'password, passwd, secret, token, api_key, apikey, private_key, smtp_pass, totp',
    'mask_enabled': '1',
}
HARD_ROW_LIMIT = 100000
MASK = '********'
# Columns that are always unreadable, whatever the settings (table.column; skipped
# when the table or column does not exist). The "Blocked columns" setting adds
# more (bare name = that column in every table), and with masking on, every text,
# binary or JSON column whose name matches a masked word is protected as well.
ALWAYS_PROTECTED = (
    'res_users.password', 'res_users.totp_secret', 'res_users.oauth_access_token', 'res_users.signup_token',
    'res_users_apikeys.key', 'auth_totp_device.key', 'ir_mail_server.smtp_pass',
    'ir_mail_server.smtp_ssl_private_key', 'fetchmail_server.password', 'iap_account.account_token',
    'pg_authid.rolpassword', 'pg_shadow.passwd', 'pg_user_mapping.umoptions', 'pg_user_mappings.umoptions',
)
TEXTLIKE = ('text', 'character varying', 'character')


class SqlWorkbench(models.AbstractModel):
    _name = 'sql.workbench'
    _description = 'SQL Query Workbench engine'

    # ------------------------------------------------------------------ access / settings
    def _require(self, level='user'):
        xmlid = 'sql_query_workbench.group_sqlw_manager' if level == 'manager' else 'sql_query_workbench.group_sqlw_user'
        if not self.env.user.has_group(xmlid):
            raise AccessError(self.env._("Only SQL Workbench users can do this."))

    @api.model
    def _settings(self):
        icp = self.env['ir.config_parameter'].sudo()
        res = {}
        for key, default in DEFAULTS.items():
            value = icp.get_str(PREFIX + key, '')
            if value in (False, None, ''):
                value = default
            elif isinstance(default, int):
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    value = default
            res[key] = value
        res['mask_enabled'] = res['mask_enabled'] not in ('0', 'False', 'false', '')
        return res

    @api.model
    def _limits(self, user=None):
        user = user or self.env.user
        s = self._settings()
        limits = {'row_limit': s['row_limit'], 'timeout': s['timeout'], 'export_limit': s['export_limit']}
        rules = self.env['sql.query.limit'].sudo().search([('group_id', 'in', user.all_group_ids.ids)])
        for key in limits:
            values = [r[key] for r in rules if r[key] > 0]
            if values:
                limits[key] = max(values)
        limits['row_limit'] = max(1, min(limits['row_limit'], HARD_ROW_LIMIT))
        limits['timeout'] = max(1, limits['timeout'])
        limits['export_limit'] = max(1, limits['export_limit'])
        return limits

    @api.model
    def _guard(self, sql):
        """Static checks, then the shadow views that hide protected columns
        (``analysis['shadow']``, created by the engine for the run)."""
        s = self._settings()
        try:
            analysis = analyse(sql, split_list(s['denied_tables']), split_list(s['denied_columns']))
            analysis['shadow'], refused_views = self._protection(relation_names(analysis), s)
            check_protected(analysis, {name for name, _b, _c in analysis['shadow']}, refused_views)
        except SqlGuardError as e:
            raise UserError(str(e)) from None
        return analysis

    @api.model
    def _protection(self, names, settings=None):
        """Shadow views for the relations among ``names`` that hold protected columns.

        Returns (shadow, refused_views): shadow is a list of (name, SQL body,
        column names); the engine creates each body as TEMPORARY VIEW <name> in
        the run's transaction, so an unqualified reference (pg_temp is searched
        first) reads the protected columns as ******** (text) or NULL, whatever
        the expression (whole-row values, JSON, casts, comparisons...).
        refused_views: existing views among ``names`` built on a protected column.
        """
        s = settings or self._settings()
        entries = split_list(s['denied_columns'])
        pairs = sorted({e for e in entries if '.' in e} | set(ALWAYS_PROTECTED))
        bare = sorted(e for e in entries if '.' not in e)
        likes = []
        if s['mask_enabled']:
            likes = ['%' + p.replace('\\', '\\\\').replace('%', r'\%').replace('_', r'\_') + '%'
                     for p in split_list(s['mask_patterns'])]
        self.env.cr.execute(SQL(r"""
            WITH RECURSIVE prot AS (
                SELECT a.attrelid, a.attnum
                  FROM pg_attribute a
                  JOIN pg_class c ON c.oid = a.attrelid AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
                  JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE a.attnum > 0 AND NOT a.attisdropped
                   AND (c.relname || '.' || a.attname = ANY(%(pairs)s)
                        OR (n.nspname NOT IN ('pg_catalog', 'information_schema')
                            AND (a.attname = ANY(%(bare)s)
                                 OR (a.atttypid IN ('text'::regtype, 'varchar'::regtype, 'bpchar'::regtype,
                                                    'bytea'::regtype, 'json'::regtype, 'jsonb'::regtype)
                                     AND a.attname NOT LIKE '%%\_id' AND a.attname NOT LIKE '%%\_ids'
                                     AND a.attname LIKE ANY(%(likes)s)))))
            ), dep(oid) AS (
                SELECT r.ev_class
                  FROM pg_depend d JOIN pg_rewrite r ON r.oid = d.objid
                 WHERE d.classid = 'pg_rewrite'::regclass AND d.refclassid = 'pg_class'::regclass
                   AND r.ev_class <> d.refobjid
                   AND ((d.refobjid, d.refobjsubid) IN (SELECT attrelid, attnum FROM prot)
                        OR (d.refobjsubid = 0 AND d.refobjid IN (SELECT attrelid FROM prot)))
                UNION
                SELECT r.ev_class
                  FROM dep JOIN pg_depend d ON d.refobjid = dep.oid
                       AND d.classid = 'pg_rewrite'::regclass AND d.refclassid = 'pg_class'::regclass
                  JOIN pg_rewrite r ON r.oid = d.objid AND r.ev_class <> dep.oid
            )
            SELECT c.relname, n.nspname, a.attname, format_type(a.atttypid, a.atttypmod),
                   (a.attrelid, a.attnum) IN (SELECT attrelid, attnum FROM prot),
                   c.oid IN (SELECT oid FROM dep)
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
              JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
             WHERE c.relname = ANY(%(names)s)
               AND c.oid = to_regclass(quote_ident(c.relname))
               AND (c.oid IN (SELECT attrelid FROM prot) OR c.oid IN (SELECT oid FROM dep))
             ORDER BY c.relname, a.attnum
        """, pairs=pairs, bare=bare, likes=likes, names=sorted(names)))
        tables, refused = {}, set()
        for relname, schema, col, ctype, protected, dependent in self.env.cr.fetchall():
            if dependent:
                refused.add(relname)
                continue
            tables.setdefault(relname, (schema, []))[1].append((col, ctype, protected))
        shadow = []
        for relname, (schema, cols) in sorted(tables.items()):
            exprs = [
                SQL.identifier(col) if not protected
                else SQL('%s::%s AS %s', MASK, SQL(ctype), SQL.identifier(col)) if ctype.split('(')[0] in TEXTLIKE
                else SQL('NULL::%s AS %s', SQL(ctype), SQL.identifier(col))
                for col, ctype, protected in cols
            ]
            body = SQL('SELECT %s FROM %s', SQL(', ').join(exprs), SQL.identifier(schema, relname))
            shadow.append((relname, body, [c[0] for c in cols]))
        return shadow, refused

    # ------------------------------------------------------------------ parameters
    @api.model
    def _builtin_values(self, user=None):
        user = user or self.env.user
        company = self.env.company if user == self.env.user else user.company_id
        companies = self.env.companies if user == self.env.user else user.company_ids
        return {
            'user_id': user.id,
            'company_id': company.id,
            'company_ids': companies.ids,
            'today': fields.Date.context_today(self.with_user(user)),
            'lang': user.lang or 'en_US',
        }

    @api.model
    def _dynamic_default(self, kind, user=None):
        user = user or self.env.user
        today = fields.Date.context_today(self.with_user(user))
        company = self.env.company if user == self.env.user else user.company_id
        if kind == 'today':
            return today
        if kind == 'yesterday':
            return today - datetime.timedelta(days=1)
        if kind == 'start_of_week':
            return today - datetime.timedelta(days=today.weekday())
        if kind == 'start_of_month':
            return today.replace(day=1)
        if kind == 'end_of_month':
            return date_utils.end_of(today, 'month')
        if kind == 'start_of_year':
            return today.replace(month=1, day=1)
        if kind == 'start_of_fiscal_year':
            if 'fiscalyear_last_month' in company._fields:
                return date_utils.get_fiscal_year(
                    today, day=company.fiscalyear_last_day, month=int(company.fiscalyear_last_month))[0]
            return today.replace(month=1, day=1)
        if kind == 'current_user':
            return user.id
        if kind == 'current_company':
            return company.id
        return None

    @api.model
    def _to_utc(self, value, user):
        tz = pytz.timezone(user.tz or 'UTC')
        return tz.localize(value).astimezone(pytz.utc).replace(tzinfo=None)

    @api.model
    def _coerce(self, ptype, raw, user=None, label=''):
        """Value from the UI (or a default) -> python value of the declared type."""
        user = user or self.env.user
        if raw in (None, '', False) and ptype not in ('boolean', 'integer', 'float', 'many2many'):
            return None
        try:
            if ptype == 'date':
                if isinstance(raw, datetime.datetime):
                    return raw.date()
                return raw if isinstance(raw, datetime.date) else datetime.date.fromisoformat(str(raw)[:10])
            if ptype == 'datetime':
                if isinstance(raw, datetime.datetime):
                    return raw
                if isinstance(raw, datetime.date):
                    return self._to_utc(datetime.datetime.combine(raw, datetime.time()), user)
                text = str(raw).replace('T', ' ')
                return self._to_utc(datetime.datetime.fromisoformat(text[:19] if len(text) > 16 else text), user)
            if ptype == 'integer':
                return None if raw in (None, '') else int(raw)
            if ptype == 'float':
                return None if raw in (None, '') else float(raw)
            if ptype == 'boolean':
                if isinstance(raw, str):
                    return raw.strip().lower() in ('1', 'true', 'yes', 'on')
                return bool(raw)
            if ptype == 'many2one':
                if isinstance(raw, (list, tuple)):
                    raw = raw[0] if raw else None
                return int(raw) if raw else None
            if ptype == 'many2many':
                if raw in (None, '', False):
                    return []
                if isinstance(raw, str):
                    raw = [p for p in raw.replace(';', ',').split(',') if p.strip()]
                return [int(v) for v in raw]
            return str(raw)
        except (TypeError, ValueError):
            raise UserError(self.env._("'%(value)s' is not a valid %(type)s for %(param)s.",
                                       value=raw, type=ptype, param=label or '?')) from None

    @api.model
    def _bind(self, analysis, declared, values, user=None, sample=False, loose=False):
        """Values for every placeholder of the statement.

        declared: sql.query.param records (saved queries) or None (console);
        values: {name: raw value} from the UI; sample: use type samples for
        missing values (validation dry run)."""
        user = user or self.env.user
        values = values or {}
        builtins = self._builtin_values(user)
        by_name = {p.name: p for p in (declared or [])}
        bound, missing = {}, []
        for name in analysis['params']:
            if name in by_name:
                p = by_name[name]
                raw = values.get(name)
                if raw in (None, '', []) and not (p.ptype == 'boolean' and raw is False):
                    raw = p._default_raw(user)
                value = self._coerce(p.ptype, raw, user, p.label or name)
                if value in (None, '') and p.ptype not in ('boolean',):
                    if sample:
                        value = p._sample_value()
                    elif p.required:
                        missing.append(p.label or name)
                bound[name] = value
            elif name in builtins:
                bound[name] = builtins[name]
            elif declared is None or loose:
                raw = values.get(name)
                if raw in (None, ''):
                    if not sample:
                        missing.append(name)
                    bound[name] = None
                else:
                    bound[name] = raw
            else:
                raise UserError(self.env._(
                    "The placeholder :%s is not declared. Add it in the Parameters tab.", name))
        if missing:
            raise UserError(self.env._("Please give a value for: %s", ', '.join(missing)))
        return bound

    # ------------------------------------------------------------------ execution
    @api.model
    def _table_models(self):
        return {M._table: name for name, M in self.env.registry.items() if not M._abstract and M._auto}

    @api.model
    def _columns(self, result, overrides=None, mask=True):
        overrides = overrides or {}
        s = self._settings()
        patterns = list(split_list(s['mask_patterns'])) if (mask and s['mask_enabled']) else []
        table_models = self._table_models()
        cols = []
        for idx, (name, oid) in enumerate(result['description']):
            tname, cat = result['types'].get(oid, ('unknown', 'X'))
            model = overrides.get(name) or False
            if not model and idx in result['sources']:
                table, col = result['sources'][idx]
                mname = table_models.get(table)
                if mname:
                    if col == 'id':
                        model = mname
                    else:
                        field = self.env[mname]._fields.get(col)
                        if field and field.type == 'many2one':
                            model = field.comodel_name
            cols.append({
                'name': name, 'type': tname, 'category': cat, 'numeric': cat == 'N',
                'model': model if model in self.env else False,
                'masked': bool(patterns) and mask_match(name, patterns),
            })
        return cols

    @api.model
    def _apply_mask(self, columns, rows):
        masked = [i for i, c in enumerate(columns) if c['masked']]
        if not masked:
            return rows
        out = []
        for row in rows:
            row = list(row)
            for i in masked:
                if isinstance(row[i], (str, bytes, memoryview, bytearray, dict, list)):
                    row[i] = MASK
            out.append(row)
        return out

    @api.model
    def _log(self, vals):
        vals.setdefault('user_id', self.env.uid)
        vals.setdefault('company_id', self.env.company.id)
        if 'source_label' not in vals:
            query = self.env['sql.query'].sudo().browse(vals.get('query_id') or [])
            vals['source_label'] = query.name or self.env._("Workbench (ad hoc)")
        if vals.get('sql'):
            vals['sql'] = vals['sql'][:20000]
        return self.env['sql.query.run'].sudo().create(vals)

    @api.model
    def _params_text(self, bound):
        return json.dumps({k: engine.jsonable(v) for k, v in bound.items()
                           if k not in ('company_ids', 'lang')}, default=str) if bound else ''

    @api.model
    def _execute(self, sql, values=None, *, query=None, origin='console', mode='run',
                 limit=None, raw=False, user=None, declared=None):
        """Guard, bind, run read-only, log. Returns a result dict (never raises for
        SQL errors: they come back as ok=False so the UI can show them inline)."""
        user = user or self.env.user
        limits = self._limits(user)
        row_limit = limit or limits['row_limit']
        log = {'query_id': query.id if query else False, 'origin': origin, 'sql': sql,
               'user_id': user.id, 'company_id': (self.env.company if user == self.env.user else user.company_id).id}
        try:
            analysis = self._guard(sql)
            if query:
                bound = self._bind(analysis, query.sudo().param_ids, values, user)
            else:
                bound = self._bind(analysis, declared, values, user, loose=True)
        except UserError as e:
            run = self._log(dict(log, status='blocked', error=e.args[0]))
            return {'ok': False, 'status': 'blocked', 'message': e.args[0], 'run_id': run.id}
        log['params_text'] = self._params_text(bound)
        driver_sql = to_driver_sql(sql, analysis)
        if mode in ('explain', 'explain_analyze'):
            if analysis['kind'] == 'explain':
                msg = self.env._("Remove EXPLAIN from the query to use the plan view.")
                return {'ok': False, 'status': 'blocked', 'message': msg}
            opts = 'ANALYZE, BUFFERS, FORMAT JSON' if mode == 'explain_analyze' else 'FORMAT JSON'
            driver_sql = f'EXPLAIN ({opts}) {driver_sql}'
        try:
            result = engine.run(self.env.cr.dbname, driver_sql, bound, limits['timeout'] * 1000,
                                row_limit, raw=raw, shadow=analysis['shadow'])
        except engine.QueryFailed as e:
            run = self._log(dict(log, status=e.status, error=e.message, duration_ms=getattr(e, 'duration_ms', 0)))
            return {'ok': False, 'status': e.status, 'message': e.message, 'line': e.line,
                    'position': e.position, 'run_id': run.id, 'duration_ms': getattr(e, 'duration_ms', 0)}
        run = self._log(dict(log, status='success', duration_ms=result['duration_ms'],
                             row_count=len(result['rows']), truncated=result['truncated']))
        if mode in ('explain', 'explain_analyze'):
            plan = result['rows'][0][0] if result['rows'] else []
            if isinstance(plan, str):
                plan = json.loads(plan)
            rels = set()

            def collect(node):
                if node.get('Relation Name'):
                    rels.add(node['Relation Name'])
                for child in node.get('Plans', []):
                    collect(child)
            collect(plan[0]['Plan'])
            flat = engine.flatten_plan(plan, self._settings()['seq_scan_rows'],
                                       engine.relation_rows(self.env.cr.dbname, rels))
            return {'ok': True, 'kind': 'plan', 'plan': flat, 'analyze': mode == 'explain_analyze',
                    'duration_ms': result['duration_ms'], 'run_id': run.id}
        overrides = {m.column_name: m.model_id.model for m in query.sudo().column_model_ids} if query else {}
        columns = self._columns(result, overrides)
        rows = self._apply_mask(columns, result['rows'])
        return {'ok': True, 'kind': 'rows', 'columns': columns, 'rows': rows,
                'row_count': len(rows), 'truncated': result['truncated'], 'limit': row_limit,
                'duration_ms': result['duration_ms'], 'run_id': run.id, 'bound': bound if raw else None}

    # ------------------------------------------------------------------ console API (RPC)
    @api.model
    def console_bootstrap(self):
        self._require('user')
        runs = self.env['sql.query.run'].search(
            [('user_id', '=', self.env.uid), ('query_id', '=', False), ('origin', '=', 'console')],
            order='id desc', limit=200)
        recent, seen = [], set()
        for r in runs:
            key = (r.sql or '').strip()
            if key and key not in seen:
                seen.add(key)
                recent.append({'id': r.id, 'sql': key, 'date': fields.Datetime.to_string(r.create_date),
                               'status': r.status})
            if len(recent) >= 25:
                break
        queries = self.env['sql.query'].search([], order='name')
        return {
            'limits': self._limits(),
            'is_manager': self.env.user.has_group('sql_query_workbench.group_sqlw_manager'),
            'recent': recent,
            'saved': [{'id': q.id, 'name': q.name, 'tags': q.tag_ids.mapped('name'), 'state': q.state}
                      for q in queries],
            'tags': self.env['sql.query.tag'].search([]).mapped('name'),
            'builtins': list(BUILTIN_PARAMS),
        }

    @api.model
    def console_params(self, sql):
        """Placeholders of an ad-hoc statement that need a value (built-ins excluded)."""
        self._require('user')
        try:
            names = analyse(sql)['params']
        except SqlGuardError:
            return []
        return [n for n in names if n not in BUILTIN_PARAMS]

    @api.model
    def console_run(self, sql, values=None, mode='run', query_id=None):
        """Run editor text. query_id (a saved query loaded in the editor) only lends
        its declared parameter types; the statement itself is the editor text."""
        self._require('user')
        if mode not in ('run', 'explain', 'explain_analyze'):
            raise UserError(self.env._("Unknown mode."))
        declared = None
        if query_id:
            q = self.env['sql.query'].browse(query_id)
            q.check_access('read')
            declared = q.sudo().param_ids
        return self._execute(sql, values, origin='explain' if mode != 'run' else 'console', mode=mode,
                             declared=declared)

    @api.model
    def console_load_query(self, query_id):
        self._require('user')
        q = self.env['sql.query'].browse(query_id)
        q.check_access('read')
        return {'id': q.id, 'name': q.name, 'sql': q.sql or '', 'can_edit': q.has_access('write'),
                'params': q.get_run_screen()['params']}

    @api.model
    def console_save(self, sql, name=None, query_id=None):
        """Save the editor text to a saved query (new draft, or update one the user may edit)."""
        self._require('user')
        self._guard(sql)
        Query = self.env['sql.query']
        if query_id:
            q = Query.browse(query_id)
            q.check_access('write')
            q.sql = sql
        else:
            q = Query.create({'name': name or self.env._("New query"), 'sql': sql})
            q._sync_params_from_sql()
        return {'id': q.id, 'name': q.name}

    # ------------------------------------------------------------------ schema browser
    @api.model
    def schema_tables(self):
        self._require('user')
        s = self._settings()
        denied = split_list(s['denied_tables'])
        self.env.cr.execute("""
            SELECT c.relname, c.relkind, GREATEST(c.reltuples, 0)::bigint,
                   pg_total_relation_size(c.oid), pg_size_pretty(pg_total_relation_size(c.oid))
              FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public' AND c.relkind IN ('r', 'v', 'm', 'p')
             ORDER BY c.relname
        """)
        rows = self.env.cr.fetchall()
        table_models = self._table_models()
        models_info = {m.model: m.name for m in self.env['ir.model'].sudo().search([])}
        kinds = {'r': 'table', 'p': 'table', 'v': 'view', 'm': 'materialized view'}
        out = []
        for name, kind, estimate, size, pretty in rows:
            model = table_models.get(name, '')
            out.append({'name': name, 'kind': kinds.get(kind, kind), 'rows': estimate, 'size': size,
                        'size_pretty': pretty, 'model': model, 'model_name': models_info.get(model, ''),
                        'denied': name in denied})
        return out

    @api.model
    def schema_table(self, table):
        self._require('user')
        cr = self.env.cr
        cr.execute("""SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                       WHERE n.nspname = 'public' AND c.relname = %s""", [table])
        row = cr.fetchone()
        if not row:
            raise UserError(self.env._("Table %s not found.", table))
        oid = row[0]
        s = self._settings()
        denied_cols = split_list(s['denied_columns'])
        model = self._table_models().get(table)
        fields_info = {}
        if model:
            for f in self.env['ir.model.fields'].sudo().search([('model', '=', model)]):
                fields_info[f.name] = (f.field_description, f.ttype, f.relation or '')
        cr.execute("""
            SELECT a.attname, format_type(a.atttypid, a.atttypmod), NOT a.attnotnull
              FROM pg_attribute a
             WHERE a.attrelid = %s AND a.attnum > 0 AND NOT a.attisdropped
             ORDER BY a.attnum
        """, [oid])
        columns = []
        for name, ctype, nullable in cr.fetchall():
            label, ttype, relation = fields_info.get(name, ('', '', ''))
            columns.append({'name': name, 'type': ctype, 'nullable': nullable, 'label': label,
                            'field_type': ttype, 'relation': relation, 'denied': name in denied_cols})
        cr.execute("""SELECT indexname, indexdef FROM pg_indexes
                       WHERE schemaname = 'public' AND tablename = %s ORDER BY indexname""", [table])
        indexes = [{'name': n, 'definition': d} for n, d in cr.fetchall()]
        cr.execute("""
            SELECT con.conname, a.attname, rc.relname, ra.attname
              FROM pg_constraint con
              JOIN pg_class rc ON rc.oid = con.confrelid
              JOIN LATERAL unnest(con.conkey, con.confkey) AS k(src, dst) ON TRUE
              JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.src
              JOIN pg_attribute ra ON ra.attrelid = con.confrelid AND ra.attnum = k.dst
             WHERE con.conrelid = %s AND con.contype = 'f'
             ORDER BY a.attname
        """, [oid])
        fks = [{'name': n, 'column': c, 'ref_table': rt, 'ref_column': rc} for n, c, rt, rc in cr.fetchall()]
        return {'name': table, 'model': model or '', 'columns': columns, 'indexes': indexes,
                'foreign_keys': fks}

    # ------------------------------------------------------------------ files
    @api.model
    def _export_payload(self, payload):
        """Run for an export/print. payload: {sql | query_id, values}. Returns
        (query, result) with raw python rows, masked, capped at the export limit."""
        query = None
        if payload.get('query_id'):
            query = self.env['sql.query'].browse(int(payload['query_id']))
            query.check_access('read')
            sql = query.sudo().sql
        else:
            self._require('user')
            sql = payload.get('sql') or ''
        return query, sql

    @api.model
    def export_file(self, payload):
        """Build a CSV or XLSX file. Returns (content, filename, mimetype) or raises UserError."""
        from ..services import exporter
        query, sql = self._export_payload(payload)
        fmt = payload.get('format') or 'csv'
        if query and not query.has_access('write') and query.state != 'valid':
            raise UserError(self.env._("This query is not validated yet."))
        res = self._execute(sql, payload.get('values'), query=query, origin=self.env.context.get('sqlw_origin', 'export'),
                            limit=self._limits()['export_limit'], raw=True)
        if not res['ok']:
            raise UserError(res['message'])
        names = [c['name'] for c in res['columns']]
        rows = res['rows']
        opts = payload.get('options') or {}
        base = (opts.get('filename') or (query.name if query else 'query')).strip() or 'query'
        base = ''.join(ch if ch.isalnum() or ch in '-_ .' else '_' for ch in base)[:80]
        if fmt == 'xlsx':
            lines = [f"{k}: {v}" for k, v in json.loads(self._params_text(res['bound']) or '{}').items()
                     if k not in ('user_id', 'company_id', 'today')]
            now = fields.Datetime.context_timestamp(self, fields.Datetime.now())
            data = exporter.to_xlsx(names, rows, query.name if query else self.env._("Query result"),
                                    self.env.company.name, now.strftime('%Y-%m-%d %H:%M'), lines,
                                    header=opts.get('header', True))
            return data, base + '.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        data = exporter.to_csv(names, rows, opts.get('separator', 'comma'), opts.get('quote', 'double'),
                               opts.get('header', True), opts.get('bom', False), opts.get('line_ending', 'crlf'))
        return data, base + '.csv', 'text/csv;charset=utf-8'

    @api.model
    def print_pdf(self, payload, orientation='portrait', title=None):
        query, sql = self._export_payload(payload)
        res = self._execute(sql, payload.get('values'), query=query, origin='print')
        if not res['ok']:
            raise UserError(res['message'])
        rec = self.env['sql.query.print'].create({
            'name': title or (query.name if query else self.env._("Query result")),
            'orientation': 'landscape' if orientation == 'landscape' else 'portrait',
            'columns_json': json.dumps([c['name'] for c in res['columns']]),
            'rows_json': json.dumps(res['rows'], default=str),
            'row_count': res['row_count'],
            'truncated': res['truncated'],
            'params_text': (self.env['sql.query.run'].browse(res['run_id']).sudo().params_text or ''),
        })
        xmlid = ('sql_query_workbench.action_report_result_landscape' if rec.orientation == 'landscape'
                 else 'sql_query_workbench.action_report_result_portrait')
        return self.env.ref(xmlid).report_action(rec, config=False)
