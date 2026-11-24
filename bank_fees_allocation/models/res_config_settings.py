# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    bank_fees_account_id = fields.Many2one(
        related='company_id.bank_fees_account_id', readonly=False,
        string='Default Bank Fees Account',
        domain="[('account_type', 'in', ['expense', 'expense_other', "
               "'expense_depreciation', 'expense_direct_cost']), "
               "('company_ids', 'parent_of', company_id)]",
    )
