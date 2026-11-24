# -*- coding: utf-8 -*-
"""Settings of the bank fees allocation.

The settings are exposed in the *Configuration > Settings* menu of the
application.  They are **company dependent**: the values are stored on
``res.company`` and are read through ``related`` fields, exactly like the
core Accounting settings do.

The domains of the account fields are plain **lists of tuples** with
literal values only, and the views filter the drop-downs on computed
``allowed_*`` fields with ``[('id', 'in', allowed_*)]``.  A dynamic domain
written in the field definition would reach the web client as a Python
expression and be flattened into a list, which is what the
``InvalidDomainError`` of the client is about.
"""

from odoo import api, fields, models

ALLOCATION_ACCOUNT_TYPES = (
    'asset_current', 'asset_cash', 'asset_receivable',
    'liability_current', 'liability_payable',
)
EXPENSE_ACCOUNT_TYPES = ('expense', 'expense_other')


class ResConfigSettings(models.TransientModel):
    """ Bank Fees Allocation settings. """

    _inherit = 'res.config.settings'

    bank_fees_allocation_account_ids = fields.Many2many(
        comodel_name='account.account',
        related='company_id.bank_fees_allocation_account_ids',
        readonly=False,
        string='Allocation Accounts',
        domain=[('account_type', 'in', ALLOCATION_ACCOUNT_TYPES)],
        help="Accounts the accountant works on: the Visa/card clearing "
             "accounts. Only the journal items of these accounts show up in "
             "the Bank Fees Allocation view.",
    )

    bank_fees_expense_account_id = fields.Many2one(
        comodel_name='account.account',
        related='company_id.bank_fees_expense_account_id',
        readonly=False,
        string='Bank Fees Expense Account',
        domain=[('account_type', 'in', EXPENSE_ACCOUNT_TYPES)],
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

    # ------------------------------------------------------------------
    # Records the user may pick
    #
    # They are computed (not stored) and listed in the view as invisible
    # fields: the drop-downs then filter on them with a plain list of
    # tuples, and the client receives a list of ids instead of a Python
    # expression.
    # ------------------------------------------------------------------
    allowed_allocation_account_ids = fields.Many2many(
        comodel_name='account.account',
        string='Allowed Allocation Accounts',
        compute='_compute_allowed_records',
    )

    allowed_expense_account_ids = fields.Many2many(
        comodel_name='account.account',
        string='Allowed Expense Accounts',
        compute='_compute_allowed_records',
    )

    allowed_bank_account_ids = fields.Many2many(
        comodel_name='account.account',
        string='Allowed Bank Accounts',
        compute='_compute_allowed_records',
    )

    allowed_journal_ids = fields.Many2many(
        comodel_name='account.journal',
        string='Allowed Journals',
        compute='_compute_allowed_records',
    )

    @api.depends('company_id',
                 'bank_fees_allocation_account_ids',
                 'bank_fees_expense_account_id',
                 'bank_fees_bank_account_ids',
                 'bank_fees_allocation_journal_id')
    def _compute_allowed_records(self):
        """ The records of the company, plus the ones already selected. """
        for settings in self:
            company = settings.company_id or self.env.company
            Account = self.env['account.account']
            Journal = self.env['account.journal']

            settings.allowed_allocation_account_ids = Account.search([
                ('company_ids', 'in', company.ids),
                ('account_type', 'in', ALLOCATION_ACCOUNT_TYPES),
            ]) | settings.bank_fees_allocation_account_ids

            settings.allowed_expense_account_ids = Account.search([
                ('company_ids', 'in', company.ids),
                ('account_type', 'in', EXPENSE_ACCOUNT_TYPES),
            ]) | settings.bank_fees_expense_account_id

            settings.allowed_bank_account_ids = Account.search([
                ('company_ids', 'in', company.ids),
                ('account_type', '=', 'asset_cash'),
            ]) | settings.bank_fees_bank_account_ids

            settings.allowed_journal_ids = Journal.search([
                ('company_id', '=', company.id),
                ('type', '=', 'general'),
            ]) | settings.bank_fees_allocation_journal_id
