# -*- coding: utf-8 -*-
"""Accounting settings page: the Bank Fees Allocation configuration.

The settings are exposed in the *Accounting* application block of the
standard Accounting settings page.  They are **company dependent**: the
values are stored on ``res.company`` and are read through ``related``
fields, exactly like the core Accounting settings do.
"""

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    """ Accounting settings: Bank Fees Allocation block. """

    _inherit = 'res.config.settings'

    bank_fees_allocation_account_ids = fields.Many2many(
        comodel_name='account.account',
        related='company_id.bank_fees_allocation_account_ids',
        readonly=False,
        string='Allocation Accounts',
        domain=[('account_type', 'in', ('asset_current', 'asset_cash', 'asset_receivable',
                                       'liability_current', 'liability_payable'))],
        help="Accounts the accountant works on: the Visa/card clearing "
             "accounts. Only the journal items of these accounts show up in "
             "the Bank Fees Allocation view.",
    )

    bank_fees_expense_account_id = fields.Many2one(
        comodel_name='account.account',
        related='company_id.bank_fees_expense_account_id',
        readonly=False,
        string='Bank Fees Expense Account',
        domain=[('account_type', 'in', ('expense', 'expense_other'))],
        help="Account where the bank fees are booked.",
    )

    bank_fees_bank_account_ids = fields.Many2many(
        comodel_name='account.account',
        related='company_id.bank_fees_bank_account_ids',
        readonly=False,
        string='Bank Accounts',
        domain=[('account_type', '=', 'asset_cash')],
        help="Bank accounts offered in the allocation wizard.",
    )

    bank_fees_allocation_journal_id = fields.Many2one(
        comodel_name='account.journal',
        related='company_id.bank_fees_allocation_journal_id',
        readonly=False,
        string='Allocation Journal',
        domain=[('type', '=', 'general')],
        help="Journal used by the generated allocation entries.",
    )
