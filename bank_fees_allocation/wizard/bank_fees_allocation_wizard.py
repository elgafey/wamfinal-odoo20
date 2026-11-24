# -*- coding: utf-8 -*-
"""The *Bank Fees Allocation* wizard.

The accountant selects the original sales journal items (100.00), types the
amount the bank actually deposited (95.00) and the wizard computes the fee
(5.00).  On confirmation the journal entries are created, posted and
reconciled with every selected item.  One entry is generated **per branch**
(the branch of a journal item is stored on its move, so the generated lines
can only carry it through one move per branch)::

    Debit  Bank Account                  95.00   <- net amount of the branch
    Debit  Bank Fees Expense Account      5.00   <- fee of the branch
    Credit Visa/Card clearing account   100.00   <- one line per source account

Everything goes through the regular ORM: ``account.move`` is created and
posted with ``action_post()`` and the reconciliation uses Odoo's own
``account.move.line.reconcile()``.
"""

from odoo import Command, _, api, fields, models
from odoo.exceptions import ValidationError


class BankFeesAllocationWizard(models.TransientModel):
    """ Bank Fees Allocation wizard.

    The wizard receives **one or several** journal items taken from the
    *Bank Fees Allocation* view, lets the user split the total between the
    **net amount** (what the bank credited) and the **fee** (what the bank
    kept), then creates one entry per branch, posts it and reconciles it.

    The two amounts are kept consistent both ways:

    * editing the *Net Amount* recomputes the *Fee Amount*;
    * editing the *Fee Amount* recomputes the *Net Amount*.

    The consistency is implemented with a ``compute`` + ``inverse`` pair on
    both fields (and the matching ``@api.onchange`` methods, because the web
    client does not run the inverses while computing an onchange).
    """

    _name = 'bank.fees.allocation.wizard'
    _description = 'Bank Fees Allocation'
    _check_company_auto = True

    # ------------------------------------------------------------------
    # Source journal items
    # ------------------------------------------------------------------
    line_ids = fields.Many2many(
        comodel_name='account.move.line',
        relation='bank_fees_allocation_wizard_line_rel',
        column1='wizard_id',
        column2='line_id',
        string='Journal Items',
        readonly=True,
        help='Journal items selected in the Bank Fees Allocation view.',
    )

    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        compute='_compute_company_id',
        store=True,
        readonly=True,
        index=True,
    )

    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )

    # ------------------------------------------------------------------
    # Accounts the user may pick
    #
    # The domains of the account fields are **not** written in the field
    # definition: a dynamic domain would reach the web client as a
    # Python expression, and the client would evaluate it into a flat
    # list instead of a list of tuples ("Invalid domain representation").
    # The allowed accounts are therefore computed here, and the view
    # filters on them with a plain list of tuples.
    # ------------------------------------------------------------------
    allowed_bank_account_ids = fields.Many2many(
        comodel_name='account.account',
        string='Allowed Bank Accounts',
        compute='_compute_allowed_accounts',
        help='Bank accounts the user may pick, for the drop-down of the '
             'bank account.',
    )

    allowed_fee_account_ids = fields.Many2many(
        comodel_name='account.account',
        string='Allowed Fee Accounts',
        compute='_compute_allowed_accounts',
        help='Expense accounts the user may pick, for the drop-down of the '
             'fee account.',
    )

    allowed_journal_ids = fields.Many2many(
        comodel_name='account.journal',
        string='Allowed Journals',
        compute='_compute_allowed_accounts',
        help='Journals the user may pick, for the drop-down of the journal.',
    )

    # ------------------------------------------------------------------
    # Amounts
    # ------------------------------------------------------------------
    total_amount = fields.Monetary(
        string='Total Amount',
        currency_field='currency_id',
        compute='_compute_total_amount',
        store=True,
        readonly=True,
        help='Sum of the balances of the selected journal items.',
    )

    net_amount = fields.Monetary(
        string='Net Amount',
        currency_field='currency_id',
        compute='_compute_net_amount',
        inverse='_inverse_net_amount',
        store=True,
        readonly=False,
        help='Amount actually credited by the bank. Editing it recomputes '
             'the fee amount.',
    )

    fee_amount = fields.Monetary(
        string='Fee Amount',
        currency_field='currency_id',
        compute='_compute_fee_amount',
        inverse='_inverse_fee_amount',
        store=True,
        readonly=False,
        help='Bank fees kept by the bank. Editing it recomputes the net amount.',
    )

    # ------------------------------------------------------------------
    # Entry configuration
    # ------------------------------------------------------------------
    bank_account_id = fields.Many2one(
        comodel_name='account.account',
        string='Bank Account',
        check_company=True,
        help='Bank account the aggregated settlement is credited to. Only '
             'the bank accounts configured in the settings are proposed.',
    )

    fee_account_id = fields.Many2one(
        comodel_name='account.account',
        string='Fee Account',
        check_company=True,
        help='Account where the bank fees are booked. Only the expense '
             'accounts of the company are proposed. Pre-filled from the '
             'company settings.',
    )

    journal_id = fields.Many2one(
        comodel_name='account.journal',
        string='Journal',
        check_company=True,
        default=lambda self: self._default_journal_id(),
    )

    date = fields.Date(
        string='Date',
        default=fields.Date.context_today,
    )

    ref = fields.Char(
        string='Reference',
        help='Reference written on the generated journal entry.',
    )

    move_id = fields.Many2one(
        comodel_name='account.move',
        string='Journal Entry',
        readonly=True,
        help='First journal entry generated by the allocation (the entries '
             'are split per branch).',
    )

    move_ids = fields.Many2many(
        comodel_name='account.move',
        relation='bank_fees_allocation_wizard_move_rel',
        column1='wizard_id',
        column2='move_id',
        string='Journal Entries',
        readonly=True,
        help='Every journal entry generated by the allocation: one per '
             'branch of the selection.',
    )

    branch_ids = fields.Many2many(
        comodel_name='branch.branch',
        string='Branches',
        compute='_compute_branch_ids',
        help='Branches of the selected journal items.',
    )

    # ------------------------------------------------------------------
    # Defaults
    # ------------------------------------------------------------------
    @api.model
    def _lines_from_context(self):
        """ The journal items put in the context by the list header button.

        The context may carry the ids as a plain list or as ORM commands;
        both are handled.
        """
        line_ids = []
        for cmd in self.env.context.get('default_line_ids') or []:
            if isinstance(cmd, (list, tuple)) and len(cmd) >= 3:
                line_ids.extend(cmd[2] or [])
            elif isinstance(cmd, int):
                line_ids.append(cmd)
        return self.env['account.move.line'].browse(line_ids)

    @api.model
    def _default_journal_id(self):
        """ The journal configured for the company, or the first
        Miscellaneous journal of the company. """
        company = self._lines_from_context()[:1].company_id or self.env.company
        journal = company.bank_fees_allocation_journal_id
        if journal:
            return journal
        return self.env['account.journal'].search([
            ('company_id', '=', company.id),
            ('type', '=', 'general'),
        ], limit=1)

    @api.model
    def _default_bank_account_id(self):
        """ The first configured bank account of the company. """
        company = self._lines_from_context()[:1].company_id or self.env.company
        return company.bank_fees_bank_account_ids[:1]

    @api.model
    def _default_fee_account_id(self):
        """ The fee expense account configured for the company. """
        company = self._lines_from_context()[:1].company_id or self.env.company
        return company.bank_fees_expense_account_id

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends('line_ids')
    def _compute_company_id(self):
        for wizard in self:
            wizard.company_id = wizard.line_ids[:1].company_id or self.env.company

    @api.depends('line_ids', 'line_ids.branch_id')
    def _compute_branch_ids(self):
        """ The branches of the selected journal items (read-only display). """
        for wizard in self:
            wizard.branch_ids = wizard.line_ids.mapped('branch_id')

    @api.depends('company_id', 'company_id.bank_fees_bank_account_ids',
                 'company_id.bank_fees_expense_account_id')
    def _compute_allowed_accounts(self):
        """ The accounts the user may pick.

        The **bank accounts** are the ones configured for the company (the
        *Bank Accounts* setting).  When the company has none configured,
        every *Bank and Cash* account of the company is proposed, so the
        wizard stays usable.

        The **fee accounts** are the *expense* accounts of the company, and
        the account configured as the *Bank Fees Expense Account* is always
        proposed (even when it is not an expense account, so that the
        administrator is not blocked by a wrong configuration).
        """
        for wizard in self:
            company = wizard.company_id or self.env.company
            accounts_model = self.env['account.account']

            bank_accounts = company.bank_fees_bank_account_ids
            if not bank_accounts:
                bank_accounts = accounts_model.search([
                    ('company_ids', 'in', company.ids),
                    ('account_type', '=', 'asset_cash'),
                ])
            wizard.allowed_bank_account_ids = bank_accounts

            fee_accounts = accounts_model.search([
                ('company_ids', 'in', company.ids),
                ('account_type', 'in', ('expense', 'expense_other')),
            ])
            if company.bank_fees_expense_account_id:
                fee_accounts |= company.bank_fees_expense_account_id
            wizard.allowed_fee_account_ids = fee_accounts

            journals = self.env['account.journal'].search([
                ('company_id', '=', company.id),
                ('type', '=', 'general'),
            ])
            if wizard.journal_id:
                journals |= wizard.journal_id
            wizard.allowed_journal_ids = journals

    @api.depends('line_ids', 'line_ids.balance', 'line_ids.currency_id',
                 'line_ids.company_currency_id', 'line_ids.amount_residual')
    def _compute_total_amount(self):
        """ Total Amount = sum of the balances of the selected items.

        The sum is always **positive**: the allocation works whatever the
        direction of the source items (a debit balance is a sale to be
        collected by the bank, a credit balance is a receipt to be netted).
        The direction of the selection is handled by ``_allocation_sign``.

        A selection that mixes both directions cannot be allocated in one
        go: it is refused by ``_check_amounts`` because the credit lines
        (one per account) would not add up to the total.
        """
        for wizard in self:
            wizard.total_amount = wizard.currency_id.round(
                sum(abs(amount) for amount in wizard._line_amounts())
            )

    def _line_amounts(self):
        """ Signed amount of every selected item, in the company currency.

        The items are read through the ORM, so the access rights and the
        record rules are applied by Odoo itself.
        """
        self.ensure_one()
        amounts = []
        for line in self.line_ids:
            currency, _reco, company_amount = line._bank_fees_amounts()
            amounts.append(company_amount)
        return amounts

    @api.depends('total_amount', 'fee_amount')
    def _compute_net_amount(self):
        """ Net Amount = Total - Fee. """
        for wizard in self:
            wizard.net_amount = wizard.currency_id.round(
                wizard.total_amount - wizard.fee_amount
            )

    @api.depends('total_amount', 'net_amount')
    def _compute_fee_amount(self):
        """ Fee Amount = Total - Net. """
        for wizard in self:
            wizard.fee_amount = wizard.currency_id.round(
                wizard.total_amount - wizard.net_amount
            )

    def _inverse_net_amount(self):
        """ The user typed the Net Amount: the Fee follows.

        ``fee_amount`` is a plain stored field here, so writing it simply
        triggers its own compute, which rebuilds the very same net amount:
        there is no ping-pong between the two fields.
        """
        for wizard in self:
            wizard.fee_amount = wizard.currency_id.round(
                wizard.total_amount - wizard.net_amount
            )

    def _inverse_fee_amount(self):
        """ The user typed the Fee Amount: the Net follows. """
        for wizard in self:
            wizard.net_amount = wizard.currency_id.round(
                wizard.total_amount - wizard.fee_amount
            )

    @api.onchange('net_amount')
    def _onchange_net_amount(self):
        """ Feed the fee live.

        The web client does **not** run the field inverses while computing
        an onchange (it only updates the cache and applies the
        ``@api.onchange`` methods), so without this method the fee would
        only follow the net amount after the record is saved.
        """
        for wizard in self:
            wizard.fee_amount = wizard.currency_id.round(
                wizard.total_amount - wizard.net_amount
            )

    @api.onchange('fee_amount')
    def _onchange_fee_amount(self):
        """ Feed the net amount live. """
        for wizard in self:
            wizard.net_amount = wizard.currency_id.round(
                wizard.total_amount - wizard.fee_amount
            )

    @api.onchange('line_ids')
    def _onchange_line_ids(self):
        """ Propose the configured bank and fee accounts. """
        for wizard in self:
            company = wizard.line_ids[:1].company_id or self.env.company
            if not wizard.bank_account_id:
                wizard.bank_account_id = company.bank_fees_bank_account_ids[:1]
            if not wizard.fee_account_id:
                wizard.fee_account_id = company.bank_fees_expense_account_id

    # ------------------------------------------------------------------
    # Validations
    # ------------------------------------------------------------------
    @api.constrains('line_ids', 'net_amount', 'fee_amount', 'bank_account_id',
                    'fee_account_id', 'journal_id', 'date')
    def _check_allocation(self):
        """ Single entry point so that the checks always run in the same order.

        The eligibility of every item is checked first, then the
        consistency of the selection, and only then the amounts: otherwise
        a fully reconciled item would produce a misleading amount error.
        """
        self._check_lines_eligibility()
        self._check_lines_consistency()
        self._check_accounts()
        self._check_branches()
        self._check_amounts()

    def _check_lines_eligibility(self):
        """ Every selected item must be posted, unreconciled and on a
        configured allocation account. """
        for wizard in self:
            for line in wizard.line_ids:
                error = line._bank_fees_eligibility_error()
                if error:
                    raise ValidationError(
                        "%s\n%s" % (error, _("Journal item: %s", line.display_name))
                    )
                allowed = wizard.company_id.bank_fees_allocation_account_ids
                if allowed and line.account_id not in allowed:
                    raise ValidationError(_(
                        "The journal item %s is not on a configured allocation "
                        "account.\nAccount: %s\n\nPlease configure the "
                        "allocation accounts in Accounting > Configuration > "
                        "Settings > Accounting > Bank Fees Allocation.",
                        line.display_name,
                        line.account_id.display_name,
                    ))

    def _check_lines_consistency(self):
        """ The selection must share the same company and the same currency. """
        for wizard in self:
            lines = wizard.line_ids
            if not lines:
                raise ValidationError(_("Please select at least one journal item to allocate."))
            error = lines._bank_fees_selection_error()
            if error:
                raise ValidationError(error)

    def _check_accounts(self):
        """ The bank account and the fee account must exist and be usable.

        The check only applies to a wizard that holds a selection: an
        empty wizard (the wizard is created before the lines are known)
        is not an error yet.
        """
        for wizard in self:
            if not wizard.line_ids:
                continue
            company = wizard.company_id
            if not wizard.bank_account_id:
                raise ValidationError(_("The bank account is required."))
            bank_accounts = company.bank_fees_bank_account_ids
            if bank_accounts and wizard.bank_account_id not in bank_accounts:
                raise ValidationError(_(
                    "The bank account %s is not one of the configured bank "
                    "accounts.\n\nPlease configure the bank accounts in "
                    "Accounting > Configuration > Settings > Accounting > "
                    "Bank Fees Allocation.",
                    wizard.bank_account_id.display_name,
                ))
            if not wizard.fee_account_id:
                raise ValidationError(_(
                    "The Bank Fees Expense Account is not configured.\n\n"
                    "Please configure it in Accounting > Configuration > "
                    "Settings > Accounting > Bank Fees Allocation."
                ))

    def _check_branches(self):
        """ The branch of the journal and the branches of the selection must
        be compatible.

        ``branch_management`` makes the journal the source of truth of the
        branch of an entry: an entry recorded in a journal that belongs to a
        branch must be on that branch.  A selection that spans several
        branches (or items without a branch) therefore cannot be posted in
        the journal of a branch: one entry per branch is generated, and none
        of them could use that journal.
        """
        for wizard in self:
            if not wizard.line_ids:
                continue
            journal_branch = wizard.journal_id.branch_id
            if not journal_branch:
                continue
            branches = wizard.line_ids.mapped('branch_id')
            if branches != journal_branch:
                raise ValidationError(_(
                    "The journal %(journal)s belongs to the branch "
                    "%(branch)s, but the selected journal items belong to "
                    "%(branches)s.\n\nChoose a journal without a branch to "
                    "allocate items of several branches, or select only the "
                    "items of the branch of the journal.",
                    journal=wizard.journal_id.display_name,
                    branch=journal_branch.display_name,
                    branches=', '.join(branches.mapped('display_name')) or _('no branch'),
                ))

    def _check_amounts(self):
        """ Net + Fee = Total, and both amounts are positive. """
        for wizard in self:
            currency = wizard.currency_id
            if currency.compare_amounts(wizard.fee_amount, 0.0) < 0:
                raise ValidationError(_("The fee amount cannot be negative."))
            if currency.compare_amounts(wizard.net_amount, 0.0) < 0:
                raise ValidationError(_("The net amount cannot be negative."))
            if currency.compare_amounts(
                wizard.net_amount + wizard.fee_amount, wizard.total_amount
            ) != 0:
                raise ValidationError(_(
                    "The net amount plus the fee amount (%s) must equal the "
                    "total amount (%s).",
                    currency.format(wizard.net_amount + wizard.fee_amount),
                    currency.format(wizard.total_amount),
                ))
            if currency.compare_amounts(wizard.total_amount, 0.0) <= 0:
                raise ValidationError(_(
                    "The selected journal items must add up to a positive "
                    "amount (%s).",
                    currency.format(wizard.total_amount),
                ))
            if not wizard.journal_id:
                raise ValidationError(_(
                    "A Miscellaneous journal is required. No journal of type "
                    "'Miscellaneous' was found for this company."))
            if not wizard.date:
                raise ValidationError(_("The journal entry date is required."))
            # The credit lines are built **per account**: the amounts of
            # the accounts must therefore add up to the total of the
            # selection, otherwise the entry would not be balanced.
            sign = wizard._allocation_sign()
            if not sign:
                raise ValidationError(_(
                    "The selected journal items cannot be allocated in one go: "
                    "they mix debits and credits.\n\nPlease select journal "
                    "items of the same direction."
                ))
            per_account = sum(
                currency.round(sum(lines.mapped('balance')))
                for _account, lines in wizard._group_lines_by_account()
            )
            if currency.compare_amounts(
                per_account, sign * wizard.total_amount
            ) != 0:
                raise ValidationError(_(
                    "The selected journal items cannot be allocated in one go: "
                    "their amounts do not add up to the total amount of the "
                    "selection (%s against %s).\n\nPlease select journal items "
                    "of the same direction.",
                    currency.format(per_account),
                    currency.format(sign * wizard.total_amount),
                ))
            # The entries are built **per branch** and, inside a branch,
            # **per account**: the rounded amounts of the branches must add
            # up to the total of the selection as well, otherwise one of the
            # generated entries would not be balanced.
            per_branch = sum(
                currency.round(sum(abs(amount) for amount in lines.mapped('balance')))
                for _branch, lines in wizard._group_lines_by_branch()
            )
            if currency.compare_amounts(per_branch, wizard.total_amount) != 0:
                raise ValidationError(_(
                    "The selected journal items cannot be allocated in one go: "
                    "their amounts, grouped by branch, do not add up to the "
                    "total amount of the selection (%s against %s).\n\nPlease "
                    "select journal items of the same direction.",
                    currency.format(per_branch),
                    currency.format(wizard.total_amount),
                ))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _allocation_sign(self):
        """ Direction of the selection.

        ``+1`` when the source items add up to a debit (a sale to be
        collected), ``-1`` when they add up to a credit.  The generated
        entry is mirrored from this value: nothing is hard-coded.

        A selection that mixes both directions has no sign: it is refused
        by ``_check_amounts``.
        """
        self.ensure_one()
        total = sum(self._line_amounts())
        if not total:
            return 1.0
        if any(amount * total < 0 for amount in self._line_amounts()):
            # Mixed directions: the sign is meaningless.
            return 0.0
        return 1.0 if total > 0 else -1.0
    def _validate_before_post(self):
        """ Re-run every validation right before anything is created: the
        journal items may have changed since the wizard was opened. """
        self.ensure_one()
        lines = self.line_ids.exists()
        if not lines:
            raise ValidationError(_("Please select at least one journal item to allocate."))
        # Force a fresh read of the items.
        lines.invalidate_recordset([
            'amount_residual', 'amount_residual_currency', 'reconciled',
            'parent_state', 'full_reconcile_id', 'account_id', 'balance',
            'amount_currency', 'currency_id', 'company_currency_id',
        ])
        self._check_lines_eligibility()
        self._check_lines_consistency()
        self._check_accounts()
        self._check_branches()
        self._check_amounts()

    # ------------------------------------------------------------------
    # Action
    # ------------------------------------------------------------------
    def action_post(self):
        """ Create the journal entries, post them and reconcile them with
        every selected journal item.

        The entries are **split per branch**: ``branch_management`` stores
        the branch of a journal item on its move (``account.move.line.
        branch_id`` is related to ``move_id.branch_id``), so the only way to
        carry the branch of the source items onto the generated lines is to
        generate one entry per branch.
        """
        self.ensure_one()
        if self.move_id:
            raise ValidationError(_(
                "This allocation has already been posted.\nJournal entry: %s",
                self.move_id.display_name,
            ))
        self._validate_before_post()

        source_lines = self.line_ids
        currency = self.currency_id
        company = self.company_id
        sign = self._allocation_sign()
        net = currency.round(self.net_amount)
        fees = currency.round(self.fee_amount)
        total = currency.round(self.total_amount)

        # ---- one group of credit lines per branch ----------------------
        # Inside a branch, the balances of the items of a same account are
        # added up; the analytic distribution of every item is carried over,
        # weighted by its share of the account total.
        prepared = []
        for branch, branch_lines in self._group_lines_by_branch():
            credits = []
            branch_amount = 0.0
            for account, account_lines in self._group_lines_by_account(branch_lines):
                amount = abs(currency.round(sum(account_lines.mapped('balance'))))
                credits.append((account, account_lines, amount))
                branch_amount = currency.round(branch_amount + amount)
            prepared.append({
                'branch': branch,
                'lines': branch_lines,
                'credits': credits,
                'amount': branch_amount,
            })
        if not prepared:
            raise ValidationError(_("Please select at least one journal item to allocate."))

        # The fees (and therefore the net amount) are split over the branches
        # proportionally to the amount of each branch.  The rounding is
        # adjusted so that the parts always add up to the fee exactly, and
        # the bank line of a branch takes the rest of the branch amount, so
        # that every generated entry stays balanced.
        fee_parts = self._split_amount(fees, [part['amount'] for part in prepared])

        moves = self.env['account.move']
        for part, fee_part in zip(prepared, fee_parts):
            branch = part['branch']
            branch_net = currency.round(part['amount'] - fee_part)
            move_line_commands = []

            # 1. the bank receives the net amount of the branch
            move_line_commands.append(Command.create({
                'name': self.ref or _('Bank Fees Allocation'),
                'account_id': self.bank_account_id.id,
                'balance': sign * branch_net,
            }))

            # 2. the fee of the branch is booked on the expense account,
            #    with the analytic distribution carried over from its items
            move_line_commands.append(Command.create({
                'name': _('Bank Fees'),
                'account_id': self.fee_account_id.id,
                'balance': sign * fee_part,
                'analytic_distribution': self._merged_distribution(part['lines']),
            }))

            # 3. one credit line per source account of the branch.
            #    The line takes the **opposite** of the sign of the
            #    selection: a selection of debits (a sale to be collected)
            #    is credited, a selection of credits is debited.
            for account, account_lines, amount in part['credits']:
                move_line_commands.append(Command.create({
                    'name': account.name,
                    'account_id': account.id,
                    'balance': -sign * amount,
                    'analytic_distribution': self._merged_distribution(account_lines),
                }))

            move_vals = {
                'move_type': 'entry',
                'journal_id': self.journal_id.id,
                'company_id': company.id,
                'date': self.date,
                'ref': self.ref or ', '.join(dict.fromkeys(part['lines'].mapped('move_id.name'))),
                'narration': _(
                    'Bank fees allocation for %s journal item(s): %s',
                    len(part['lines']),
                    ', '.join(part['lines'].mapped('display_name')),
                ),
                'review_state': 'reviewed',
                'line_ids': move_line_commands,
            }
            if branch:
                move_vals['branch_id'] = branch.id
            move = self.env['account.move'].with_context(
                skip_invoice_sync=True,
                skip_invoice_line_sync=True,
                skip_analytic_sync=False,
            ).create(move_vals)
            move.action_post()

            # ---- reconcile every credit line with its own source items ----
            # The counterpart line of an account is the only line of the
            # generated entry posted on that very account.
            for account, account_lines, _amount in part['credits']:
                counterpart = move.line_ids.filtered(
                    lambda move_line, account=account: move_line.account_id == account
                )
                if not counterpart:
                    raise ValidationError(_(
                        "Could not identify the counterpart of the journal items of "
                        "the account %s in the created journal entry.",
                        account.display_name,
                    ))
                (account_lines | counterpart).reconcile()

            moves |= move

        # ---- store the allocation --------------------------------------
        allocation = self.env['bank.fees.allocation'].create({
            'date': self.date,
            'company_id': company.id,
            'user_id': self.env.user.id,
            'bank_account_id': self.bank_account_id.id,
            'journal_id': self.journal_id.id,
            'currency_id': currency.id,
            'total_amount': total,
            'net_amount': net,
            'fee_amount': fees,
            'move_id': moves[:1].id,
            'move_ids': [Command.set(moves.ids)],
            'line_ids': [Command.set(source_lines.ids)],
        })
        self.move_id = moves[:1]
        self.move_ids = moves

        return {
            'type': 'ir.actions.act_window',
            'name': _('Bank Fees Allocation'),
            'res_model': 'bank.fees.allocation',
            'res_id': allocation.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _group_lines_by_branch(self):
        """ Group the selected journal items by their branch.

        :return: an ordered list of ``(branch, lines)`` tuples.  ``branch``
                 is an empty recordset for the items without a branch.
        """
        self.ensure_one()
        groups = []
        for line in self.line_ids.sorted(lambda line: (line.branch_id.id or 0, line.id)):
            branch = line.branch_id
            for index, (existing_branch, existing_lines) in enumerate(groups):
                if existing_branch == branch:
                    groups[index] = (branch, existing_lines | line)
                    break
            else:
                groups.append((branch, line))
        return groups

    def _split_amount(self, amount, weights):
        """ Split ``amount`` over ``weights`` with a fixed rounding.

        The parts are rounded in the currency of the allocation and the
        rounding difference is given to the biggest weight, so that the sum
        of the parts is **exactly** ``amount``.

        :return: a list of positive amounts, one per weight.
        """
        self.ensure_one()
        currency = self.currency_id
        amount = currency.round(amount)
        weights = list(weights)
        if not weights:
            return []
        total_weight = sum(weights)
        if not total_weight:
            parts = [currency.round(amount / len(weights))] * len(weights)
        else:
            parts = [
                currency.round(amount * weight / total_weight)
                for weight in weights
            ]
        difference = currency.round(amount - sum(parts))
        if difference:
            index = max(range(len(weights)), key=lambda i: (weights[i], i))
            parts[index] = currency.round(parts[index] + difference)
        return parts

    def _group_lines_by_account(self, lines=None):
        """ Group the given journal items by their account.

        :param lines: the items to group, the whole selection by default.
        :return: an ordered list of ``(account, lines)`` tuples.
        """
        self.ensure_one()
        lines = self.line_ids if lines is None else lines
        groups = []
        for line in lines.sorted(lambda line: (line.account_id.id, line.id)):
            account = line.account_id
            for index, (existing_account, existing_lines) in enumerate(groups):
                if existing_account == account:
                    groups[index] = (account, existing_lines | line)
                    break
            else:
                groups.append((account, line))
        return groups


    def _merged_distribution(self, lines):
        """ Analytic distribution carried over from the given journal items.

        The distribution of every item is weighted by its share of the
        total amount of the group, so that the fee line (and the credit
        lines) keep the *proportional* analytic distribution of the source
        items, as the branch / cost centre of each sale.
        """
        self.ensure_one()
        lines = lines.exists()
        if not lines:
            return {}
        currency = self.currency_id
        total = sum(lines.mapped('balance'))
        merged = {}
        for line in lines:
            distribution = line.analytic_distribution or {}
            if not distribution:
                continue
            if not total:
                weight = 100.0 / len(lines)
            else:
                weight = (line.balance / total) * 100.0
            for key, percentage in distribution.items():
                merged[key] = merged.get(key, 0.0) + (percentage * weight)
        # Drop the rounding noise and normalise on 100 when there is any.
        cleaned = {
            key: currency.round(value)
            for key, value in merged.items()
            if not currency.is_zero(value)
        }
        if not cleaned:
            return {}
        # Normalise the percentages so that they add up to 100.
        total_percentage = sum(cleaned.values())
        if total_percentage:
            cleaned = {
                key: currency.round(value * 100.0 / total_percentage)
                for key, value in cleaned.items()
            }
        return cleaned

    def action_cancel(self):
        """ Close the wizard without doing anything. """
        return {'type': 'ir.actions.act_window_close'}
