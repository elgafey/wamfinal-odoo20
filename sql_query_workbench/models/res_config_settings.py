# Part of SQL Query Workbench. Copyright Viyug Infotech. License LGPL-3.
from odoo import api, fields, models

from .sql_workbench import DEFAULTS, PREFIX


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    sqlw_row_limit = fields.Integer(string='Row cap', config_parameter=PREFIX + 'row_limit',
                                    default=DEFAULTS['row_limit'])
    sqlw_timeout = fields.Integer(string='Statement timeout (s)', config_parameter=PREFIX + 'timeout',
                                  default=DEFAULTS['timeout'])
    sqlw_export_limit = fields.Integer(string='Max export rows', config_parameter=PREFIX + 'export_limit',
                                      default=DEFAULTS['export_limit'])
    sqlw_retention_days = fields.Integer(string='Keep run log (days)', config_parameter=PREFIX + 'retention_days',
                                         default=DEFAULTS['retention_days'])
    sqlw_seq_scan_rows = fields.Integer(string='Flag sequential scans from (rows)',
                                        config_parameter=PREFIX + 'seq_scan_rows', default=DEFAULTS['seq_scan_rows'])
    sqlw_denied_tables = fields.Char(string='Blocked tables', config_parameter=PREFIX + 'denied_tables',
                                     default=DEFAULTS['denied_tables'])
    sqlw_denied_columns = fields.Char(string='Blocked columns', config_parameter=PREFIX + 'denied_columns',
                                      default=DEFAULTS['denied_columns'])
    sqlw_mask_patterns = fields.Char(string='Masked column names', config_parameter=PREFIX + 'mask_patterns',
                                     default=DEFAULTS['mask_patterns'])
    sqlw_mask_enabled = fields.Boolean(string='Mask credential-like columns', default=True)

    @api.model
    def get_values(self):
        res = super().get_values()
        res['sqlw_mask_enabled'] = self.env['sql.workbench']._settings()['mask_enabled']
        return res

    def set_values(self):
        super().set_values()
        if self.env.user.has_group('base.group_system'):
            self.env['ir.config_parameter'].sudo().set_str(PREFIX + 'mask_enabled',
                                                             '1' if self.sqlw_mask_enabled else '0')

    def action_sqlw_group_limits(self):
        return self.env['ir.actions.act_window']._for_xml_id('sql_query_workbench.action_sql_query_limit')
