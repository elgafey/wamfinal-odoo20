# Part of SQL Query Workbench. Copyright Viyug Infotech. License LGPL-3.
import datetime
import re

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from ..services import engine
from ..services.sql_guard import BUILTIN_PARAMS, SqlGuardError, analyse, to_driver_sql

PARAM_TYPES = [
    ('date', 'Date'),
    ('datetime', 'Date and time'),
    ('integer', 'Integer'),
    ('float', 'Decimal number'),
    ('char', 'Text'),
    ('boolean', 'Yes / No'),
    ('selection', 'Selection'),
    ('many2one', 'Record'),
    ('many2many', 'Record list'),
]
DEFAULT_KINDS = [
    ('none', 'No default'),
    ('fixed', 'Fixed value'),
    ('today', 'Today'),
    ('yesterday', 'Yesterday'),
    ('start_of_week', 'Start of this week'),
    ('start_of_month', 'Start of this month'),
    ('end_of_month', 'End of this month'),
    ('start_of_year', 'Start of this year'),
    ('start_of_fiscal_year', 'Start of the fiscal year'),
    ('current_user', 'Current user'),
    ('current_company', 'Current company'),
]
NAME_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


class SqlQueryTag(models.Model):
    _name = 'sql.query.tag'
    _description = 'SQL query tag'
    _order = 'name'

    name = fields.Char(required=True, translate=True)
    color = fields.Integer()

    _name_uniq = models.Constraint('UNIQUE (name)', 'This tag already exists.')


