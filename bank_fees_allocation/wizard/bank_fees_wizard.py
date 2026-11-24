from datetime import timedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import ValidationError

from ..models.account_move_line import EXPENSE_ACCOUNT_TYPES


class BankFeesAllocationWizard(models.TransientModel):
    """ Bank Fees Allocation wizard.

    It receives **one or several** journal items taken from
    *Accounting > Reconcile* (Journal Items to Reconcile), lets the user split
    the amount available for reconciliation between the **Unlink Account** and a
    bank-fees expense account, then:

        1. creates **one single** ``account.move`` through the regular ORM,
        2. posts it with the regular ``action_post()`` workflow,
        3. reconciles it with every selected journal item through Odoo's own
           ``account.move.line.reconcile()``.

    Nothing from Odoo core is overwritten: the model is brand new (``_name``)
    and only *uses* core APIs.  The form layout mirrors
    ``account_accountant.view_account_reconcile_wizard`` (the standard
    **Reconcile** button wizard): left column = accounts/journal/label, right
    column = amounts + date + cost center, footer = one primary action.

    The generated entry contains the **reconciling line**, the **remaining
    amount line** and — only when fees are actually charged — the **bank fees
    line**::

        (-sign) source account       total amount    <- reconciles them
        (+sign) unlink account       original amount <- remaining amount
        (+sign) bank fees account    fees amount     <- bank fees + cost center

    where ``total = sum of the residuals`` and ``original + fees == total``,
    so the entry is balanced by construction.  A line is dropped when it is
    worth nothing in **both** currencies.

    The **Unlink Account** is *optional*: when it is left empty the remaining
    amount simply stays on the source account (the remaining line then uses
    the same account as the reconciling one).  Only **Bank and Cash** accounts
    are offered for it.

    The **Bank Fees configuration is required only when fees are actually
    charged** (``fees_amount != 0``): with zero fees the fees line is worth
    nothing in both currencies and is dropped, so asking for a fees account
    and a cost center would be pure friction.
    """
    _name = 'bank.fees.allocation.wizard'
    _inherit = ['analytic.mixin']
    _description = 'Closing Fees'
    _check_company_auto = True

    # ------------------------------------------------------------------
    # Source journal items
    # ------------------------------------------------------------------
    line_ids = fields.Many2many(
        comodel_name='account.move.line',
        string='Journal Items',
        help='Journal items selected in the "Journal Items to Reconcile" list.',
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        compute='_compute_company_id',
        store=True,
        readonly=True,
        index=True,
    )
    source_account_id = fields.Many2one(
        comodel_name='account.account',
        string='Source Account',
        compute='_compute_source_account_id',
        readonly=True,
        help='Common account of every selected journal item. The line that '
             'reconciles them is always posted on this account (Odoo refuses '
             'to reconcile items coming from different accounts).',
    )

    # ------------------------------------------------------------------
    # Amounts (always shown as positive amounts, like the specification)
    # ------------------------------------------------------------------
    reco_currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Reconciliation Currency',
        compute='_compute_amount_data',
    )
    total_amount = fields.Monetary(
        string='Amount',
        currency_field='reco_currency_id',
        compute='_compute_amount_data',
        help='Sum of the amounts still available for reconciliation on the '
             'selected journal items. Not editable.',
    )
    original_amount = fields.Monetary(
        string='Unlink Account Amount',
        currency_field='reco_currency_id',
        compute='_compute_original_amount',
        inverse='_inverse_original_amount',
        store=True,
        readonly=False,
    )
    fees_amount = fields.Monetary(
        string='Bank Fees Amount',
        currency_field='reco_currency_id',
        default=0.0,
        help='Single fee amount covering the whole selection. '
             'Zero means: no bank fees, no fees account and no cost center '
             'are required.',
    )
    reconciled_total = fields.Monetary(
        string='Total',
        currency_field='reco_currency_id',
        compute='_compute_reconciled_total',
    )

    # ------------------------------------------------------------------
    # Bank fees configuration (only required when fees_amount != 0)
    # ------------------------------------------------------------------
    fees_account_id = fields.Many2one(
        comodel_name='account.account',
        string='Bank Fees Account',
        check_company=True,
        default=lambda self: self._default_fees_account(),
        domain="[('account_type', 'in', ['expense', 'expense_other', 'expense_depreciation', "
                "'expense_direct_cost']), ('company_ids', 'parent_of', company_id)]",
        help='Expense account that receives the bank fees portion. '
             'Pre-filled from the company default set in Settings > '
             'Invoicing > Closing Fees; only required when the Bank Fees '
             'Amount is not zero.',
    )
    unlink_account_id = fields.Many2one(
        comodel_name='account.account',
        string='Unlink Account',
        check_company=True,
        domain="[('account_type', '=', 'asset_cash'), "
               "('company_ids', 'parent_of', company_id)]",
        help='Account that receives the remaining amount. Leave it EMPTY to '
             'keep the remainder on the account of the selected journal items '
             '(the default). Only Bank and Cash accounts are offered.',
    )

    # ------------------------------------------------------------------
    # Entry configuration
    # ------------------------------------------------------------------
    journal_id = fields.Many2one(
        comodel_name='account.journal',
        string='Journal',
        check_company=True,
        domain="[('type', '=', 'general')]",
        compute='_compute_journal_id',
        store=True,
        readonly=False,
    )
    date = fields.Date(
        string='Date',
        compute='_compute_date',
        store=True,
        readonly=False,
    )
    label = fields.Char(string='Label', default='Closing Fees')
    move_id = fields.Many2one(
        comodel_name='account.move',
        string='Created Journal Entry',
        readonly=True,
    )

    # ==================================================================
    # Defaults
    # ==================================================================
    @api.model
    def _default_fees_account(self):
        """The company default set in Settings > Invoicing > Closing Fees.

        The company is taken from the selected journal items (the button
        puts them in the context as ``default_line_ids``), falling back to
        the active company. The wizard field stays editable: the default
        saves the repetition, it does not remove the choice.
        """
        line_ids = []
        for cmd in self.env.context.get('default_line_ids') or []:
            if isinstance(cmd, (list, tuple)) and len(cmd) >= 3:
                line_ids.extend(cmd[2] or [])
            elif isinstance(cmd, int):
                line_ids.append(cmd)
        company = (self.env['account.move.line'].browse(line_ids)[:1].company_id
                   or self.env.company)
        return company.bank_fees_account_id

    # ==================================================================
    # Computes
    # ==================================================================
    @api.depends('line_ids')
    def _compute_company_id(self):
        for wizard in self:
            wizard.company_id = wizard.line_ids[:1].company_id

    @api.depends('line_ids')
    def _compute_source_account_id(self):
        for wizard in self:
            wizard.source_account_id = wizard.line_ids[:1].account_id

    def _bank_fees_line_values(self, line):
        """ (reconciliation currency, signed residual in that currency,
        signed residual in the company currency) for one journal item. """
        self.ensure_one()
        if line.currency_id and line.currency_id != line.company_currency_id:
            return line.currency_id, line.amount_residual_currency, line.amount_residual
        return line.company_currency_id, line.amount_residual, line.amount_residual

    def _aggregate(self):
        """ Sum the residuals of every selected journal item.

        :return: (currency, sum in reconciliation currency, sum in company
                 currency). When the selection mixes currencies the sums are
                 meaningless and returned as 0: ``_check_lines_consistency``
                 raises the proper error before the amounts are ever used.
        """
        self.ensure_one()
        values = [self._bank_fees_line_values(line) for line in self.line_ids]
        if not values:
            return False, 0.0, 0.0
        currency = values[0][0]
        if any(value[0] != currency for value in values):
            return currency, 0.0, 0.0
        return (
            currency,
            sum(value[1] for value in values),
            sum(value[2] for value in values),
        )

    @api.depends(
        'line_ids',
        'line_ids.amount_residual',
        'line_ids.amount_residual_currency',
        'line_ids.currency_id',
    )
    def _compute_amount_data(self):
        """ Reconciliation currency + amount still available for reconciliation.

        Same rule as Odoo's own reconciliation wizard: use the foreign currency
        when the journal items carry one, otherwise the company currency.
        The amount is always returned as a **positive** quantity.
        """
        for wizard in self:
            currency, reco_residual, _company_residual = wizard._aggregate()
            wizard.reco_currency_id = currency
            wizard.total_amount = abs(reco_residual) if currency else 0.0

    @api.depends('total_amount', 'fees_amount')
    def _compute_original_amount(self):
        """ Unlink Account Amount = Total - Bank Fees Amount. """
        for wizard in self:
            currency = wizard.reco_currency_id
            wizard.original_amount = (
                currency.round(wizard.total_amount - wizard.fees_amount) if currency else 0.0
            )

    def _sync_fees_from_original(self):
        """ Bank Fees Amount = Total - Unlink Account Amount. """
        for wizard in self:
            currency = wizard.reco_currency_id
            if currency:
                wizard.fees_amount = currency.round(
                    wizard.total_amount - wizard.original_amount
                )

    def _inverse_original_amount(self):
        """ The user typed the Unlink Account Amount, so
        Bank Fees Amount = Total - Unlink Account Amount.

        Only fires when ``original_amount`` is written by the user.
        ``fees_amount`` is a plain field: once it has been updated the compute
        above simply rebuilds the very same ``original_amount``, therefore
        there is no onchange ping-pong.
        """
        self._sync_fees_from_original()

    @api.onchange('original_amount')
    def _onchange_original_amount(self):
        """ Feed the remainder into the Bank Fees Amount **live**.

        Odoo's web client does *not* run field inverses while computing an
        onchange (it only updates the cache, marks the dependencies and
        applies ``@api.onchange`` methods), so without this method the Bank
        Fees Amount would only follow the Unlink Account Amount after the
        record is saved.
        """
        self._sync_fees_from_original()

    @api.depends('original_amount', 'fees_amount')
    def _compute_reconciled_total(self):
        for wizard in self:
            wizard.reconciled_total = wizard.original_amount + wizard.fees_amount

    @api.depends('company_id')
    def _compute_journal_id(self):
        """ Same rule as Odoo's own reconciliation wizard: first 'general'
        journal of the company. Nothing is hard-coded. """
        journal_model = self.env['account.journal']
        for wizard in self:
            wizard.journal_id = journal_model.search(
                [*journal_model._check_company_domain(wizard.company_id), ('type', '=', 'general')],
                limit=1,
            )

    @api.depends('line_ids', 'company_id')
    def _compute_date(self):
        """ Accounting date honouring the lock dates (Odoo's own helper).

        Uses the highest date of the selection, like Odoo's own wizard.

        Only the *default* is adjusted here: a date the user picked himself is
        never moved, it is refused instead (see ``_check_accounting_date``).

        ``journal_id`` is deliberately **not** a dependency: depending on it
        would recompute the date every time the user picks another journal and
        silently overwrite the date he already chose.  The journal is simply
        read here (Odoo computes a pending stored field the moment it is
        accessed), so the very first default is still lock-aware, while a
        journal change only *re-validates* the date through
        ``_check_accounting_date`` and never moves it.
        """
        for wizard in self:
            if wizard.line_ids and wizard.journal_id:
                highest_date = max(wizard.line_ids.mapped('date'))
                temp_move = self.env['account.move'].new({'journal_id': wizard.journal_id.id})
                date = temp_move._get_accounting_date(highest_date, False)
            else:
                date = fields.Date.context_today(wizard)
            # safety net: the default must never land in a locked period,
            # otherwise simply opening the wizard would raise.
            lock_dates = wizard._bank_fees_lock_dates(date)
            if lock_dates:
                date = lock_dates[-1][0] + timedelta(days=1)
            wizard.date = date

    # ==================================================================
    # Validations
    # ==================================================================
    @api.constrains('line_ids', 'unlink_account_id', 'original_amount', 'fees_amount',
                    'fees_account_id', 'analytic_distribution', 'journal_id', 'date')
    def _check_bank_fees(self):
        """ Single entry point so the checks always run in the same order:
        eligibility of every item, then consistency of the selection, and only
        then the amounts (otherwise a fully reconciled item would produce a
        misleading amount error). """
        self._check_lines_eligibility()
        self._check_lines_consistency()
        self._check_amounts()
        self._check_accounting_date()

    def _check_lines_eligibility(self):
        for wizard in self:
            for line in wizard.line_ids:
                error = line._bank_fees_eligibility_error()
                if error:
                    raise ValidationError(
                        "%s\n%s" % (error, _("Journal item: %s", line.display_name))
                    )

    def _check_lines_consistency(self):
        for wizard in self:
            lines = wizard.line_ids
            if not lines:
                raise ValidationError(_("Please select at least one journal item to use Closing Fees."))
            error = lines._bank_fees_selection_error()
            if error:
                raise ValidationError(error)

    def _check_amounts(self):
        for wizard in self:
            currency = wizard.reco_currency_id
            if not currency:
                continue
            if not wizard.journal_id:
                raise ValidationError(_(
                    "A General journal is required. No journal of type "
                    "'Miscellaneous' was found for this company."))
            if not wizard.date:
                raise ValidationError(_("The journal entry date is required."))
            if wizard.unlink_account_id and wizard.unlink_account_id.account_type != 'asset_cash':
                raise ValidationError(_(
                    "Unlink Account must be a Bank and Cash account.\n"
                    "Selected account: %s (type: %s).",
                    wizard.unlink_account_id.display_name,
                    wizard.unlink_account_id.account_type,
                ))
            if currency.is_zero(wizard.total_amount):
                raise ValidationError(_("The journal item is no longer available for reconciliation."))
            if currency.compare_amounts(wizard.fees_amount, 0.0) < 0:
                raise ValidationError(_("Bank Fees Amount cannot be negative."))
            if currency.compare_amounts(wizard.original_amount, 0.0) < 0:
                raise ValidationError(_("Unlink Account Amount cannot be negative."))
            if currency.compare_amounts(
                wizard.original_amount + wizard.fees_amount, wizard.total_amount
            ) != 0:
                raise ValidationError(_(
                    "The amounts do not match the amount available for reconciliation.\n"
                    "Unlink Account Amount + Bank Fees Amount must equal %s.",
                    currency.format(wizard.total_amount),
                ))
            # The fees configuration (expense account + cost center) is only
            # meaningful when fees are actually charged: with zero fees the
            # fees line is worth nothing in both currencies and is dropped
            # from the generated entry, so nothing would ever use them.
            if currency.is_zero(wizard.fees_amount):
                continue
            if not wizard.fees_account_id:
                raise ValidationError(_("Bank Fees Account is required."))
            if wizard.fees_account_id.account_type not in EXPENSE_ACCOUNT_TYPES:
                raise ValidationError(_(
                    "Bank Fees Account must be an Expense account.\n"
                    "Selected account: %s (type: %s).",
                    wizard.fees_account_id.display_name,
                    wizard.fees_account_id.account_type,
                ))
            if not wizard.analytic_distribution:
                raise ValidationError(_("Cost Center is required for Bank Fees."))

    # ------------------------------------------------------------------
    # Accounting date
    # ------------------------------------------------------------------
    def _bank_fees_lock_dates(self, date=None):
        """ Lock dates violated by ``date`` for this wizard, ordered
        chronologically (an empty list means the date is allowed). """
        self.ensure_one()
        if date is None:
            date = self.date
        if not date or not self.journal_id or not self.company_id:
            return []
        return self.company_id._get_violated_lock_dates(date, False, self.journal_id)

    def _check_accounting_date(self):
        """ The accounting date is the **user's** choice: when a lock date
        blocks it we raise a clear error instead of silently moving the entry
        to another date. """
        for wizard in self:
            lock_dates = wizard._bank_fees_lock_dates()
            if not lock_dates:
                continue
            earliest = lock_dates[-1][0] + timedelta(days=1)
            raise ValidationError(_(
                "Invalid journal entry date: %s.\n"
                "It is blocked by: %s.\n"
                "Please choose a date on or after %s. The date you picked is "
                "never changed silently.",
                wizard.date,
                wizard.company_id._format_lock_dates(lock_dates),
                earliest,
            ))

    # ==================================================================
    # Helpers
    # ==================================================================
    def _bank_fees_sign(self):
        """ Direction of the selection.

        +1 when the residuals add up to a debit, -1 when they add up to a
        credit. The whole entry is mirrored from this value: nothing is
        hard-coded.
        """
        self.ensure_one()
        _currency, reco_residual, _company_residual = self._aggregate()
        return 1.0 if reco_residual > 0.0 else -1.0

    def _uses_foreign_currency(self):
        self.ensure_one()
        currency, _reco, _company = self._aggregate()
        return bool(currency and currency != self.company_id.currency_id)

    def _validate_before_post(self):
        """ Re-run every validation right before anything is created: the
        journal items may have changed since the wizard was opened. """
        self.ensure_one()
        lines = self.line_ids.exists()
        if not lines:
            raise ValidationError(_("Please select at least one journal item to use Closing Fees."))
        # Force a fresh read of the journal items residuals.
        lines.invalidate_recordset([
            'amount_residual', 'amount_residual_currency', 'reconciled', 'parent_state',
            'full_reconcile_id', 'account_id', 'balance', 'amount_currency',
        ])
        self._check_lines_eligibility()
        self._check_lines_consistency()
        self._check_amounts()
        self._check_accounting_date()

    # ==================================================================
    # Action
    # ==================================================================
    def action_post(self):
        """ Create **one** journal entry, post it and reconcile it with every
        selected journal item. """
        self.ensure_one()
        # Already posted? Say so *before* the eligibility check, otherwise the
        # user gets the misleading "the journal item has already been
        # reconciled" and no second entry can slip through.
        if self.move_id:
            raise ValidationError(_(
                "This Closing Fees wizard has already been posted.\n"
                "Journal entry: %s",
                self.move_id.display_name,
            ))
        self._validate_before_post()

        source_lines = self.line_ids
        source_account = self.source_account_id
        # the Unlink Account is optional: empty means "keep it where it is"
        unlink_account = self.unlink_account_id or source_account
        currency = self.reco_currency_id
        company = self.company_id
        company_currency = company.currency_id
        sign = self._bank_fees_sign()
        foreign = self._uses_foreign_currency()

        _currency, source_reco_residual, source_balance_residual = self._aggregate()
        original = self.original_amount
        fees = self.fees_amount

        # One partner when the selection shares one, none otherwise: exactly
        # the rule Odoo's own write-off wizard uses.
        partners = source_lines.mapped('partner_id')
        partner_id = partners.id if len(partners) == 1 else False

        # ---- journal entry date: the user's own choice. It was already
        #      validated against every lock date, so it is used exactly as
        #      picked and is never silently moved (see _check_accounting_date).
        date = self.date

        # ---- amounts ---------------------------------------------------
        # balance values are derived from the *actual* aggregated residual so
        # that the reconciliation is exact in both currencies and the generated
        # entry is always perfectly balanced, even with rounding.
        if foreign:
            fees_balance = currency._convert(sign * fees, company_currency, company, date)
        else:
            fees_balance = sign * fees

        lines = [
            # 1. reconciling line: posted on the SOURCE account, it is the one
            #    that fully clears every selected journal item.
            {
                'account_id': source_account.id,
                'amount_currency': -source_reco_residual,
                'balance': -source_balance_residual,
            },
            # 2. remaining amount, unloaded on the account the user picked
            {
                'account_id': unlink_account.id,
                'amount_currency': sign * original,
                'balance': source_balance_residual - fees_balance,
            },
            # 3. bank fees on the expense account, with the cost center
            {
                'account_id': self.fees_account_id.id,
                'amount_currency': sign * fees,
                'balance': fees_balance,
                'analytic_distribution': self.analytic_distribution,
            },
        ]
        # A line is dropped only when it is worth nothing in **both**
        # currencies.  Filtering on amount_currency alone would silently drop
        # the "Unlink" line of a foreign-currency selection whose exchange rate
        # moved (Unlink Account Amount = 0): that line keeps a company balance
        # but a zero amount_currency, and without it the entry would be refused
        # as unbalanced.  With zero fees the fees line is dropped the same way
        # (which is why no fees account is required in that case).
        line_ids = [
            Command.create({
                'name': self.label or _('Closing Fees'),
                'partner_id': partner_id,
                'currency_id': currency.id,
                **line_vals,
            })
            for line_vals in lines
            if not currency.is_zero(line_vals['amount_currency'])
            or not company_currency.is_zero(line_vals['balance'])
        ]

        move = self.env['account.move'].with_context(
            skip_invoice_sync=True,
            skip_invoice_line_sync=True,
        ).create({
            'move_type': 'entry',
            'journal_id': self.journal_id.id,
            'company_id': company.id,
            'date': date,
            'ref': ', '.join(dict.fromkeys(source_lines.mapped('move_id.name'))),
            'narration': _(
                'Closing Fees allocation for %s journal item(s): %s',
                len(source_lines), ', '.join(source_lines.mapped('display_name')),
            ),
            'review_state': 'reviewed',
            'line_ids': line_ids,
        })
        move.action_post()

        # ---- locate the reconciling line of the new entry ---------------
        # It is the only line on the SOURCE account whose balance is the exact
        # opposite of the aggregated residual (the remaining line, whatever
        # its account, can never match: that would require fees = 2 x total).
        candidates = move.line_ids.filtered(
            lambda move_line: move_line.account_id == source_account
            and company_currency.compare_amounts(
                move_line.balance, -source_balance_residual
            ) == 0
        )
        reconcile_line = candidates.sorted(key=lambda move_line: move_line.id)[:1]
        if not reconcile_line:
            raise ValidationError(_(
                "Could not identify the counterpart of the selected journal items "
                "in the created journal entry."
            ))

        # ---- automatic reconciliation, through Odoo's own API ----------
        (source_lines + reconcile_line).reconcile()

        self.move_id = move
        # Return a **notification + dialog close**, never a navigation.
        # Opening the created entry with a ``target: 'current'`` action
        # navigates the main view *while the "Journal Items to Reconcile"
        # list behind the dialog is reloading* (its items were just
        # reconciled).  The reload's in-flight reads (line rows + the Cost
        # Center column's analytic-account reads) are then orphaned by the
        # destruction and the browser reports the well-known
        # "Component is destroyed" uncaught promise — observed live on
        # every Post (2026-10-03).  Closing the dialog calmly lets the list
        # finish its reload in place; the entry name is in the message.
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Closing Fees'),
                'message': _(
                    'Journal entry %s posted and reconciled with %s journal '
                    'item(s).', move.display_name, len(source_lines)),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def action_cancel(self):
        return {'type': 'ir.actions.act_window_close'}
