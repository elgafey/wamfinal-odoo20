# Part of SQL Query Workbench. Copyright Viyug Infotech. License LGPL-3.
import base64
import json

from odoo import fields, models
from odoo.exceptions import UserError

LIBRARY_FORMAT = 'sql_query_workbench.library'


class SqlQueryLibrary(models.TransientModel):
    _name = 'sql.query.library'
    _description = 'Import or export saved SQL queries'

    mode = fields.Selection([('export', 'Export'), ('import', 'Import')], default='export', required=True)
    query_ids = fields.Many2many('sql.query', string='Queries')
    file = fields.Binary(string='Library file')
    filename = fields.Char()
    created_count = fields.Integer(readonly=True)

    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get('active_model') == 'sql.query' and self.env.context.get('active_ids'):
            res['query_ids'] = [fields.Command.set(self.env.context['active_ids'])]
        return res

    def _reopen(self):
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'new'}

    def action_export(self):
        self.ensure_one()
        self.env['sql.workbench']._require('user')
        queries = self.query_ids or self.env['sql.query'].search([])
        data = {'format': LIBRARY_FORMAT, 'version': 1, 'exported_on': fields.Datetime.to_string(fields.Datetime.now()),
                'queries': [q._library_entry() for q in queries]}
        self.write({'file': base64.b64encode(json.dumps(data, indent=2, ensure_ascii=False).encode()).decode(),
                    'filename': 'sql_queries.json'})
        return self._reopen()

    def action_import(self):
        self.ensure_one()
        self.env['sql.workbench']._require('user')
        if not self.file:
            raise UserError(self.env._("Choose a library file to import."))
        try:
            data = json.loads(self.file.content)
        except ValueError:
            raise UserError(self.env._("The file is not valid JSON.")) from None
        if not isinstance(data, dict) or data.get('format') != LIBRARY_FORMAT:
            raise UserError(self.env._("This is not a SQL Workbench library file."))
        created = self.env['sql.query']._library_import(data)
        return {'type': 'ir.actions.act_window', 'res_model': 'sql.query', 'name': self.env._("Imported queries"),
                'view_mode': 'list,form', 'domain': [('id', 'in', created.ids)], 'target': 'current'}