class SqlQuery(models.Model):
    _name = 'sql.query'
    _description = 'Saved SQL query'
    _inherit = ['mail.thread']
    _order = 'sequence, name, id'

    name = fields.Char(required=True, tracking=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Text(string='Notes', help="What the query answers, how to read it, caveats.")
    sql = fields.Text(string='SQL', tracking=True, groups='sql_query_workbench.group_sqlw_user',
                      default="SELECT id, name\n  FROM res_partner\n ORDER BY id DESC\n LIMIT 50")
    tag_ids = fields.Many2many('sql.query.tag', string='Tags')
    param_ids = fields.One2many('sql.query.param', 'query_id', string='Parameters', copy=True)
    param_signature = fields.Char(string='Parameter definition', compute='_compute_param_signature',
                                  store=True, tracking=True)
    column_model_ids = fields.One2many('sql.query.column.model', 'query_id', string='Column links', copy=True,
                                       help="Open records from a result column: column name -> model. "
                                            "Columns read straight from a table are detected automatically.")
    state = fields.Selection([('draft', 'Draft'), ('valid', 'Validated')], default='draft', required=True,
                             readonly=True, tracking=True, copy=False)
    validated_on = fields.Datetime(readonly=True, copy=False)
    user_id = fields.Many2one('res.users', string='Owner', default=lambda s: s.env.user, required=True,
                              tracking=True, index=True)
    company_id = fields.Many2one('res.company', default=lambda s: s.env.company, index=True,
                                 help="Leave empty to make the query available in every company.")
    group_ids = fields.Many2many('res.groups', 'sql_query_share_group_rel', 'query_id', 'group_id',
                                 string='Shared with groups', tracking=True, copy=False,
                                 help="Members of these groups can run the query (not edit it).")
    user_ids = fields.Many2many('res.users', 'sql_query_share_user_rel', 'query_id', 'user_id',
                                string='Shared with users', copy=False)
    example = fields.Boolean(readonly=True, copy=False)
    can_edit = fields.Boolean(compute='_compute_can_edit')
    # published menu
    menu_parent_id = fields.Many2one('ir.ui.menu', string='Menu under', copy=False,
                                     default=lambda s: s.env.ref('sql_query_workbench.menu_sql_reports_root',
                                                                 raise_if_not_found=False))
    menu_id = fields.Many2one('ir.ui.menu', readonly=True, copy=False)
    client_action_id = fields.Many2one('ir.actions.client', readonly=True, copy=False)
    # digests
    digest_active = fields.Boolean(string='Email digest', copy=False, tracking=True)
    digest_interval = fields.Selection([('daily', 'Daily'), ('weekly', 'Weekly'), ('monthly', 'Monthly')],
                                       default='weekly', string='Every')
    digest_format = fields.Selection([('xlsx', 'Excel (XLSX)'), ('csv', 'CSV')], default='xlsx', string='File')
    digest_user_ids = fields.Many2many('res.users', 'sql_query_digest_user_rel', 'query_id', 'user_id',
                                       string='Send to users')
    digest_partner_ids = fields.Many2many('res.partner', 'sql_query_digest_partner_rel', 'query_id',
                                          'partner_id', string='Send to contacts')
    digest_skip_empty = fields.Boolean(string='Skip empty results', default=True)
    digest_next = fields.Datetime(string='Next digest', copy=False)
    digest_last = fields.Datetime(string='Last digest', readonly=True, copy=False)
    # run log
    run_ids = fields.One2many('sql.query.run', 'query_id', string='Runs')
    run_count = fields.Integer(compute='_compute_run_stats')
    last_run_date = fields.Datetime(compute='_compute_run_stats')
    last_run_status = fields.Char(compute='_compute_run_stats')

    @api.depends('param_ids.name', 'param_ids.ptype', 'param_ids.required', 'param_ids.default_kind',
                 'param_ids.default_value', 'param_ids.model_id', 'param_ids.selection_options')
    def _compute_param_signature(self):
        for q in self:
            parts = []
            for p in q.param_ids.sorted(lambda p: (p.sequence, p.id or 0)):
                bits = [f":{p.name} {p.ptype}"]
                if p.model_id:
                    bits.append(p.model_id.sudo().model)
                if p.required:
                    bits.append('required')
                if p.default_kind and p.default_kind != 'none':
                    bits.append('default ' + (p.default_value or '' if p.default_kind == 'fixed' else p.default_kind))
                parts.append(' '.join(bits))
            q.param_signature = '; '.join(parts) or False

    @api.depends_context('uid')
    def _compute_can_edit(self):
        for q in self:
            q.can_edit = q.has_access('write')

    def _compute_run_stats(self):
        Run = self.env['sql.query.run'].sudo()
        counts = dict(Run._read_group([('query_id', 'in', self.ids)], ['query_id'], ['__count']))
        for q in self:
            q.run_count = counts.get(q, 0) if q.id else 0
            last = Run.search([('query_id', '=', q.id)], order='id desc', limit=1) if q.id else Run
            q.last_run_date = last.create_date
            q.last_run_status = dict(last._fields['status'].selection).get(last.status) if last else False

    # ------------------------------------------------------------------ constraints
    def _is_shared(self):
        self.ensure_one()
        return bool(self.group_ids or self.user_ids or self.menu_id or self.digest_active)

    @api.constrains('state', 'group_ids', 'user_ids', 'digest_active', 'menu_id')
    def _check_shared_valid(self):
        for q in self:
            if q._is_shared() and q.state != 'valid':
                raise ValidationError(self.env._(
                    "Validate the query '%s' before sharing, publishing or scheduling it.", q.name))

    @api.constrains('digest_active', 'digest_user_ids', 'digest_partner_ids')
    def _check_digest(self):
        for q in self:
            if q.digest_active and not (q.digest_user_ids or q.digest_partner_ids):
                raise ValidationError(self.env._("Choose who receives the email digest."))

    # ------------------------------------------------------------------ CRUD
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('digest_active') and not vals.get('digest_next'):
                vals['digest_next'] = fields.Datetime.now()
        return super().create(vals_list)

    def write(self, vals):
        definition = bool({'sql', 'param_ids'} & set(vals))
        if vals.get('digest_active'):
            vals.setdefault('digest_next', fields.Datetime.now())
        res = super().write(vals)
        if definition and not self.env.context.get('sqlw_keep_state'):
            for q in self:
                if q._is_shared():
                    q._validate_sql()
                elif q.state == 'valid':
                    q.with_context(sqlw_keep_state=True).write({'state': 'draft'})
        if {'name', 'group_ids', 'menu_parent_id', 'sequence'} & set(vals):
            self.filtered('menu_id')._sync_menu()
        return res

    def unlink(self):
        menus = self.sudo().mapped('menu_id')
        actions = self.sudo().mapped('client_action_id')
        res = super().unlink()
        menus.unlink()
        actions.unlink()
        return res

    def copy_data(self, default=None):
        vals_list = super().copy_data(default)
        for q, vals in zip(self, vals_list):
            if 'name' not in (default or {}):
                vals['name'] = self.env._("%s (copy)", q.name)
        return vals_list

    # ------------------------------------------------------------------ validation
    def _sync_params_from_sql(self):
        """Declare a text parameter for each new placeholder (keeps existing ones)."""
        for q in self:
            try:
                names = analyse(q.sudo().sql or '')['params']
            except SqlGuardError:
                continue
            existing = set(q.param_ids.mapped('name'))
            new = [n for n in names if n not in existing and n not in BUILTIN_PARAMS]
            if new:
                guess = {'date': 'date', 'day': 'date', 'from': 'date', 'to': 'date', 'since': 'date',
                         'until': 'date', 'limit': 'integer', 'count': 'integer', 'min': 'float', 'max': 'float'}
                q.with_context(sqlw_keep_state=True).write({'param_ids': [fields.Command.create({
                    'name': n,
                    'label': n.replace('_', ' ').capitalize(),
                    'ptype': next((t for k, t in guess.items() if k in n.split('_')), 'char'),
                }) for n in new]})

    def _validate_sql(self):
        """Guard + dry run (EXPLAIN, read-only, rolled back). Raises UserError when invalid."""
        self.ensure_one()
        ws = self.env['sql.workbench']
        sql = self.sudo().sql or ''
        analysis = ws._guard(sql)
        declared = self.sudo().param_ids
        names = set(declared.mapped('name'))
        unknown = [p for p in analysis['params'] if p not in names and p not in BUILTIN_PARAMS]
        if unknown:
            raise UserError(self.env._("Declare these parameters first: %s", ', '.join(':' + u for u in unknown)))
        bound = ws._bind(analysis, declared, {}, sample=True)
        driver = to_driver_sql(sql, analysis)
        if analysis['kind'] != 'explain':
            driver = 'EXPLAIN ' + driver
        limits = ws._limits()
        try:
            engine.run(self.env.cr.dbname, driver, bound, limits['timeout'] * 1000, 1000, shadow=analysis['shadow'])
        except engine.QueryFailed as e:
            ws._log({'query_id': self.id, 'origin': 'validate', 'sql': sql, 'status': e.status, 'error': e.message})
            raise UserError(self.env._("The query does not run:\n%s", e.message)) from None
        ws._log({'query_id': self.id, 'origin': 'validate', 'sql': sql, 'status': 'success',
                 'params_text': ws._params_text(bound)})
        self.with_context(sqlw_keep_state=True).write({'state': 'valid', 'validated_on': fields.Datetime.now()})

    def action_validate(self):
        for q in self:
            q._sync_params_from_sql()
            q._validate_sql()
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'type': 'success', 'message': self.env._("Query validated: it can be shared now."),
                           'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'}}}

    def action_reset_draft(self):
        self.write({'group_ids': [fields.Command.clear()], 'user_ids': [fields.Command.clear()],
                    'digest_active': False})
        self.filtered('menu_id').action_unpublish_menu()
        self.with_context(sqlw_keep_state=True).write({'state': 'draft'})

    def action_detect_params(self):
        self._sync_params_from_sql()

    # ------------------------------------------------------------------ running
    def _check_runnable(self):
        self.ensure_one()
        self.check_access('read')
        if self.state != 'valid' and not self.has_access('write'):
            raise AccessError(self.env._("This query is not validated yet."))

    def get_run_screen(self):
        """Data for the run screen (parameter form). Checks read access through record rules."""
        self._check_runnable()
        ws = self.env['sql.workbench']
        is_user = self.env.user.has_group('sql_query_workbench.group_sqlw_user')
        params = []
        for p in self.sudo().param_ids.sorted(lambda p: (p.sequence, p.id)):
            raw = p._default_raw(self.env.user)
            value = ws._coerce(p.ptype, raw, label=p.name) if raw not in (None, '') else None
            if p.ptype == 'datetime' and value:
                value = engine.jsonable(fields.Datetime.context_timestamp(self, value).replace(tzinfo=None))[:16]
            params.append({
                'name': p.name, 'label': p.label or p.name, 'ptype': p.ptype, 'required': p.required,
                'help': p.help or '', 'model': p.model_id.model or False,
                'options': p._options(),
                'value': engine.jsonable(value) if value not in (None, []) else (False if p.ptype == 'boolean' else
                                                                                  ([] if p.ptype == 'many2many' else '')),
            })
        return {
            'id': self.id, 'name': self.name, 'description': self.description or '',
            'tags': self.tag_ids.mapped('name'), 'params': params, 'state': self.state,
            'can_edit': self.has_access('write'), 'sql': self.sudo().sql if is_user else False,
            'limits': ws._limits(),
        }

    def run_query(self, values=None, mode='run'):
        self._check_runnable()
        if mode != 'run':
            self.env['sql.workbench']._require('user')
        return self.env['sql.workbench']._execute(
            self.sudo().sql, values, query=self, mode=mode,
            origin='explain' if mode != 'run' else ('menu' if self.env.context.get('sqlw_from_menu') else 'saved'))

    def action_open_run_screen(self):
        self.ensure_one()
        return {'type': 'ir.actions.client', 'tag': 'sql_query_workbench.run', 'name': self.name,
                'params': {'query_id': self.id}}

    def action_open_in_console(self):
        self.ensure_one()
        return {'type': 'ir.actions.client', 'tag': 'sql_query_workbench.console',
                'name': self.env._("SQL Workbench"), 'params': {'query_id': self.id}}

    def action_view_runs(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('sql_query_workbench.action_sql_query_run')
        action['domain'] = [('query_id', '=', self.id)]
        action['context'] = {'search_default_query_id': self.id}
        return action

    def action_duplicate_draft(self):
        """Copy a query the user can read into a private draft they own."""
        self.ensure_one()
        self.env['sql.workbench']._require('user')
        self.check_access('read')
        new = self.sudo().copy({
            'name': self.env._("%s (my draft)", self.name), 'user_id': self.env.uid,
            'company_id': self.env.company.id if self.company_id else False, 'example': False,
        })
        new = new.with_user(self.env.user)
        new.check_access('write')
        return {'type': 'ir.actions.act_window', 'res_model': 'sql.query', 'res_id': new.id,
                'view_mode': 'form', 'target': 'current'}

    # ------------------------------------------------------------------ menus
    def action_publish_menu(self):
        for q in self:
            if q.state != 'valid':
                raise UserError(self.env._("Validate the query before publishing it."))
            if not q.group_ids and not q.user_ids:
                raise UserError(self.env._("Share the query with at least one group first: the menu is "
                                           "shown to those groups."))
            if not q.group_ids:
                raise UserError(self.env._("Menus are shown per group: add a group in Sharing."))
            action = self.env['ir.actions.client'].sudo().create({
                'name': q.name, 'tag': 'sql_query_workbench.run', 'params': {'query_id': q.id},
            })
            menu = self.env['ir.ui.menu'].sudo().create({
                'name': q.name, 'parent_id': (q.menu_parent_id or self.env.ref('sql_query_workbench.menu_sql_reports_root')).id,
                'action': f'ir.actions.client,{action.id}', 'sequence': q.sequence,
                'group_ids': [fields.Command.set((q.group_ids | self.env.ref('sql_query_workbench.group_sqlw_manager')).ids)],
            })
            q.write({'menu_id': menu.id, 'client_action_id': action.id})
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_unpublish_menu(self):
        for q in self.sudo():
            menu, action = q.menu_id, q.client_action_id
            q.write({'menu_id': False, 'client_action_id': False})
            menu.unlink()
            action.unlink()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def _sync_menu(self):
        manager = self.env.ref('sql_query_workbench.group_sqlw_manager')
        for q in self.sudo():
            q.menu_id.write({
                'name': q.name, 'sequence': q.sequence,
                'parent_id': (q.menu_parent_id or self.env.ref('sql_query_workbench.menu_sql_reports_root')).id,
                'group_ids': [fields.Command.set((q.group_ids | manager).ids)],
            })
            q.client_action_id.name = q.name

    # ------------------------------------------------------------------ digests
    def _digest_recipients(self):
        return self.digest_user_ids.mapped('partner_id') | self.digest_partner_ids

    def _send_digest(self):
        """Run as the owner with default parameter values and email the file."""
        self.ensure_one()
        owner = self.user_id
        ws = self.env['sql.workbench'].with_user(owner).with_company(self.company_id or owner.company_id)
        fmt = self.digest_format or 'xlsx'
        try:
            content, filename, mimetype = ws.with_context(sqlw_origin='digest').export_file(
                {'query_id': self.id, 'format': fmt, 'options': {'bom': True}})
        except (UserError, AccessError) as e:
            self.message_post(body=self.env._("Email digest not sent: %s", e.args[0]))
            return False
        run = self.env['sql.query.run'].sudo().search([('query_id', '=', self.id)], order='id desc', limit=1)
        if (self.digest_skip_empty and not self.env.context.get('sqlw_force_send')
                and run and not run.row_count):
            return False
        attachment = self.env['ir.attachment'].sudo().create({
            'name': filename, 'raw': content, 'mimetype': mimetype.split(';')[0],
            'res_model': self._name, 'res_id': self.id,
        })
        partners = self._digest_recipients()
        body = self.env['ir.qweb']._render('sql_query_workbench.digest_mail_body', {
            'query': self, 'rows': run.row_count if run else 0, 'truncated': run.truncated if run else False,
        })
        mail = self.env['mail.mail'].sudo().create({
            'subject': self.env._("%(name)s - %(date)s", name=self.name, date=fields.Date.today()),
            'body_html': body,
            'email_from': (self.company_id or owner.company_id).email_formatted or owner.email_formatted,
            'recipient_ids': [fields.Command.set(partners.ids)],
            'attachment_ids': [fields.Command.set(attachment.ids)],
            'model': self._name, 'res_id': self.id,
            'auto_delete': True,
        })
        return mail

    @api.model
    def _next_digest_date(self, interval, start):
        return start + {'daily': relativedelta(days=1), 'weekly': relativedelta(weeks=1),
                        'monthly': relativedelta(months=1)}[interval or 'weekly']

    @api.model
    def _cron_send_digests(self):
        now = fields.Datetime.now()
        due = self.sudo().search([('digest_active', '=', True), ('state', '=', 'valid'),
                                  '|', ('digest_next', '=', False), ('digest_next', '<=', now)])
        for q in due:
            q._send_digest()
            base = q.digest_next or now
            nxt = q._next_digest_date(q.digest_interval, base)
            while nxt <= now:
                nxt = q._next_digest_date(q.digest_interval, nxt)
            q.with_context(sqlw_keep_state=True).write({'digest_last': now, 'digest_next': nxt})

    def action_send_digest_now(self):
        for q in self:
            q.check_access('write')
            if not q.digest_user_ids and not q.digest_partner_ids:
                raise UserError(self.env._("Choose who receives the email digest."))
            q.with_context(sqlw_force_send=True)._send_digest()
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'type': 'success', 'message': self.env._("Digest queued for sending.")}}

    # ------------------------------------------------------------------ library
    def _library_entry(self):
        self.ensure_one()
        self.check_access('read')
        self = self.sudo()
        groups = []
        for g in self.group_ids:
            xmlid = g.get_external_id().get(g.id)
            if xmlid:
                groups.append(xmlid)
        return {
            'name': self.name, 'description': self.description or '', 'sql': self.sudo().sql or '',
            'tags': self.tag_ids.mapped('name'),
            'groups': groups,
            'parameters': [{
                'name': p.name, 'label': p.label, 'type': p.ptype, 'required': p.required,
                'default': p.default_kind, 'default_value': p.default_value or '',
                'model': p.model_id.model or '', 'options': p.selection_options or '', 'help': p.help or '',
                'sequence': p.sequence,
            } for p in self.param_ids],
            'column_links': [{'column': c.column_name, 'model': c.model_id.model} for c in self.column_model_ids],
        }

    @api.model
    def _library_import(self, data):
        """Create draft queries from a library dict. Returns the created records."""
        if not isinstance(data, dict) or not isinstance(data.get('queries'), list):
            raise UserError(self.env._("This is not a SQL Workbench library file."))
        Tag, Model = self.env['sql.query.tag'], self.env['ir.model'].sudo()
        created = self.browse()
        for entry in data['queries']:
            if not isinstance(entry, dict) or not entry.get('name') or not entry.get('sql'):
                raise UserError(self.env._("Each query needs a name and SQL."))
            tags = Tag.browse()
            for t in entry.get('tags') or []:
                tags |= Tag.search([('name', '=', t)], limit=1) or Tag.create({'name': t})
            params = []
            for p in entry.get('parameters') or []:
                model = Model.search([('model', '=', p.get('model'))], limit=1) if p.get('model') else Model
                params.append(fields.Command.create({
                    'name': p.get('name'), 'label': p.get('label') or p.get('name'),
                    'ptype': p.get('type') or 'char', 'required': bool(p.get('required')),
                    'default_kind': p.get('default') or 'none', 'default_value': p.get('default_value') or False,
                    'model_id': model.id or False, 'selection_options': p.get('options') or False,
                    'help': p.get('help') or False, 'sequence': p.get('sequence') or 10,
                }))
            links = []
            for c in entry.get('column_links') or []:
                model = Model.search([('model', '=', c.get('model'))], limit=1)
                if model and c.get('column'):
                    links.append(fields.Command.create({'column_name': c['column'], 'model_id': model.id}))
            q = self.create({
                'name': entry['name'], 'description': entry.get('description') or False, 'sql': entry['sql'],
                'tag_ids': [fields.Command.set(tags.ids)], 'param_ids': params, 'column_model_ids': links,
            })
            groups = self.env['res.groups']
            for xmlid in entry.get('groups') or []:
                groups |= self.env.ref(xmlid, raise_if_not_found=False) or groups
            if groups:
                try:
                    q._validate_sql()
                    q.group_ids = [fields.Command.set(groups.ids)]
                except UserError:
                    pass  # stays a private draft; the user fixes and validates it
            created |= q
        return created


