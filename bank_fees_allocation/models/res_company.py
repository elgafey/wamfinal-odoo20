# -*- coding: utf-8 -*-
"""Per-company configuration of the bank fees allocation.

The configuration lives on ``res.company`` so that it is naturally
multi-company, and it is exposed through the settings page of the
application where only the *Bank Fees Allocation / Administrator* group
may change it.

The domains of the account fields are plain **lists of tuples** with
literal values only: they are evaluated by the server and never reach the
web client as a Python expression.  The company restriction is enforced by
``check_company`` and, in the views, by the computed ``allowed_*`` fields.
"""

from odoo import api, fields, models


class ResCompany(models.Model):
    """ Company level configuration of the bank fees allocation. """

    _inherit = 'res.company'

    # ------------------------------------------------------------------
    # Accounts
    # ------------------------------------------------------------------
    bank_fees_allocation_account_ids = fields.Many2many(
        comodel_name='account.account',
        relation='company_bank_fees_allocation_account_rel',
        column1='company_id',
        column2='account_id',
        string='Allocation Accounts',
        check_company=True,
        domain=[('account_type', 'in', ('asset_current', 'asset_cash', 'asset_receivable',
                                       'liability_current', 'liability_payable'))],
        help="Accounts the accountant works on: the Visa/card clearing accounts "
             "the aggregated bank settlements are booked against. Only the "
             "journal items of these accounts show up in the Bank Fees "
             "Allocation view. A branch may configure several accounts.",
    )

    bank_fees_expense_account_id = fields.Many2one(
        comodel_name='account.account',
        string='Bank Fees Expense Account',
        check_company=True,
        domain=[('account_type', 'in', ('expense', 'expense_other'))],
        help="Account where the bank fees are booked. It must be configured, "
             "otherwise the allocation cannot be confirmed.",
    )

    bank_fees_bank_account_ids = fields.Many2many(
        comodel_name='account.account',
        relation='company_bank_fees_bank_account_rel',
        column1='company_id',
        column2='account_id',
        string='Bank Accounts',
        check_company=True,
        domain=[('account_type', '=', 'asset_cash')],
        help="Bank accounts offered in the allocation wizard. The amount "
             "credited by the bank is booked on the account picked here.",
    )

    bank_fees_allocation_journal_id = fields.Many2one(
        comodel_name='account.journal',
        string='Allocation Journal',
        check_company=True,
        domain=[('type', '=', 'general')],
        default=lambda self: self._default_bank_fees_allocation_journal(),
        help="Journal used by the generated allocation entries. Defaults to "
             "the Miscellaneous journal of the company.",
    )

    @api.model
    def _default_bank_fees_allocation_journal(self):
        """ The first Miscellaneous journal of the company. """
        return self.env['account.journal'].search([
            ('company_id', '=', self.id),
            ('type', '=', 'general'),
        ], limit=1)
