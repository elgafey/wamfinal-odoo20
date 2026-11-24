# -*- coding: utf-8 -*-
from odoo import fields, models

from .account_move_line import EXPENSE_ACCOUNT_TYPES


class ResCompany(models.Model):
    _inherit = 'res.company'

    bank_fees_account_id = fields.Many2one(
        'account.account',
        string='Default Bank Fees Account',
        check_company=True,
        domain=[('account_type', 'in', list(EXPENSE_ACCOUNT_TYPES))],
        help="Pre-fills the Bank Fees Account on the Closing Fees wizard, "
             "so nobody has to pick the same expense account every time. "
             "It stays editable on the wizard for the exceptional entries. "
             "Uninstalling this module removes the setting cleanly; the "
             "journal entries already created keep their accounts.")