class SqlQueryParam(models.Model):
    _name = 'sql.query.param'
    _description = 'SQL query parameter'
    _order = 'sequence, id'

    query_id = fields.Many2one('sql.query', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Placeholder', required=True, help="Used in the SQL as :name")
    label = fields.Char(help="Shown on the parameter form.")
    help = fields.Char(string='Hint')
    ptype = fields.Selection(PARAM_TYPES, string='Type', required=True, default='char')
    required = fields.Boolean()
    default_kind = fields.Selection(DEFAULT_KINDS, string='Default', default='none', required=True)
    default_value = fields.Char(string='Fixed default',
                                help="Date as YYYY-MM-DD, numbers as 12.5, records as an ID "
                                     "(record lists: 3,7,9), booleans as true/false.")
    model_id = fields.Many2one('ir.model', string='Model', ondelete='cascade',
                               help="Model of the record picker for Record and Record list parameters.")
    selection_options = fields.Text(string='Options', help="One option per line, as value or value:Label.")

    _name_uniq = models.Constraint('UNIQUE (query_id, name)', 'Each placeholder can be declared once per query.')

    @api.constrains('name', 'ptype', 'model_id', 'selection_options')
    def _check_definition(self):
        for p in self:
            if not NAME_RE.match(p.name or ''):
                raise ValidationError(self.env._("'%s' is not a valid placeholder name (letters, digits, _).", p.name))
            if p.name in BUILTIN_PARAMS:
                raise ValidationError(self.env._(":%s is a built-in value and cannot be redeclared.", p.name))
            if p.ptype in ('many2one', 'many2many') and not p.model_id:
                raise ValidationError(self.env._("Choose the model of the record parameter :%s.", p.name))
            if p.ptype == 'selection' and not p._options():
                raise ValidationError(self.env._("Add at least one option to the selection parameter :%s.", p.name))

    def _options(self):
        self.ensure_one()
        out = []
        for line in (self.selection_options or '').splitlines():
            line = line.strip()
            if line:
                value, _sep, label = line.partition(':')
                out.append([value.strip(), (label or value).strip()])
        return out

    def _default_raw(self, user=None):
        self.ensure_one()
        if self.default_kind == 'fixed':
            return self.default_value
        if self.default_kind in (None, False, 'none'):
            return None
        return self.env['sql.workbench']._dynamic_default(self.default_kind, user)

    def _sample_value(self):
        today = fields.Date.today()
        return {
            'date': today, 'datetime': datetime.datetime.combine(today, datetime.time()),
            'integer': 0, 'float': 0.0, 'char': '', 'boolean': False, 'many2one': 0, 'many2many': [],
            'selection': (self._options() or [['']])[0][0],
        }.get(self.ptype)


class SqlQueryColumnModel(models.Model):
    _name = 'sql.query.column.model'
    _description = 'SQL query column link'

    query_id = fields.Many2one('sql.query', required=True, ondelete='cascade', index=True)
    column_name = fields.Char(string='Column', required=True, help="Result column name, as shown in the grid header.")
    model_id = fields.Many2one('ir.model', required=True, ondelete='cascade', string='Opens')

    _column_uniq = models.Constraint('UNIQUE (query_id, column_name)', 'Each column can be linked once.')
