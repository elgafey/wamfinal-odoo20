# Part of SQL Query Workbench. Copyright Viyug Infotech. License LGPL-3.
import json

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

ORIGINS = [
    ('console', 'Console'),
    ('saved', 'Saved query'),
    ('menu', 'Published menu'),
    ('explain', 'Explain'),
    ('export', 'Export'),
    ('print', 'PDF'),
    ('digest', 'Email digest'),
    ('validate', 'Validation'),
]
STATUSES = [('success', 'Success'), ('error', 'Error'), ('timeout', 'Timeout'), ('blocked', 'Blocked')]


class SqlQueryRun(models.Model):
    _name = 'sql.query.run'
    _description = 'SQL query run'
    _order = 'id desc'
    _rec_name = 'display_label'

    query_id = fields.Many2one('sql.query', string='Query', index='btree_not_null', ondelete='set null',
                               readonly=True)
    user_id = fields.Many2one('res.users', string='User', required=True, index=True, readonly=True)
    company_id = fields.Many2one('res.company', required=True, index=True, readonly=True)
    origin = fields.Selection(ORIGINS, required=True, default='console', readonly=True)
    status = fields.Selection(STATUSES, required=True, readonly=True, index=True)
    duration_ms = fields.Integer(string='Duration (ms)', readonly=True, aggregator='avg')
    max_duration_ms = fields.Integer(compute='_compute_failed', store=True, string='Slowest (ms)', aggregator='max')
    row_count = fields.Integer(string='Rows', readonly=True, aggregator='sum')
    truncated = fields.Boolean(string='Row cap hit', readonly=True)
    error = fields.Text(readonly=True)
    params_text = fields.Text(string='Parameters', readonly=True)
    sql = fields.Text(string='SQL', readonly=True)
    failed = fields.Integer(compute='_compute_failed', store=True, string='Failures', aggregator='sum')
    source_label = fields.Char(string='Query name', readonly=True, help="Query name at run time.")
    display_label = fields.Char(compute='_compute_display_label')

    _date_idx = models.Index('(create_date DESC)')

    @api.depends('status', 'duration_ms')
    def _compute_failed(self):
        for r in self:
            r.failed = 1 if r.status != 'success' else 0
            r.max_duration_ms = r.duration_ms

    @api.depends('query_id', 'create_date')
    def _compute_display_label(self):
        for r in self:
            r.display_label = f"{r.query_id.name or self.env._('Console')} - {r.create_date or ''}"

    def action_open_in_console(self):
        self.ensure_one()
        return {'type': 'ir.actions.client', 'tag': 'sql_query_workbench.console',
                'name': self.env._("SQL Workbench"), 'params': {'run_id': self.id}}

    def console_sql(self):
        """SQL of a run for the editor (the user's own history, or any run for managers)."""
        self.ensure_one()
        self.env['sql.workbench']._require('user')
        self.check_access('read')
        return self.sql or ''

    @api.model
    def _cron_purge(self):
        days = self.env['sql.workbench']._settings()['retention_days']
        if days > 0:
            limit = fields.Datetime.now() - relativedelta(days=days)
            self.sudo().search([('create_date', '<', limit)]).unlink()


class SqlQueryLimit(models.Model):
    _name = 'sql.query.limit'
    _description = 'SQL Workbench limits per group'
    _order = 'group_id'

    group_id = fields.Many2one('res.groups', required=True, ondelete='cascade')
    row_limit = fields.Integer(string='Row cap', help="0 = use the global setting.")
    timeout = fields.Integer(string='Statement timeout (s)', help="0 = use the global setting.")
    export_limit = fields.Integer(string='Max export rows', help="0 = use the global setting.")

    _group_uniq = models.Constraint('UNIQUE (group_id)', 'One limit line per group.')
    _positive = models.Constraint('CHECK (row_limit >= 0 AND timeout >= 0 AND export_limit >= 0)',
                                  'Limits cannot be negative.')


class SqlQueryPrint(models.TransientModel):
    _name = 'sql.query.print'
    _description = 'SQL result to print'

    name = fields.Char()
    orientation = fields.Selection([('portrait', 'Portrait'), ('landscape', 'Landscape')], default='portrait')
    columns_json = fields.Text()
    rows_json = fields.Text()
    row_count = fields.Integer()
    truncated = fields.Boolean()
    params_text = fields.Text()

    def _columns(self):
        return json.loads(self.columns_json or '[]')

    def _rows(self):
        return json.loads(self.rows_json or '[]')

    def _params(self):
        try:
            return {k: v for k, v in json.loads(self.params_text or '{}').items()
                    if k not in ('user_id', 'company_id', 'today')}
        except ValueError:
            return {}
