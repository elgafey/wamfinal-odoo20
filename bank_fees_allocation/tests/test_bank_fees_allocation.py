# -*- coding: utf-8 -*-
"""Tests of the ``bank_fees_allocation`` module.

The tests are self-contained: they create their own accounts, their own
journal and their own journal items, so they do not depend on any chart
template and they run the same way on the Community and on the Enterprise
edition.
"""

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged, new_test_user


@tagged('post_install', '-at_install')
class TestBankFeesAllocation(TransactionCase):
    """ Test the whole flow of the module. """

    @classmethod
    def setUpClass(cls):
        """ Create the accounting data the tests need. """
        super().setUpClass()

        cls.company = cls.env.company
        cls.currency = cls.company.currency_id
        cls.analytic_plan = cls.env['account.analytic.plan'].search([], limit=1)
        cls.analytic_account = cls.env['account.analytic.account'].create({
            'name': 'Branch Riyadh',
            'company_id': cls.company.id,
            'plan_id': cls.analytic_plan.id,
        })

        # ---- accounts -------------------------------------------------
        cls.card_account = cls._create_account('Visa Clearing', 'asset_current', reconcile=True)
        cls.card_account_2 = cls._create_account('Mastercard Clearing', 'asset_current', reconcile=True)
        cls.fee_account = cls._create_account('Bank Fees Expense', 'expense')
        cls.bank_account = cls._create_account('Bank Account', 'asset_cash', reconcile=True)
        cls.other_bank_account = cls._create_account('Other Bank Account', 'asset_cash', reconcile=True)

        # ---- journal --------------------------------------------------
        cls.journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id),
            ('type', '=', 'general'),
        ], limit=1)
        cls.journal = cls.journal or cls.env['account.journal'].create({
            'name': 'Miscellaneous',
            'code': 'MISC',
            'type': 'general',
            'company_id': cls.company.id,
        })

        # ---- settings -------------------------------------------------
        cls.company.write({
            'bank_fees_allocation_account_ids': [Command.set(
                (cls.card_account + cls.card_account_2).ids
            )],
            'bank_fees_expense_account_id': cls.fee_account.id,
            'bank_fees_bank_account_ids': [Command.set(
                (cls.bank_account + cls.other_bank_account).ids
            )],
            'bank_fees_allocation_journal_id': cls.journal.id,
        })

        # ---- users ----------------------------------------------------
        cls.accountant = new_test_user(
            cls.env,
            name='Bank Fees Accountant',
            login='bfa_accountant',
            password='bfa_accountant',
            email='bfa_accountant@test.com',
            group_ids=(
                cls.env.ref('account.group_account_user').ids
                + cls.env.ref('bank_fees_allocation.group_bank_fees_allocation_user').ids
            ),
            company_id=cls.company.id,
            company_ids=[(4, cls.company.id)],
        )

        cls.administrator = new_test_user(
            cls.env,
            name='Bank Fees Administrator',
            login='bfa_admin',
            password='bfa_admin',
            email='bfa_admin@test.com',
            group_ids=(
                cls.env.ref('account.group_account_manager').ids
                + cls.env.ref('base.group_system').ids
                + cls.env.ref(
                    'bank_fees_allocation.group_bank_fees_allocation_administrator'
                ).ids
            ),
            company_id=cls.company.id,
            company_ids=[(4, cls.company.id)],
        )

    # ==================================================================
    # Helpers
    # ==================================================================
    @classmethod
    def _create_account(cls, name, account_type, reconcile=False):
        """ Create a plain account for the company of the tests. """
        return cls.env['account.account'].create({
            'name': name,
            'account_type': account_type,
            'reconcile': reconcile,
            'company_ids': [Command.set(cls.company.ids)],
        })

    def _create_move(self, account, amount, date=None, analytic=False, name='Sale'):
        """ Create a posted journal item of the given amount.

        The amount is a **debit** (a sale booked on a clearing account),
        unless ``amount`` is negative, in which case it is a credit.
        """
        date = date or fields.Date.context_today(self)
        balance = amount
        income_account = self.env['account.account'].search([
            ('company_ids', 'in', self.company.ids),
            ('account_type', '=', 'income'),
        ], limit=1)
        move = self.env['account.move'].create({
            'journal_id': self.journal.id,
            'company_id': self.company.id,
            'date': date,
            'move_type': 'entry',
            'line_ids': [
                Command.create({
                    'account_id': account.id,
                    'name': name,
                    'balance': balance,
                    'analytic_distribution': (
                        {str(self.analytic_account.id): 100.0} if analytic else {}
                    ),
                }),
                Command.create({
                    'account_id': income_account.id,
                    'name': name,
                    'balance': -balance,
                }),
            ],
        })
        move.action_post()
        return move.line_ids.filtered(lambda line: line.account_id == account)

    def _create_move_in_company(self, company, account, amount, date=None):
        """ Create a posted journal item of the given amount in another
        company.

        The counterpart line is booked on an income account of that very
        company, so the entry is balanced even when the company has no
        chart of accounts.
        """
        date = date or fields.Date.context_today(self)
        income_account = self.env['account.account'].search([
            ('company_ids', 'in', company.ids),
            ('account_type', '=', 'income'),
        ], limit=1)
        if not income_account:
            income_account = self.env['account.account'].create({
                'name': 'Sales BFA %s' % company.id,
                'account_type': 'income',
                'company_ids': [Command.set(company.ids)],
            })
        journal = self.env['account.journal'].search([
            ('company_id', '=', company.id),
            ('type', '=', 'general'),
        ], limit=1)
        if not journal:
            journal = self.env['account.journal'].create({
                'name': 'Misc BFA',
                'code': 'MISCBFA',
                'type': 'general',
                'company_id': company.id,
            })
        move = self.env['account.move'].with_company(company).create({
            'journal_id': journal.id,
            'company_id': company.id,
            'date': date,
            'move_type': 'entry',
            'line_ids': [
                Command.create({
                    'account_id': account.id,
                    'name': 'Sale',
                    'balance': amount,
                }),
                Command.create({
                    'account_id': income_account.id,
                    'name': 'Sale',
                    'balance': -amount,
                }),
            ],
        })
        move.action_post()
        return move.line_ids.filtered(lambda line: line.account_id == account)

    def _create_wizard(self, lines, net=None, fee=None, **values):
        """ Create the wizard on the given journal items. """
        values.setdefault('bank_account_id', self.bank_account.id)
        values.setdefault('fee_account_id', self.fee_account.id)
        values.setdefault('journal_id', self.journal.id)
        wizard = self.env['bank.fees.allocation.wizard'].create({
            'line_ids': [Command.set(lines.ids)],
            **values,
        })
        if net is not None:
            wizard.net_amount = net
        if fee is not None:
            wizard.fee_amount = fee
        return wizard

    # ==================================================================
    # Settings & security
    # ==================================================================
    def test_settings_are_company_dependent(self):
        """ The configuration is stored on the company. """
        self.assertEqual(
            self.company.bank_fees_expense_account_id, self.fee_account
        )
        self.assertIn(
            self.card_account, self.company.bank_fees_allocation_account_ids
        )
        self.assertIn(
            self.bank_account, self.company.bank_fees_bank_account_ids
        )

    def test_accountant_cannot_edit_settings(self):
        """ The accountant has read-only access to the settings.

        In Odoo 20, ``res.config.settings`` is only writable by the
        *Administrator* role, so the accountant cannot even open the
        settings page: the configuration of the module is out of his reach.
        """
        with self.assertRaises(AccessError):
            self.env['res.config.settings'].with_user(self.accountant).create({})

    def test_administrator_can_edit_settings(self):
        """ The administrator can change the settings. """
        settings = self.env['res.config.settings'].with_user(self.administrator)
        settings = settings.create({})
        settings.write({
            'bank_fees_expense_account_id': self.other_bank_account.id,
        })
        self.assertEqual(
            self.company.bank_fees_expense_account_id, self.other_bank_account
        )
        # Put the configuration back.
        settings.write({
            'bank_fees_expense_account_id': self.fee_account.id,
        })

    def test_settings_block_is_hidden_from_the_accountant(self):
        """ The settings block of the module is restricted to the
        administrators.

        The ``groups`` attribute of the block is kept in the arch of the
        view: the Odoo client hides the block from the users that are not
        in the group.
        """
        view = self.env.ref(
            'bank_fees_allocation.res_config_settings_view_form_bank_fees_allocation'
        )
        arch = view.arch
        admin_group = self.env.ref(
            'bank_fees_allocation.group_bank_fees_allocation_administrator'
        )
        self.assertIn(
            'bank_fees_allocation.group_bank_fees_allocation_administrator', arch
        )
        # The accountant belongs to the user group but not to the
        # administrator group.
        self.assertNotIn(
            admin_group, self.accountant.all_group_ids
        )
        self.assertIn(
            self.env.ref('bank_fees_allocation.group_bank_fees_allocation_user'),
            self.accountant.all_group_ids,
        )

    # ==================================================================
    # The two-way computation
    # ==================================================================
    def test_fee_and_net_are_computed_both_ways(self):
        """ Editing the net amount recomputes the fee, and the other way
        round. """
        lines = self._create_move(self.card_account, 100.0)
        wizard = self._create_wizard(lines)
        self.assertAlmostEqual(wizard.total_amount, 100.0)
        # By default the fee is 0 and the net is the total.
        self.assertAlmostEqual(wizard.net_amount, 100.0)
        self.assertAlmostEqual(wizard.fee_amount, 0.0)

        # The user types the net amount: the fee follows.
        wizard.net_amount = 95.0
        self.assertAlmostEqual(wizard.fee_amount, 5.0)

        # The user types the fee amount: the net follows.
        wizard.fee_amount = 3.0
        self.assertAlmostEqual(wizard.net_amount, 97.0)

        # And the other way round again.
        wizard.net_amount = 90.0
        self.assertAlmostEqual(wizard.fee_amount, 10.0)

    def test_fee_and_net_are_computed_both_ways_in_the_web_client(self):
        """ The same consistency, but through the machinery the web client
        uses: the inverses are **not** run by the client, only the
        ``@api.onchange`` methods are. """
        lines = self._create_move(self.card_account, 100.0)
        wizard = self._create_wizard(lines)
        fields_spec = {
            'net_amount': {'type': 'monetary'},
            'fee_amount': {'type': 'monetary'},
            'total_amount': {'type': 'monetary'},
        }
        result = wizard.onchange({'net_amount': 95.0}, ['net_amount'], fields_spec)
        self.assertAlmostEqual(result['value']['fee_amount'], 5.0)

        result = wizard.onchange({'fee_amount': 3.0}, ['fee_amount'], fields_spec)
        self.assertAlmostEqual(result['value']['net_amount'], 97.0)

    # ==================================================================
    # The allocation itself
    # ==================================================================
    def test_single_account_allocation(self):
        """ One source account: one credit line, everything reconciled. """
        lines = self._create_move(self.card_account, 100.0)
        wizard = self._create_wizard(lines, net=95.0)
        self.assertAlmostEqual(wizard.fee_amount, 5.0)

        action = wizard.action_post()
        allocation = self.env['bank.fees.allocation'].browse(action['res_id'])
        move = allocation.move_id

        # The entry has three lines: bank, fees and the source account.
        self.assertEqual(len(move.line_ids), 3)
        self.assertEqual(move.state, 'posted')

        bank_line = move.line_ids.filtered(
            lambda line: line.account_id == self.bank_account
        )
        fee_line = move.line_ids.filtered(
            lambda line: line.account_id == self.fee_account
        )
        credit_line = move.line_ids.filtered(
            lambda line: line.account_id == self.card_account
        )
        self.assertAlmostEqual(bank_line.balance, 95.0)
        self.assertAlmostEqual(fee_line.balance, 5.0)
        self.assertAlmostEqual(credit_line.balance, -100.0)

        # The entry is balanced.
        self.assertAlmostEqual(sum(move.line_ids.mapped('balance')), 0.0)

        # The source item is reconciled.
        lines.invalidate_recordset(['reconciled', 'full_reconcile_id'])
        self.assertTrue(lines.reconciled)
        self.assertTrue(lines.full_reconcile_id)

        # The allocation record holds the amounts.
        self.assertAlmostEqual(allocation.total_amount, 100.0)
        self.assertAlmostEqual(allocation.net_amount, 95.0)
        self.assertAlmostEqual(allocation.fee_amount, 5.0)
        self.assertEqual(allocation.state, 'done')
        self.assertEqual(allocation.user_id, self.env.user)
        self.assertIn(lines, allocation.line_ids)

    def test_multiple_accounts_allocation(self):
        """ Several accounts: one credit line per account. """
        lines_1 = self._create_move(self.card_account, 100.0)
        lines_2 = self._create_move(self.card_account_2, 60.0)
        lines = lines_1 | lines_2

        wizard = self._create_wizard(lines, net=150.0)
        self.assertAlmostEqual(wizard.total_amount, 160.0)
        self.assertAlmostEqual(wizard.fee_amount, 10.0)

        action = wizard.action_post()
        allocation = self.env['bank.fees.allocation'].browse(action['res_id'])
        move = allocation.move_id

        # Bank + fees + one credit line per account.
        self.assertEqual(len(move.line_ids), 4)
        credit_1 = move.line_ids.filtered(
            lambda line: line.account_id == self.card_account
        )
        credit_2 = move.line_ids.filtered(
            lambda line: line.account_id == self.card_account_2
        )
        self.assertAlmostEqual(credit_1.balance, -100.0)
        self.assertAlmostEqual(credit_2.balance, -60.0)

        # Both source groups are reconciled.
        lines.invalidate_recordset(['reconciled', 'full_reconcile_id'])
        self.assertTrue(lines_1.reconciled)
        self.assertTrue(lines_2.reconciled)

    def test_credit_selection_is_allocated_in_the_other_direction(self):
        """ A selection of **credit** balances is allocated the other way
        round: the bank is credited and the source account is debited.

        The entry stays balanced and the source item is reconciled.
        """
        lines = self._create_move(self.card_account, -100.0)
        wizard = self._create_wizard(lines, net=95.0)
        self.assertAlmostEqual(wizard.total_amount, 100.0)
        self.assertAlmostEqual(wizard.fee_amount, 5.0)

        action = wizard.action_post()
        allocation = self.env['bank.fees.allocation'].browse(action['res_id'])
        move = allocation.move_id

        self.assertAlmostEqual(sum(move.line_ids.mapped('balance')), 0.0)
        bank_line = move.line_ids.filtered(
            lambda line: line.account_id == self.bank_account
        )
        source_line = move.line_ids.filtered(
            lambda line: line.account_id == self.card_account
        )
        self.assertAlmostEqual(bank_line.balance, -95.0)
        self.assertAlmostEqual(source_line.balance, 100.0)

        lines.invalidate_recordset(['reconciled', 'full_reconcile_id'])
        self.assertTrue(lines.reconciled)

    def test_mixed_directions_are_refused(self):
        """ A selection that mixes debits and credits cannot be allocated
        in one go: the entry would not be balanced. """
        debit_lines = self._create_move(self.card_account, 100.0)
        credit_lines = self._create_move(self.card_account, -40.0)
        with self.assertRaises(ValidationError):
            self.env['bank.fees.allocation.wizard'].create({
                'line_ids': [Command.set((debit_lines | credit_lines).ids)],
                'bank_account_id': self.bank_account.id,
                'fee_account_id': self.fee_account.id,
                'journal_id': self.journal.id,
            })

    def test_allocation_across_several_days(self):
        """ The selection may span several days. """
        from datetime import timedelta
        yesterday = fields.Date.context_today(self) - timedelta(days=1)
        lines_1 = self._create_move(self.card_account, 40.0, date=yesterday)
        lines_2 = self._create_move(self.card_account, 60.0)

        wizard = self._create_wizard(lines_1 | lines_2, net=95.0)
        self.assertAlmostEqual(wizard.total_amount, 100.0)
        self.assertAlmostEqual(wizard.fee_amount, 5.0)

        action = wizard.action_post()
        allocation = self.env['bank.fees.allocation'].browse(action['res_id'])
        lines_1.invalidate_recordset(['reconciled'])
        lines_2.invalidate_recordset(['reconciled'])
        self.assertTrue(lines_1.reconciled)
        self.assertTrue(lines_2.reconciled)
        self.assertEqual(len(allocation.move_id.line_ids), 3)

    def test_analytic_distribution_is_carried_over(self):
        """ The analytic distribution of the source items is carried over
        proportionally to the fee line. """
        lines = self._create_move(self.card_account, 100.0, analytic=True)
        wizard = self._create_wizard(lines, net=95.0)
        action = wizard.action_post()
        allocation = self.env['bank.fees.allocation'].browse(action['res_id'])

        fee_line = allocation.move_id.line_ids.filtered(
            lambda line: line.account_id == self.fee_account
        )
        self.assertTrue(fee_line.analytic_distribution)
        self.assertIn(str(self.analytic_account.id), fee_line.analytic_distribution)

        credit_line = allocation.move_id.line_ids.filtered(
            lambda line: line.account_id == self.card_account
        )
        self.assertIn(str(self.analytic_account.id), credit_line.analytic_distribution)

    def test_analytic_distribution_is_proportional(self):
        """ With several distributions, the fee line keeps the proportions. """
        analytic_2 = self.env['account.analytic.account'].create({
            'name': 'Branch Jeddah',
            'company_id': self.company.id,
            'plan_id': self.analytic_plan.id,
        })
        lines = self._create_move(self.card_account, 100.0, analytic=True)
        # Change the distribution of the source item: 75% / 25%.
        lines.analytic_distribution = {
            str(self.analytic_account.id): 75.0,
            str(analytic_2.id): 25.0,
        }
        wizard = self._create_wizard(lines, net=95.0)
        action = wizard.action_post()
        allocation = self.env['bank.fees.allocation'].browse(action['res_id'])
        fee_line = allocation.move_id.line_ids.filtered(
            lambda line: line.account_id == self.fee_account
        )
        distribution = fee_line.analytic_distribution
        self.assertAlmostEqual(distribution[str(self.analytic_account.id)], 75.0)
        self.assertAlmostEqual(distribution[str(analytic_2.id)], 25.0)

    # ==================================================================
    # Validations
    # ==================================================================
    def test_negative_fee_is_refused(self):
        """ A negative fee is refused. """
        lines = self._create_move(self.card_account, 100.0)
        wizard = self._create_wizard(lines)
        # The fee is recomputed from the net amount, so the negative fee
        # is refused by the constraint of the model.
        with self.assertRaises(ValidationError):
            wizard.fee_amount = -10.0

    def test_negative_net_is_refused(self):
        """ A negative net amount is refused. """
        lines = self._create_move(self.card_account, 100.0)
        wizard = self._create_wizard(lines)
        with self.assertRaises(ValidationError):
            wizard.net_amount = -10.0

    def test_already_reconciled_line_is_refused(self):
        """ A reconciled journal item cannot be allocated again. """
        lines = self._create_move(self.card_account, 100.0)
        wizard = self._create_wizard(lines, net=95.0)
        wizard.action_post()

        # The same line cannot be selected again.
        with self.assertRaises(ValidationError):
            self.env['bank.fees.allocation.wizard'].create({
                'line_ids': [Command.set(lines.ids)],
                'bank_account_id': self.bank_account.id,
                'fee_account_id': self.fee_account.id,
            })

    def test_draft_line_is_refused(self):
        """ A draft journal item cannot be allocated. """
        move = self.env['account.move'].create({
            'journal_id': self.journal.id,
            'company_id': self.company.id,
            'date': fields.Date.context_today(self),
            'move_type': 'entry',
            'line_ids': [
                Command.create({
                    'account_id': self.card_account.id,
                    'name': 'Draft sale',
                    'balance': 100.0,
                }),
                Command.create({
                    'account_id': self.env['account.account'].search([
                        ('company_ids', 'in', self.company.ids),
                        ('account_type', '=', 'income'),
                    ], limit=1).id,
                    'name': 'Draft sale',
                    'balance': -100.0,
                }),
            ],
        })
        lines = move.line_ids.filtered(lambda line: line.account_id == self.card_account)
        with self.assertRaises(ValidationError):
            self.env['bank.fees.allocation.wizard'].create({
                'line_ids': [Command.set(lines.ids)],
                'bank_account_id': self.bank_account.id,
                'fee_account_id': self.fee_account.id,
            })

    def test_line_outside_allocation_accounts_is_refused(self):
        """ A journal item of an account that is not configured is refused. """
        other_account = self._create_account('Unconfigured Clearing', 'asset_current', reconcile=True)
        lines = self._create_move(other_account, 100.0)
        with self.assertRaises(ValidationError):
            self.env['bank.fees.allocation.wizard'].create({
                'line_ids': [Command.set(lines.ids)],
                'bank_account_id': self.bank_account.id,
                'fee_account_id': self.fee_account.id,
            })

    def test_missing_fee_account_gives_a_clear_error(self):
        """ When the fee account is not configured, the error points to the
        settings. """
        # A second company, without any bank fees configuration.
        other_company = self.env['res.company'].create({
            'name': 'BFA No Fee Account',
            'currency_id': self.currency.id,
        })
        card_account = self.env['account.account'].create({
            'name': 'Visa Clearing 2',
            'account_type': 'asset_current',
            'reconcile': True,
            'company_ids': [Command.set(other_company.ids)],
        })
        bank_account = self.env['account.account'].create({
            'name': 'Bank Account 2',
            'account_type': 'asset_cash',
            'reconcile': True,
            'company_ids': [Command.set(other_company.ids)],
        })
        other_company.write({
            'bank_fees_allocation_account_ids': [Command.set(card_account.ids)],
            'bank_fees_bank_account_ids': [Command.set(bank_account.ids)],
        })
        lines = self._create_move_in_company(other_company, card_account, 100.0)

        # The wizard of that company cannot be created without a fee
        # account: the error points to the settings.
        with self.assertRaises(ValidationError) as catcher:
            self.env['bank.fees.allocation.wizard'].with_company(other_company).create({
                'line_ids': [Command.set(lines.ids)],
                'bank_account_id': bank_account.id,
            })
        self.assertIn('Bank Fees Expense Account', str(catcher.exception))
        self.assertIn('Settings', str(catcher.exception))

    def test_bank_account_is_required(self):
        """ The bank account is required. """
        lines = self._create_move(self.card_account, 100.0)
        wizard = self._create_wizard(lines)
        with self.assertRaises(ValidationError) as catcher:
            wizard.bank_account_id = False
        self.assertIn('bank account', str(catcher.exception).lower())

    # ==================================================================
    # Cancel & reverse
    # ==================================================================
    def test_cancel_unreconciles_and_reverses(self):
        """ The cancel action unreconciles the entry, reverses it and frees
        the original journal items. """
        lines = self._create_move(self.card_account, 100.0)
        wizard = self._create_wizard(lines, net=95.0)
        action = wizard.action_post()
        allocation = self.env['bank.fees.allocation'].browse(action['res_id'])
        move = allocation.move_id

        lines.invalidate_recordset(['reconciled', 'full_reconcile_id'])
        self.assertTrue(lines.reconciled)

        allocation.action_cancel()
        self.assertEqual(allocation.state, 'cancelled')

        # The original items are free again.
        lines.invalidate_recordset(['reconciled', 'full_reconcile_id'])
        self.assertFalse(lines.reconciled)
        self.assertFalse(lines.full_reconcile_id)

        # A reversal entry has been posted.
        reversal = self.env['account.move'].search([
            ('reversed_entry_id', '=', move.id),
            ('state', '=', 'posted'),
        ], limit=1)
        self.assertTrue(reversal)

        # Cancelling twice is refused.
        with self.assertRaises(UserError):
            allocation.action_cancel()

    def test_cancelled_lines_can_be_allocated_again(self):
        """ After a cancel, the same items can be allocated again. """
        lines = self._create_move(self.card_account, 100.0)
        wizard = self._create_wizard(lines, net=95.0)
        action = wizard.action_post()
        allocation = self.env['bank.fees.allocation'].browse(action['res_id'])
        allocation.action_cancel()

        lines.invalidate_recordset(['reconciled', 'full_reconcile_id'])
        wizard_2 = self._create_wizard(lines, net=98.0)
        self.assertAlmostEqual(wizard_2.fee_amount, 2.0)
        action_2 = wizard_2.action_post()
        allocation_2 = self.env['bank.fees.allocation'].browse(action_2['res_id'])
        self.assertEqual(allocation_2.state, 'done')
        lines.invalidate_recordset(['reconciled'])
        self.assertTrue(lines.reconciled)

    # ==================================================================
    # History & reports
    # ==================================================================
    def test_allocation_history_is_stored(self):
        """ The confirmation stores a record with every piece of information. """
        lines = self._create_move(self.card_account, 100.0)
        wizard = self._create_wizard(lines, net=95.0)
        action = wizard.action_post()
        allocation = self.env['bank.fees.allocation'].browse(action['res_id'])

        self.assertTrue(allocation.name)
        self.assertTrue(allocation.date)
        self.assertEqual(allocation.company_id, self.company)
        self.assertEqual(allocation.bank_account_id, self.bank_account)
        self.assertEqual(allocation.user_id, self.env.user)
        self.assertTrue(allocation.move_id)
        self.assertEqual(len(allocation.line_ids), 1)
        self.assertEqual(allocation.state, 'done')

    def test_allocation_sequence(self):
        """ The allocations are numbered, and the series restarts every
        year. """
        lines = self._create_move(self.card_account, 100.0)
        wizard = self._create_wizard(lines, net=95.0)
        allocation = self.env['bank.fees.allocation'].browse(
            wizard.action_post()['res_id']
        )
        year = allocation.date.year
        self.assertTrue(
            allocation.name.startswith('BFA/%04d/' % year),
            "Unexpected sequence number: %s" % allocation.name,
        )

        # The next allocation of the same year continues the series.
        lines_2 = self._create_move(self.card_account, 50.0)
        wizard_2 = self._create_wizard(lines_2, net=45.0)
        allocation_2 = self.env['bank.fees.allocation'].browse(
            wizard_2.action_post()['res_id']
        )
        self.assertTrue(
            allocation_2.name.startswith('BFA/%04d/' % year),
            "Unexpected sequence number: %s" % allocation_2.name,
        )
        self.assertNotEqual(allocation.name, allocation_2.name)

        # An allocation of another year starts a new series.
        from datetime import timedelta
        other_year_date = allocation.date + timedelta(days=400)
        lines_3 = self._create_move(self.card_account, 30.0, date=other_year_date)
        wizard_3 = self._create_wizard(lines_3, net=25.0, date=other_year_date)
        allocation_3 = self.env['bank.fees.allocation'].browse(
            wizard_3.action_post()['res_id']
        )
        self.assertTrue(
            allocation_3.name.startswith('BFA/%04d/' % other_year_date.year),
            "Unexpected sequence number: %s" % allocation_3.name,
        )

    def test_report_helpers(self):
        """ The report helpers return the expected totals and breakdowns. """
        lines = self._create_move(self.card_account, 100.0)
        wizard = self._create_wizard(lines, net=95.0)
        wizard.action_post()

        report = self.env['bank.fees.allocation.report']
        allocations = self.env['bank.fees.allocation'].search([])
        totals = report._report_totals(allocations)
        self.assertAlmostEqual(totals['total_sales'], 100.0)
        self.assertAlmostEqual(totals['total_fees'], 5.0)
        self.assertAlmostEqual(totals['total_net'], 95.0)

        by_bank = report._report_by_bank_account(allocations)
        self.assertTrue(by_bank)
        self.assertAlmostEqual(by_bank[0]['total_fees'], 5.0)

        by_day = report._report_by_day(allocations)
        self.assertEqual(len(by_day), 1)

        by_month = report._report_by_month(allocations)
        self.assertEqual(len(by_month), 1)

        by_account = report._report_by_account(allocations)
        self.assertTrue(by_account)

    # ==================================================================
    # The view
    # ==================================================================
    def test_allocation_view_domain(self):
        """ The domain of the view shows the posted, unreconciled items of
        the configured accounts only. """
        lines = self._create_move(self.card_account, 100.0)
        action_builder = self.env['bank.fees.allocation.line.action']
        domain = action_builder._allocation_domain()
        self.assertIn(('parent_state', '=', 'posted'), domain)
        self.assertIn(('reconciled', '=', False), domain)
        self.assertIn(('company_id', 'in', self.env.companies.ids), domain)

        found = self.env['account.move.line'].search(domain)
        self.assertIn(lines, found)

        # Once allocated, the item leaves the view.
        wizard = self._create_wizard(lines, net=95.0)
        wizard.action_post()
        found = self.env['account.move.line'].search(domain)
        self.assertNotIn(lines, found)

    def test_button_opens_the_wizard(self):
        """ The list header button opens the wizard on the selected items. """
        lines = self._create_move(self.card_account, 100.0)
        action = lines.action_bank_fees_allocation()
        self.assertEqual(action['res_model'], 'bank.fees.allocation.wizard')
        self.assertEqual(action['target'], 'new')
        self.assertEqual(action['context']['active_ids'], lines.ids)

    # ==================================================================
    # Multi-company
    # ==================================================================
    def test_multi_company_rule(self):
        """ The allocations of another company are not visible. """
        other_company = self.env['res.company'].create({
            'name': 'BFA Other Company',
            'currency_id': self.currency.id,
        })
        other_bank_account = self.env['account.account'].create({
            'name': 'Bank Account MC',
            'account_type': 'asset_cash',
            'reconcile': True,
            'company_ids': [Command.set(other_company.ids)],
        })
        allocation = self.env['bank.fees.allocation'].with_company(other_company).create({
            'date': fields.Date.context_today(self),
            'company_id': other_company.id,
            'bank_account_id': other_bank_account.id,
            'currency_id': self.currency.id,
            'total_amount': 100.0,
            'net_amount': 95.0,
            'fee_amount': 5.0,
        })
        # The record rule prevents the user of the first company from
        # reading it.
        accountant = self.env['bank.fees.allocation'].with_user(self.accountant)
        self.assertNotIn(allocation, accountant.search([]))

    def test_line_of_another_company_is_refused(self):
        """ A journal item of another company cannot be allocated with the
        items of the first company. """
        other_company = self.env['res.company'].create({
            'name': 'BFA Other Company 2',
            'currency_id': self.currency.id,
        })
        card_account = self.env['account.account'].create({
            'name': 'Visa Clearing 3',
            'account_type': 'asset_current',
            'reconcile': True,
            'company_ids': [Command.set(other_company.ids)],
        })
        other_company.write({
            'bank_fees_allocation_account_ids': [Command.set(card_account.ids)],
        })
        other_bank_account = self.env['account.account'].create({
            'name': 'Bank Account MC 2',
            'account_type': 'asset_cash',
            'reconcile': True,
            'company_ids': [Command.set(other_company.ids)],
        })
        other_fee_account = self.env['account.account'].create({
            'name': 'Fees MC 2',
            'account_type': 'expense',
            'company_ids': [Command.set(other_company.ids)],
        })
        other_company.write({
            'bank_fees_bank_account_ids': [Command.set(other_bank_account.ids)],
            'bank_fees_expense_account_id': other_fee_account.id,
        })
        lines_other = self._create_move_in_company(other_company, card_account, 100.0)
        lines_own = self._create_move(self.card_account, 100.0)

        # A selection that mixes two companies is refused.
        with self.assertRaises(ValidationError):
            self.env['bank.fees.allocation.wizard'].create({
                'line_ids': [Command.set((lines_other | lines_own).ids)],
                'bank_account_id': self.bank_account.id,
                'fee_account_id': self.fee_account.id,
            })

        # A selection of a single company is accepted.
        wizard_2 = self.env['bank.fees.allocation.wizard'].with_company(other_company).create({
            'line_ids': [Command.set(lines_other.ids)],
            'bank_account_id': other_bank_account.id,
            'fee_account_id': other_fee_account.id,
        })
        wizard_2._check_lines_consistency()
