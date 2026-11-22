# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    branch_analytic_auto = fields.Boolean(
        related='company_id.branch_analytic_auto', readonly=False,
    )
    branch_warehouse_exclusive = fields.Boolean(
        related='company_id.branch_warehouse_exclusive', readonly=False,
    )
