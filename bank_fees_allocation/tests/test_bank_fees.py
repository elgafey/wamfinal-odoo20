import re

from odoo import Command, fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form

from odoo.addons.bank_fees_allocation.models.account_move_line import EXPENSE_ACCOUNT_TYPES


class TestBankFeesAllocation(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # The list header button (like the standard Reconcile one) is guarded
        # by account.group_account_user.
        if not cls.env.user.has_group('account.group_account_user'):
            cls.env.user.write({
                'group_ids': [Command.link(cls.env.ref('account.group_account_user').id)],
            })

        cls.company = cls.env.company
        cls.currency = cls.company.currency_id
        cls.partner = cls.env['res.partner'].create({'name': 'Bank Fees Partner'})

        cls.account_recv = cls.company_data['default_account_receivable']
        cls.account_expense = cls.company_data['default_account_expense']
        cls.account_revenue = cls.company_data['default_account_revenue']
        cls.journal_misc = cls.company_data['default_journal_misc']

        cls.analytic_plan = cls.env['account.analytic.plan'].create({'name': 'Closing Fees Plan'})
        cls.analytic_account = cls.env['account.analytic.account'].create({
            'name': 'Riyadh Cost Center',
            'plan_id': cls.analytic_plan.id,
        })
        cls.analytic_distribution = {str(cls.analytic_account.id): 100.0}

    def test_00_views_expose_both_buttons(self):
        """ The standard Reconcile button is untouched and ours is added next
        to it; the wizard form exposes every required field. """
        primary = self.env.ref('account_accountant.view_move_line_reconcile_tree')
        arch = self.env['account.move.line'].get_view(primary.id, 'list')['arch']
        self.assertIn('action_reconcile', arch, 'standard Reconcile button disappeared')
        self.assertIn('action_bank_fees_allocation', arch, 'Closing Fees button not added')

        wizard_arch = self.env['bank.fees.allocation.wizard'].get_view(
            self.env.ref('bank_fees_allocation.bank_fees_wizard_form').id, 'form',
        )['arch']
        for fname in ('line_ids', 'source_account_id', 'unlink_account_id', 'total_amount',
                      'original_amount',
                      'fees_account_id', 'fees_amount', 'analytic_distribution',
                      'journal_id', 'date', 'reconciled_total'):
            self.assertIn(fname, wizard_arch, f'wizard field {fname} missing')

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @classmethod
    def _create_source(cls, amount=10000.0, credit=False, currency=None, partner=None, account=None):
        """ Create a posted, reconcilable journal item and return it. """
        sign = -1.0 if credit else 1.0
        source_account = account or cls.account_recv
        partner = partner or cls.partner
        line_vals = {
            'name': 'Bank Fees source',
            'account_id': source_account.id,
            'partner_id': partner.id,
        }
        other_vals = {
            'name': 'Bank Fees counterpart',
            'account_id': cls.account_revenue.id,
            'partner_id': partner.id,
        }
        if currency and currency != cls.currency:
            balance = currency._convert(amount, cls.currency, cls.company, fields.Date.today())
            line_vals.update({'currency_id': currency.id, 'amount_currency': sign * amount,
                              'balance': sign * balance})
            other_vals.update({'currency_id': currency.id, 'amount_currency': -sign * amount,
                               'balance': -sign * balance})
        else:
            line_vals.update({'debit': sign * amount if sign > 0 else 0.0,
                              'credit': -sign * amount if sign < 0 else 0.0})
            other_vals.update({'debit': -sign * amount if sign > 0 else 0.0,
                               'credit': sign * amount if sign < 0 else 0.0})
        move = cls.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': cls.journal_misc.id,
            'date': fields.Date.today(),
            'line_ids': [Command.create(line_vals), Command.create(other_vals)],
        })
        move.action_post()
        source = move.line_ids.filtered(lambda l: l.account_id == source_account)
        assert source, 'source line not found'
        return source

    def _create_wizard(self, line, fees=500.0, analytic=True, account=None):
        lines = self.env['account.move.line']
        for item in line:
            lines |= item
        return self.env['bank.fees.allocation.wizard'].create({
            'line_ids': [Command.set(lines.ids)],
            'fees_account_id': (account or self.account_expense).id,
            'fees_amount': fees,
            'analytic_distribution': self.analytic_distribution if analytic else False,
        })

    def _new_lines(self, wizard):
        return wizard.move_id.line_ids

    # ==================================================================
    # 1 & 2 - both amounts are linked, in both directions
    # ==================================================================
    def test_01_fees_entered_first(self):
        """ Bank Fees entered first -> Unlink Account Amount follows. """
        line = self._create_source()
        wizard = self._create_wizard(line, fees=500.0)
        self.assertEqual(wizard.total_amount, 10000.0)
        self.assertEqual(wizard.fees_amount, 500.0)
        self.assertEqual(wizard.original_amount, 9500.0)
        self.assertEqual(wizard.reconciled_total, 10000.0)
        self.assertFalse(wizard.unlink_account_id,
                         'Unlink Account must start empty')

    def test_02_original_entered_first(self):
        """ Unlink Account Amount entered first -> Bank Fees follows. """
        line = self._create_source()
        wizard = self._create_wizard(line, fees=0.0)
        self.assertEqual(wizard.original_amount, 10000.0)
        wizard.original_amount = 9500.0
        self.assertEqual(wizard.fees_amount, 500.0)
        # and the compute rebuilds the very same original amount (no loop)
        self.assertEqual(wizard.original_amount, 9500.0)
        self.assertEqual(wizard.reconciled_total, 10000.0)

    # ==================================================================
    # 3 - debit / credit direction
    # ==================================================================
    def test_03_direction_debit_source(self):
        """ Debit source item -> balancing line is a credit, fees are a debit. """
        line = self._create_source()
        self.assertGreater(line.balance, 0.0)
        wizard = self._create_wizard(line, fees=500.0)
        wizard.action_post()

        lines = self._new_lines(wizard)
        self.assertEqual(len(lines), 3)
        balancing = lines.filtered(lambda l: l.balance < 0)
        original = lines.filtered(lambda l: l.account_id == self.account_recv and l.balance > 0)
        fees = lines.filtered(lambda l: l.account_id == self.account_expense)
        self.assertEqual(len(balancing), 1)
        self.assertEqual(balancing.account_id, self.account_recv)
        self.assertEqual(balancing.balance, -10000.0)
        self.assertEqual(original.balance, 9500.0)
        self.assertEqual(fees.balance, 500.0)
        self.assertAlmostEqual(sum(lines.mapped('balance')), 0.0, places=4)

    def test_04_direction_credit_source(self):
        """ Credit source item -> the whole entry is mirrored. """
        line = self._create_source(credit=True)
        self.assertLess(line.balance, 0.0)
        wizard = self._create_wizard(line, fees=500.0)
        wizard.action_post()

        lines = self._new_lines(wizard)
        self.assertEqual(len(lines), 3)
        balancing = lines.filtered(lambda l: l.balance > 0)
        self.assertEqual(balancing.account_id, self.account_recv)
        self.assertEqual(balancing.balance, 10000.0)
        original = lines.filtered(lambda l: l.account_id == self.account_recv and l.balance < 0)
        fees = lines.filtered(lambda l: l.account_id == self.account_expense)
        self.assertEqual(original.balance, -9500.0)
        self.assertEqual(fees.balance, -500.0)
        self.assertAlmostEqual(sum(lines.mapped('balance')), 0.0, places=4)
        # the source item must be reconciled either way
        line.invalidate_recordset()
        self.assertTrue(line.reconciled)

    # ==================================================================
    # 5 - analytic / cost center
    # ==================================================================
    def test_05_analytic_on_bank_fees_line(self):
        line = self._create_source()
        wizard = self._create_wizard(line, fees=500.0)
        wizard.action_post()

        fee_lines = self._new_lines(wizard).filtered(
            lambda l: l.account_id == self.account_expense)
        self.assertEqual(len(fee_lines), 1)
        self.assertEqual(fee_lines.analytic_distribution, {str(self.analytic_account.id): 100.0})
        # the distribution is turned into real analytic entries when posted
        self.assertTrue(
            fee_lines.analytic_line_ids,
            'the cost center must produce analytic entries on the posted move',
        )
        # and only there
        other = self._new_lines(wizard) - fee_lines
        self.assertFalse(any(other.mapped('analytic_distribution')))

    # ==================================================================
    # 6 - automatic reconciliation
    # ==================================================================
    def test_06_reconciled_automatically(self):
        line = self._create_source()
        wizard = self._create_wizard(line, fees=500.0)
        result = wizard.action_post()

        line.invalidate_recordset()
        self.assertEqual(line.amount_residual, 0.0)
        self.assertTrue(line.reconciled)
        self.assertTrue(line.full_reconcile_id)
        self.assertTrue(wizard.move_id)
        self.assertEqual(wizard.move_id.state, 'posted')
        # the return is a calm notification + dialog close (never a
        # navigation: navigating while the reconcile list behind the dialog
        # reloads orphans its in-flight reads -> "Component is destroyed")
        self.assertEqual(result['type'], 'ir.actions.client')
        self.assertEqual(result['tag'], 'display_notification')
        self.assertEqual(
            result['params']['next']['type'], 'ir.actions.act_window_close')
        self.assertIn(wizard.move_id.display_name, result['params']['message'])

        # it must disappear from "Journal Items to Reconcile"
        domain = [
            ('display_type', 'not in', ('line_section', 'line_subsection', 'line_note')),
            ('account_id.reconcile', '=', True),
            ('full_reconcile_id', '=', False),
            ('parent_state', '!=', 'cancel'),
        ]
        self.assertNotIn(line.id, self.env['account.move.line'].search(domain).ids)

    def test_07_standard_reconcile_still_works(self):
        """ The standard Reconcile button must keep working untouched. """
        line = self._create_source()
        counterpart = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.journal_misc.id,
            'date': fields.Date.today(),
            'line_ids': [
                Command.create({'name': 'payment', 'account_id': self.account_revenue.id,
                                'partner_id': self.partner.id, 'debit': 10000.0, 'credit': 0.0}),
                Command.create({'name': 'payment', 'account_id': self.account_recv.id,
                                'partner_id': self.partner.id, 'debit': 0.0, 'credit': 10000.0}),
            ],
        })
        counterpart.action_post()
        pay_line = counterpart.line_ids.filtered(lambda l: l.account_id == self.account_recv)

        (line + pay_line).action_reconcile()
        line.invalidate_recordset()
        self.assertTrue(line.reconciled)

    # ==================================================================
    # 7 - already reconciled item
    # ==================================================================
    def test_08_already_reconciled_item_is_blocked(self):
        line = self._create_source()
        opposite = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.journal_misc.id,
            'date': fields.Date.today(),
            'line_ids': [
                Command.create({'name': 'x', 'account_id': self.account_revenue.id,
                                'partner_id': self.partner.id, 'debit': 10000.0, 'credit': 0.0}),
                Command.create({'name': 'x', 'account_id': self.account_recv.id,
                                'partner_id': self.partner.id, 'debit': 0.0, 'credit': 10000.0}),
            ],
        })
        opposite.action_post()
        opp_line = opposite.line_ids.filtered(lambda l: l.account_id == self.account_recv)
        (line + opp_line).reconcile()
        line.invalidate_recordset()
        self.assertTrue(line.reconciled)

        with self.assertRaises(UserError) as ctx:
            line.action_bank_fees_allocation()
        self.assertIn('already been reconciled', str(ctx.exception))

        with self.assertRaises(ValidationError) as ctx:
            self._create_wizard(line, fees=500.0)
        self.assertIn('already been reconciled', str(ctx.exception))

    def test_09_revalidated_right_before_posting(self):
        """ The journal item is re-checked when Post is pressed. """
        line = self._create_source()
        wizard = self._create_wizard(line, fees=500.0)
        # somebody reconciles the item between the opening and the click
        opposite = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.journal_misc.id,
            'date': fields.Date.today(),
            'line_ids': [
                Command.create({'name': 'x', 'account_id': self.account_revenue.id,
                                'partner_id': self.partner.id, 'debit': 10000.0, 'credit': 0.0}),
                Command.create({'name': 'x', 'account_id': self.account_recv.id,
                                'partner_id': self.partner.id, 'debit': 0.0, 'credit': 10000.0}),
            ],
        })
        opposite.action_post()
        opp_line = opposite.line_ids.filtered(lambda l: l.account_id == self.account_recv)
        (line + opp_line).reconcile()

        moves_before = self.env['account.move'].search_count([])
        with self.assertRaises(ValidationError):
            wizard.action_post()
        # nothing was created
        self.assertFalse(wizard.move_id)
        self.assertEqual(self.env['account.move'].search_count([]), moves_before)

    # ==================================================================
    # 8 - invalid (non expense) account
    # ==================================================================
    def test_10_bank_fees_account_must_be_expense(self):
        line = self._create_source()
        wizard = self._create_wizard(line, fees=500.0)
        self.assertNotIn(self.account_revenue.account_type, EXPENSE_ACCOUNT_TYPES)
        with self.assertRaises(ValidationError) as ctx:
            wizard.fees_account_id = self.account_revenue
        self.assertIn('must be an Expense account', str(ctx.exception))

        # and the required account cannot be empty
        with self.assertRaises(ValidationError) as ctx:
            wizard.fees_account_id = False
        self.assertIn('Bank Fees Account is required', str(ctx.exception))

    # ==================================================================
    # 9 - amounts validation
    # ==================================================================
    def test_11_amount_mismatch_is_blocked(self):
        line = self._create_source()
        wizard = self._create_wizard(line, fees=500.0)

        # original amount bigger than the amount available -> must fail
        with self.assertRaises(ValidationError) as ctx:
            wizard.original_amount = 12000.0
        msg = str(ctx.exception).lower()
        self.assertTrue('cannot be negative' in msg or 'do not match' in msg, msg)

        # fees bigger than the amount available -> must fail too
        with self.assertRaises(ValidationError):
            wizard.fees_amount = 12000.0

    def test_12_negative_amounts_are_blocked(self):
        line = self._create_source()
        wizard = self._create_wizard(line, fees=500.0)
        with self.assertRaises(ValidationError) as ctx:
            wizard.original_amount = -100.0
        self.assertIn('cannot be negative', str(ctx.exception).lower())

        with self.assertRaises(ValidationError):
            wizard.fees_amount = -100.0

    def test_13_cost_center_is_required(self):
        line = self._create_source()
        with self.assertRaises(ValidationError) as ctx:
            self._create_wizard(line, fees=500.0, analytic=False)
        self.assertIn('Cost Center is required', str(ctx.exception))

    def test_14_total_is_not_editable(self):
        """ 'Total Amount' comes from the journal item and cannot be edited. """
        line = self._create_source()
        wizard = self._create_wizard(line, fees=500.0)
        field = self.env['bank.fees.allocation.wizard']._fields['total_amount']
        self.assertFalse(field.inverse, 'total_amount must not have an inverse')
        self.assertTrue(field.readonly, 'total_amount must be read-only')
        self.assertEqual(wizard.total_amount, abs(line.amount_residual))

    # ==================================================================
    # 10 - multi currency
    # ==================================================================
    def test_15_multi_currency(self):
        foreign = self.env.ref('base.EUR')
        if foreign == self.currency:
            foreign = self.env.ref('base.USD')
        foreign = foreign.with_context(active_test=False)
        foreign.write({'active': True})

        amount = 10000.0
        line = self._create_source(amount=amount, currency=foreign)
        self.assertEqual(line.currency_id, foreign)
        self.assertNotEqual(line.company_currency_id, foreign)

        wizard = self._create_wizard(line, fees=500.0)
        self.assertEqual(wizard.reco_currency_id, foreign)
        self.assertEqual(wizard.total_amount, amount)
        self.assertEqual(wizard.original_amount, 9500.0)

        wizard.action_post()
        lines = self._new_lines(wizard)

        for l in lines:
            self.assertEqual(l.currency_id, foreign, 'entry must keep the item currency')
        self.assertAlmostEqual(sum(lines.mapped('amount_currency')), 0.0, places=4)
        self.assertAlmostEqual(sum(lines.mapped('balance')), 0.0, places=4)

        # rounding must not break the reconciliation
        line.invalidate_recordset()
        self.assertEqual(line.amount_residual_currency, 0.0)
        self.assertTrue(line.reconciled)
        self.assertTrue(line.full_reconcile_id)

    # ==================================================================
    # 11 - access rights
    # ==================================================================
    def test_16_access_rights_are_not_bypassed(self):
        line = self._create_source()
        simple_user = self.env['res.users'].create({
            'name': 'No Accounting Rights',
            'login': 'bank_fees_no_rights',
            'group_ids': [Command.link(self.env.ref('base.group_user').id)],
        })
        with self.assertRaises(AccessError):
            self.env['bank.fees.allocation.wizard'].with_user(simple_user).create({
                'line_ids': [Command.set([line.id])],
                'fees_account_id': self.account_expense.id,
                'fees_amount': 500.0,
                'analytic_distribution': self.analytic_distribution,
            })
        # posting a journal entry is not possible either
        with self.assertRaises(AccessError):
            self.env['account.move'].with_user(simple_user).create({
                'move_type': 'entry',
                'journal_id': self.journal_misc.id,
                'line_ids': [Command.create({'name': 'x', 'account_id': self.account_expense.id,
                                             'debit': 1.0, 'credit': 0.0}),
                             Command.create({'name': 'x', 'account_id': self.account_revenue.id,
                                             'debit': 0.0, 'credit': 1.0})],
            })

    def test_17_move_is_balanced_and_posted(self):
        line = self._create_source()
        wizard = self._create_wizard(line, fees=500.0)
        wizard.action_post()
        move = wizard.move_id

        self.assertEqual(move.state, 'posted')
        self.assertEqual(move.move_type, 'entry')
        self.assertEqual(move.journal_id, wizard.journal_id)
        self.assertEqual(move.journal_id.type, 'general')
        self.assertAlmostEqual(sum(move.line_ids.mapped('debit')),
                               sum(move.line_ids.mapped('credit')), places=4)
        # the source item is referenced for traceability, it is never modified
        self.assertEqual(move.ref, line.move_id.name)
        self.assertEqual(line.move_id.state, 'posted')

    # ==================================================================
    # 12 - several journal items -> a single journal entry
    # ==================================================================
    def _other_reconcilable_account(self):
        return self.env['account.account'].create({
            'name': 'Bank Fees Other Reconcilable',
            'code': 'CF9991',
            'account_type': 'asset_current',
            'reconcile': True,
            'company_ids': [Command.set([self.company.id])],
        })

    def test_18_multi_selection_creates_one_single_entry(self):
        """ Selecting several items and pressing 'Closing Fees' once creates
        exactly one journal entry with exactly three lines. """
        lines = self.env['account.move.line']
        for amount in (3000.0, 7000.0, 5000.0):
            lines |= self._create_source(amount=amount)
        self.assertEqual(len(lines), 3)

        wizard = self._create_wizard(lines, fees=500.0)
        self.assertEqual(len(wizard.line_ids), 3)
        self.assertFalse(wizard.unlink_account_id,
                         'Unlink Account must start empty')
        self.assertEqual(wizard.source_account_id, self.account_recv)
        self.assertEqual(wizard.total_amount, 15000.0)
        self.assertEqual(wizard.original_amount, 14500.0)
        self.assertEqual(wizard.fees_amount, 500.0)
        self.assertEqual(wizard.reconciled_total, 15000.0)

        moves_before = self.env['account.move'].search_count([])
        wizard.action_post()
        self.assertEqual(self.env['account.move'].search_count([]), moves_before + 1,
                         'the multi selection must produce exactly one journal entry')

        entry = wizard.move_id
        self.assertEqual(entry.state, 'posted')
        self.assertEqual(len(entry.line_ids), 3, 'the entry must still have exactly 3 lines')

        balancing = entry.line_ids.filtered(lambda l: l.balance < 0)
        remaining = entry.line_ids.filtered(
            lambda l: l.account_id == self.account_recv and l.balance > 0)
        fees = entry.line_ids.filtered(lambda l: l.account_id == self.account_expense)
        self.assertEqual(len(balancing), 1)
        self.assertEqual(balancing.balance, -15000.0)
        self.assertEqual(remaining.balance, 14500.0)
        self.assertEqual(fees.balance, 500.0)
        self.assertAlmostEqual(sum(entry.line_ids.mapped('balance')), 0.0, places=4)

        # every selected item is reconciled, none of them was modified
        lines.invalidate_recordset()
        for source in lines:
            self.assertEqual(source.amount_residual, 0.0)
            self.assertTrue(source.reconciled)
            self.assertTrue(source.full_reconcile_id)
            self.assertEqual(source.move_id.state, 'posted')
            self.assertNotEqual(source.move_id, entry)

    def test_19_multi_selection_amounts_link_both_directions(self):
        """ The fee amount covers the whole selection. """
        lines = self._create_source(amount=4000.0) + self._create_source(amount=6000.0)
        wizard = self._create_wizard(lines, fees=0.0)
        self.assertEqual(wizard.total_amount, 10000.0)
        self.assertEqual(wizard.original_amount, 10000.0)
        wizard.original_amount = 9900.0
        self.assertEqual(wizard.fees_amount, 100.0)
        self.assertEqual(wizard.reconciled_total, 10000.0)

    def test_20_multi_selection_different_accounts_is_blocked(self):
        """ Only items of the same account can be handled together. """
        other = self._other_reconcilable_account()
        lines = self._create_source(amount=1000.0) + \
            self._create_source(amount=2000.0, account=other)
        with self.assertRaises(UserError) as ctx:
            lines.action_bank_fees_allocation()
        self.assertIn('same account', str(ctx.exception))

        with self.assertRaises(ValidationError) as ctx:
            self._create_wizard(lines, fees=500.0)
        self.assertIn('same account', str(ctx.exception))

    def test_21_multi_selection_empty_is_blocked(self):
        with self.assertRaises(UserError) as ctx:
            self.env['account.move.line'].action_bank_fees_allocation()
        self.assertIn('at least one journal item', str(ctx.exception))

        # a wizard whose selection becomes empty must be blocked too
        wizard = self._create_wizard(self._create_source())
        with self.assertRaises(ValidationError) as ctx:
            wizard.line_ids = [Command.clear()]
        self.assertIn('at least one journal item', str(ctx.exception))

    def test_22_multi_selection_mixed_currencies_is_blocked(self):
        foreign = self.env.ref('base.EUR')
        if foreign == self.currency:
            foreign = self.env.ref('base.USD')
        foreign = foreign.with_context(active_test=False)
        foreign.write({'active': True})

        lines = self._create_source(amount=1000.0) + \
            self._create_source(amount=2000.0, currency=foreign)
        with self.assertRaises(UserError) as ctx:
            lines.action_bank_fees_allocation()
        self.assertIn('same currency', str(ctx.exception))

    def test_23_multi_selection_mixed_direction(self):
        """ A debit item and a credit item on the same account: the selection
        is handled through its NET residual, and all of them are reconciled. """
        debit_line = self._create_source(amount=10000.0)
        credit_line = self._create_source(amount=4000.0, credit=True)
        lines = debit_line + credit_line

        wizard = self._create_wizard(lines, fees=500.0)
        self.assertEqual(wizard.total_amount, 6000.0)
        self.assertEqual(wizard.original_amount, 5500.0)

        wizard.action_post()
        entry = wizard.move_id
        self.assertEqual(len(entry.line_ids), 3)
        self.assertAlmostEqual(sum(entry.line_ids.mapped('balance')), 0.0, places=4)

        lines.invalidate_recordset()
        for source in lines:
            self.assertEqual(source.amount_residual, 0.0)
            self.assertTrue(source.reconciled)
            self.assertTrue(source.full_reconcile_id)

    def test_24_multi_selection_different_partners(self):
        """ When the selection mixes partners the new entry carries no partner,
        exactly like Odoo's own write-off lines. """
        other_partner = self.env['res.partner'].create({'name': 'Bank Fees Partner 2'})
        lines = self._create_source(amount=1000.0) + \
            self._create_source(amount=2000.0, partner=other_partner)

        wizard = self._create_wizard(lines, fees=500.0)
        wizard.action_post()
        entry = wizard.move_id

        self.assertFalse(any(entry.line_ids.mapped('partner_id')),
                         'mixed partners -> no partner on the generated lines')
        lines.invalidate_recordset()
        for source in lines:
            self.assertEqual(source.amount_residual, 0.0)
            self.assertTrue(source.reconciled)

    def test_25_multi_selection_foreign_currency(self):
        foreign = self.env.ref('base.EUR')
        if foreign == self.currency:
            foreign = self.env.ref('base.USD')
        foreign = foreign.with_context(active_test=False)
        foreign.write({'active': True})

        lines = self._create_source(amount=1000.0, currency=foreign) + \
            self._create_source(amount=2000.0, currency=foreign)
        wizard = self._create_wizard(lines, fees=100.0)
        self.assertEqual(wizard.reco_currency_id, foreign)
        self.assertEqual(wizard.total_amount, 3000.0)
        self.assertEqual(wizard.original_amount, 2900.0)

        wizard.action_post()
        entry = wizard.move_id
        self.assertEqual(len(entry.line_ids), 3)
        for line in entry.line_ids:
            self.assertEqual(line.currency_id, foreign)
        self.assertAlmostEqual(sum(entry.line_ids.mapped('amount_currency')), 0.0, places=4)
        self.assertAlmostEqual(sum(entry.line_ids.mapped('balance')), 0.0, places=4)

        lines.invalidate_recordset()
        for source in lines:
            self.assertEqual(source.amount_residual_currency, 0.0)
            self.assertEqual(source.amount_residual, 0.0)
            self.assertTrue(source.reconciled)
            self.assertTrue(source.full_reconcile_id)

    def test_26_single_selection_is_a_special_case_of_multi(self):
        """ One item still behaves exactly as before the multi-selection. """
        line = self._create_source()
        wizard = self._create_wizard(line, fees=500.0)
        self.assertEqual(len(wizard.line_ids), 1)
        self.assertEqual(wizard.total_amount, 10000.0)
        wizard.action_post()
        self.assertEqual(len(wizard.move_id.line_ids), 3)
        line.invalidate_recordset()
        self.assertTrue(line.reconciled)

    # ==================================================================
    # 13 - Unlink Account (editable) + Cost Center visibility
    # ==================================================================
    def _bank_target_account(self):
        """ A *Bank and Cash* account: the only kind the Unlink Account
        dropdown is allowed to offer. """
        Account = self.env['account.account']
        account = Account.search([
            ('account_type', '=', 'asset_cash'),
            ('company_ids', 'parent_of', self.company.id),
        ], limit=1)
        if account:
            return account
        # no Bank and Cash account yet: create one.  ``chart_template_load``
        # only skips the automatic journal creation, nothing else.
        return Account.with_context(chart_template_load=True).create({
            'name': 'Bank Fees Unlink Bank',
            'code': 'CF9992',
            'account_type': 'asset_cash',
            'reconcile': True,
            'company_ids': [Command.set([self.company.id])],
        })

    def test_27_unlink_account_starts_empty_and_offers_bank_and_cash_only(self):
        line = self._create_source()
        wizard = self._create_wizard(line, fees=500.0)
        self.assertEqual(wizard.source_account_id, self.account_recv)
        self.assertFalse(wizard.unlink_account_id,
                         'Unlink Account must start EMPTY so nobody changes it by mistake')
        # still editable when the accountant really wants to unload it elsewhere
        field = self.env['bank.fees.allocation.wizard']._fields['unlink_account_id']
        self.assertFalse(field.readonly, 'Unlink Account must be editable')
        # only Bank and Cash accounts are offered in the dropdown
        self.assertIn('asset_cash', str(field._description_domain(self.env)),
                      'only Bank and Cash accounts may be offered')
        # and the field is shown in green, not marked required
        arch = self.env['bank.fees.allocation.wizard'].get_view(
            self.env.ref('bank_fees_allocation.bank_fees_wizard_form').id, 'form',
        )['arch']
        node = re.search(r'<field[^>]*name="unlink_account_id"[^>]*>', arch)
        self.assertIsNotNone(node)
        self.assertIn('class="text-success"', node.group(0),
                      'Unlink Account must be shown in green')
        self.assertNotIn('required="1"', node.group(0),
                         'Unlink Account must be left empty by default')

        # ... and, left empty, the remainder simply stays on the source account
        wizard.action_post()
        entry = wizard.move_id
        self.assertEqual(entry.state, 'posted')
        self.assertEqual(len(entry.line_ids), 3)
        on_source = entry.line_ids.filtered(lambda l: l.account_id == self.account_recv)
        self.assertEqual(len(on_source), 2,
                         'empty Unlink Account => reconciling line + remainder stay on the source account')
        self.assertEqual(sum(on_source.mapped('balance')), -500.0)
        self.assertAlmostEqual(sum(entry.line_ids.mapped('balance')), 0.0, places=4)

    def test_28_unlink_account_can_be_another_account(self):
        """ The reconciling line always stays on the SOURCE account (Odoo only
        reconciles items of one account), while the remaining amount is
        unloaded on the account the user picked. """
        target = self._bank_target_account()
        line = self._create_source(amount=10000.0)
        wizard = self._create_wizard(line, fees=500.0)
        wizard.unlink_account_id = target
        self.assertEqual(wizard.unlink_account_id, target)
        wizard.action_post()

        entry = wizard.move_id
        self.assertEqual(entry.state, 'posted')
        self.assertEqual(len(entry.line_ids), 3)

        reconciling = entry.line_ids.filtered(lambda l: l.account_id == self.account_recv)
        self.assertEqual(len(reconciling), 1, 'the reconciling line stays on the source account')
        self.assertEqual(reconciling.balance, -10000.0)

        remaining = entry.line_ids.filtered(lambda l: l.account_id == target)
        self.assertEqual(len(remaining), 1, 'the remaining amount goes to the Unlink Account')
        self.assertEqual(remaining.balance, 9500.0)

        fees = entry.line_ids.filtered(lambda l: l.account_id == self.account_expense)
        self.assertEqual(len(fees), 1)
        self.assertEqual(fees.balance, 500.0)
        self.assertAlmostEqual(sum(entry.line_ids.mapped('balance')), 0.0, places=4)

        # the source item is fully reconciled anyway
        line.invalidate_recordset()
        self.assertEqual(line.amount_residual, 0.0)
        self.assertTrue(line.reconciled)
        self.assertTrue(line.full_reconcile_id)

    def test_29_unlink_account_is_optional_but_must_be_bank_and_cash(self):
        line = self._create_source()
        wizard = self._create_wizard(line, fees=500.0)

        # 1) empty is allowed (and it is the default): the remainder simply
        #    stays on the source account
        wizard.unlink_account_id = False
        self.assertFalse(wizard.unlink_account_id)

        # 2) a non Bank and Cash account is rejected server side as well
        with self.assertRaises(ValidationError) as ctx:
            wizard.unlink_account_id = self.account_expense
        self.assertIn('Bank and Cash', str(ctx.exception))

        # 3) a Bank and Cash account is accepted
        wizard.unlink_account_id = self._bank_target_account()
        self.assertTrue(wizard.unlink_account_id)

    def test_30_cost_center_is_visible_in_the_created_entry(self):
        """ The cost center is stored on the Bank Fees line; make sure the
        entry exposes it under the very same label as the wizard. """
        line = self._create_source()
        wizard = self._create_wizard(line, fees=500.0)
        wizard.action_post()
        fee_line = wizard.move_id.line_ids.filtered(
            lambda l: l.account_id == self.account_expense)
        self.assertEqual(fee_line.analytic_distribution,
                         {str(self.analytic_account.id): 100.0})

        form_arch = self.env['account.move'].get_view(
            self.env.ref('account.view_move_form').id, 'form')['arch']
        nodes = re.findall(r'<field[^>]*name="analytic_distribution"[^>]*>', form_arch)
        self.assertTrue(any('Cost Center' in node for node in nodes),
                        'the Journal Items tab must expose the Cost Center column')
        self.assertNotIn('analytic.group_analytic_accounting', form_arch)

        list_arch = self.env['account.move.line'].get_view(
            self.env.ref('account.view_move_line_tree').id, 'list')['arch']
        nodes = re.findall(r'<field[^>]*name="analytic_distribution"[^>]*>', list_arch)
        self.assertEqual(len(nodes), 1)
        self.assertIn('Cost Center', nodes[0])
        self.assertIn('optional="show"', nodes[0])
        self.assertNotIn('analytic.group_analytic_accounting', nodes[0])

    def test_31_wizard_form_shaped_like_the_standard_reconcile_wizard(self):
        arch = self.env['bank.fees.allocation.wizard'].get_view(
            self.env.ref('bank_fees_allocation.bank_fees_wizard_form').id, 'form',
        )['arch']
        # same skeleton as account_accountant.view_account_reconcile_wizard
        self.assertIn('o_td_label', arch, 'the Amount row must look like the standard wizard')
        self.assertIn('<footer', arch, 'actions must sit in the footer')
        self.assertIn('name="action_post" type="object"', arch)
        self.assertIn('special="cancel"', arch)
        # two columns: accounts on the left, amounts + cost center on the right
        self.assertIn('string="Cost Center"', arch)
        # ``string`` is stripped from the arch when it equals the field label
        self.assertIn('name="unlink_account_id"', arch)
        self.assertEqual(
            self.env['bank.fees.allocation.wizard']._fields['unlink_account_id'].string,
            'Unlink Account',
        )
        # colour coding: green = amount that stays, red = bank fees
        node = re.search(r'<field[^>]*name="original_amount"[^>]*>', arch)
        self.assertIsNotNone(node)
        self.assertIn('class="text-success"', node.group(0))
        node = re.search(r'<field[^>]*name="fees_amount"[^>]*>', arch)
        self.assertIsNotNone(node)
        self.assertIn('class="text-danger"', node.group(0))

    def test_32_unlink_amount_feeds_bank_fees_while_typing(self):
        """ Typing the Unlink Account Amount must push the remainder into the
        Bank Fees Amount *live* (Odoo does not run field inverses during an
        onchange, only ``@api.onchange`` methods run). Driven through the very
        same ``Form`` helper the web client uses. """
        line = self._create_source()
        wizard = self._create_wizard(line, fees=500.0)

        with Form(wizard,
                  view='bank_fees_allocation.bank_fees_wizard_form') as form:
            self.assertEqual(form.total_amount, 10000.0)
            self.assertEqual(form.original_amount, 9500.0)
            self.assertEqual(form.fees_amount, 500.0)

            # the user types the Unlink Account Amount
            form.original_amount = 8000.0
            self.assertEqual(
                form.fees_amount, 2000.0,
                'the remainder must be pushed into Bank Fees while typing',
            )
            self.assertEqual(form.reconciled_total, 10000.0)

            # and the other direction still works
            form.fees_amount = 1500.0
            self.assertEqual(form.original_amount, 8500.0)

        # saved on the record
        self.assertEqual(wizard.original_amount, 8500.0)
        self.assertEqual(wizard.fees_amount, 1500.0)

    # ==================================================================
    # 14 - The accounting date is the user's choice (never moved silently)
    # ==================================================================
    def test_33_locked_accounting_date_is_refused_not_moved(self):
        """ When a lock date blocks the date picked in the wizard, the wizard
        must complain instead of quietly posting the entry on another date. """
        line = self._create_source()
        wizard = self._create_wizard(line, fees=500.0)
        chosen = wizard.date
        self.assertTrue(chosen, 'the wizard must propose an accounting date')

        # block exactly that date
        self.company.write({'fiscalyear_lock_date': chosen})

        # 1) the wizard never moves the chosen date on its own
        self.assertEqual(wizard.date, chosen,
                         'the chosen date must never be changed silently')

        # 2) it explains why the date is refused
        with self.assertRaises(ValidationError) as ctx:
            wizard._check_accounting_date()
        message = str(ctx.exception)
        self.assertIn('Invalid journal entry date', message)
        self.assertIn(str(chosen), message)
        self.assertIn('lock', message.lower())

        # 3) pressing Post is refused as well, and nothing gets created
        moves_before = self.env['account.move'].search_count([])
        with self.assertRaises(ValidationError):
            wizard.action_post()
        self.assertFalse(wizard.move_id, 'no journal entry may be created')
        self.assertEqual(self.env['account.move'].search_count([]), moves_before)

        # 4) unlocking lets the very same date through, used as picked
        self.company.write({'fiscalyear_lock_date': False})
        wizard.action_post()
        self.assertEqual(wizard.move_id.date, chosen,
                         'the entry must be dated exactly as chosen')

    # ==================================================================
    # 17 - a zero Unlink Account Amount must still balance in foreign currency
    # ==================================================================
    def test_34_unlink_zero_in_foreign_currency_still_balances(self):
        """ Unlink Account Amount = 0 (everything goes to Bank Fees) is a legal
        input.  In a foreign currency the fees are converted at the entry date
        while the source item keeps its historical rate: the "Unlink" line then
        carries a company balance but a zero amount_currency, and dropping it
        would leave the entry unbalanced. """
        foreign = self.env.ref('base.EUR')
        if foreign == self.currency:
            foreign = self.env.ref('base.USD')
        foreign = foreign.with_context(active_test=False)
        foreign.write({'active': True})

        line = self._create_source(amount=10000.0, currency=foreign)
        wizard = self._create_wizard(line, fees=0.0)
        wizard.unlink_account_id = self._bank_target_account()

        # Move the entry to a date we control and force a different rate on
        # that very date: converting the fees can no longer match the balance
        # stored on the source item.
        wizard.date = fields.Date.add(fields.Date.today(), days=30)
        existing = self.env['res.currency.rate'].search(
            [('currency_id', '=', foreign.id), ('name', '<=', wizard.date)],
            order='name desc', limit=1,
        )
        base = existing.rate if existing and existing.rate else 1.0
        self.env['res.currency.rate'].create({
            'currency_id': foreign.id,
            'name': wizard.date,
            'company_id': self.company.id,
            'rate': base * 1.5,
        })
        self.env.invalidate_all()

        # everything goes to the bank fees account
        wizard.original_amount = 0.0
        self.assertEqual(wizard.original_amount, 0.0)
        self.assertEqual(wizard.fees_amount, wizard.total_amount)
        self.assertEqual(wizard.fees_amount, 10000.0)

        wizard.action_post()
        entry = wizard.move_id
        self.assertEqual(entry.state, 'posted')
        self.assertEqual(entry.date, wizard.date)

        # the entry balances even though the Unlink line is worth 0 in EUR
        self.assertEqual(len(entry.line_ids), 3,
                         'the zero-amount Unlink line must be kept, not dropped')
        self.assertAlmostEqual(sum(entry.line_ids.mapped('balance')), 0.0, places=4)
        self.assertAlmostEqual(sum(entry.line_ids.mapped('amount_currency')), 0.0, places=4)

        # and the source item is cleared anyway
        line.invalidate_recordset()
        self.assertTrue(line.reconciled)
        self.assertTrue(line.full_reconcile_id)

    # ==================================================================
    # 18 - changing the journal must never move the picked date
    # ==================================================================
    def test_35_changing_the_journal_never_moves_the_picked_date(self):
        """ ``_compute_date`` must not depend on ``journal_id``: picking
        another journal would otherwise silently overwrite the date the user
        already chose, which is exactly the silent change v20.0.1.6.0 forbids. """
        line = self._create_source()
        wizard = self._create_wizard(line, fees=500.0)
        default_date = wizard.date
        self.assertTrue(default_date, 'the wizard must propose an accounting date')

        # the user picks his own date...
        chosen = fields.Date.add(default_date, days=3)
        wizard.date = chosen
        self.assertEqual(wizard.date, chosen)

        # ... and only then changes the journal
        other_journal = self.env['account.journal'].create({
            'name': 'Bank Fees Second Misc',
            'code': 'CFM2',
            'type': 'general',
            'company_id': self.company.id,
        })
        wizard.journal_id = other_journal
        self.assertEqual(wizard.journal_id, other_journal)
        self.assertEqual(wizard.date, chosen,
                         'changing the journal must never move the picked date')

        # the chosen date survives all the way into the posted entry
        wizard.action_post()
        self.assertEqual(wizard.move_id.date, chosen,
                         'the entry must be dated exactly as chosen')

    # ==================================================================
    # 19 - the wizard never posts twice
    # ==================================================================
    def test_36_posting_twice_is_refused_before_anything_happens(self):
        """ ``action_post`` remembers the entry it created: pressing Post
        again is refused with a clear message (instead of the misleading
        "the journal item has already been reconciled") and no second journal
        entry is ever created. """
        line = self._create_source()
        wizard = self._create_wizard(line, fees=500.0)
        wizard.action_post()
        first = wizard.move_id
        self.assertTrue(first)
        self.assertEqual(first.state, 'posted')

        moves_before = self.env['account.move'].search_count([])
        with self.assertRaises(ValidationError) as ctx:
            wizard.action_post()
        message = str(ctx.exception)
        self.assertIn('already been posted', message)
        self.assertIn(first.display_name, message)

        self.assertEqual(wizard.move_id, first, 'the wizard must keep its entry')
        self.assertEqual(self.env['account.move'].search_count([]), moves_before,
                         'a second journal entry must never be created')

        # the source item is still reconciled, by the first entry only
        line.invalidate_recordset()
        self.assertTrue(line.reconciled)
        self.assertTrue(line.full_reconcile_id)

    # ==================================================================
    # 20 - zero fees need no fees account and no cost center (new in
    #      bank_fees_allocation: the requirement is conditional)
    # ==================================================================
    def test_37_fees_zero_needs_no_fees_configuration(self):
        """ Bank Fees Amount = 0: no Bank Fees account and no Cost Center are
        required — the fees line is worth nothing in both currencies and is
        dropped, so the entry carries only the reconciling line and the
        remaining amount line, and the source item is still fully cleared. """
        line = self._create_source()
        wizard = self.env['bank.fees.allocation.wizard'].create({
            'line_ids': [Command.set(line.ids)],
            'fees_amount': 0.0,
            'analytic_distribution': False,
            # deliberately no fees_account_id at all
        })
        self.assertEqual(wizard.fees_amount, 0.0)
        self.assertEqual(wizard.original_amount, 10000.0)
        self.assertFalse(wizard.fees_account_id)

        wizard.action_post()
        entry = wizard.move_id
        self.assertEqual(entry.state, 'posted')
        self.assertEqual(len(entry.line_ids), 2,
                         'zero fees -> the fees line is dropped, two lines remain')
        self.assertAlmostEqual(sum(entry.line_ids.mapped('balance')), 0.0, places=4)
        self.assertFalse(any(entry.line_ids.mapped('analytic_distribution')))

        # the source item is still fully reconciled
        line.invalidate_recordset()
        self.assertEqual(line.amount_residual, 0.0)
        self.assertTrue(line.reconciled)
        self.assertTrue(line.full_reconcile_id)

    def test_38_fees_view_requires_configuration_only_when_fees(self):
        """ The wizard form mirrors the server rule: the fees account and the
        cost center are required exactly when the Bank Fees Amount is not
        zero (dynamic required in the view). """
        raw_arch = self.env.ref('bank_fees_allocation.bank_fees_wizard_form').arch
        fees_node = re.search(r'<field[^>]*name="fees_account_id"[^>]*>', raw_arch).group(0)
        analytic_node = re.search(
            r'<field[^>]*name="analytic_distribution"[^>]*>', raw_arch).group(0)
        self.assertIn('required="fees_amount != 0"', fees_node)
        self.assertIn('required="fees_amount != 0"', analytic_node)
        # ... and the original amount stays required in every case
        original_node = re.search(r'<field[^>]*name="original_amount"[^>]*>', raw_arch).group(0)
        self.assertIn('required="1"', original_node)

    def test_39_company_default_prefills_the_wizard(self):
        """ Settings > Invoicing > Closing Fees: the company default Bank
        Fees Account pre-fills the wizard on the button path, where the
        selected journal items travel through ``default_line_ids``. """
        self.company.bank_fees_account_id = self.account_expense
        line = self._create_source()
        wizard = self.env['bank.fees.allocation.wizard'].with_context(
            default_line_ids=[Command.set(line.ids)]).create({
            'line_ids': [Command.set(line.ids)],
            'fees_amount': 500.0,
            'analytic_distribution': self.analytic_distribution,
        })
        self.assertEqual(wizard.fees_account_id, self.account_expense,
                         'the company default must pre-fill the wizard')

        wizard.action_post()
        self.assertTrue(wizard.move_id)
        fee_lines = wizard.move_id.line_ids.filtered(
            lambda l: l.account_id == self.account_expense)
        self.assertEqual(len(fee_lines), 1)
        self.assertAlmostEqual(fee_lines.balance, 500.0, places=4)

    def test_40_no_company_default_leaves_the_wizard_empty(self):
        """ Without a company default the wizard behaves exactly as before:
        with zero fees the fees account is not required and stays empty. """
        line = self._create_source()
        wizard = self.env['bank.fees.allocation.wizard'].with_context(
            default_line_ids=[Command.set(line.ids)]).create({
            'line_ids': [Command.set(line.ids)],
            'fees_amount': 0.0,
            'analytic_distribution': False,
        })
        self.assertFalse(wizard.fees_account_id)

        # and a positive fees amount still demands an account (the company
        # default is empty here, so the constraint fires on the create)
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.env['bank.fees.allocation.wizard'].with_context(
                default_line_ids=[Command.set(line.ids)]).create({
                'line_ids': [Command.set(line.ids)],
                'fees_amount': 500.0,
                'analytic_distribution': self.analytic_distribution,
            })

