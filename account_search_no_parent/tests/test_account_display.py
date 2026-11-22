# -*- coding: utf-8 -*-
from odoo import Command
from odoo.tests import TransactionCase


class TestAccountDisplay(TransactionCase):
    """The account dropdown must show the account itself — no parent path."""

    def setUp(self):
        super().setUp()
        self.parent = self.env['account.account'].create({
            'name': 'Cash at Bank', 'code': '1601',
            'account_type': 'asset_cash',
        })
        self.child = self.env['account.account'].create({
            'name': 'Main SAR Operating Account', 'code': '160101',
            'account_type': 'asset_cash',
            'parent_id': self.parent.id,
        })
        # the code is displayed only to accounting users: make the test user
        # one, like any real accountant
        self.env.ref('account.group_account_readonly').write(
            {'user_ids': [Command.link(self.env.user.id)]})

    def test_01_dropdown_shows_the_account_without_its_parents(self):
        """ The dropdown context must not bring the parent names in. """
        display = self.child.with_context(
            formatted_display_name=True).display_name
        self.assertIn('Main SAR Operating Account', display)
        self.assertNotIn('Cash at Bank', display,
                         'the parent path must not appear in the dropdown')

    def test_02_code_kept_for_accounting_users(self):
        """ The account code is shown to accounting users, and only the
        name to everybody else. """
        display = self.child.with_context(
            formatted_display_name=True).display_name
        self.assertTrue(display.startswith('160101 '), display)
        plain = self.env['res.users'].create({
            'name': 'Plain User', 'login': 'asnp_plain',
            'group_ids': [Command.link(self.env.ref('base.group_user').id)],
        })
        plain_display = self.child.with_user(plain).with_context(
            formatted_display_name=True).display_name
        self.assertEqual(plain_display, 'Main SAR Operating Account',
                         plain_display)

    def test_03_search_by_own_name_still_finds_it(self):
        """ Searching the account name still returns the account. """
        found = self.env['account.account'].with_context(
            formatted_display_name=True).name_search('Main SAR Operating')
        self.assertIn(self.child.id, [r[0] for r in found])

    def test_04_plain_display_unchanged(self):
        """ Outside the dropdown context the core rule still applies. """
        display = self.child.display_name
        self.assertNotIn('Cash at Bank', display)
        self.assertTrue(display.startswith('160101 '), display)

    def test_05_renaming_refreshes_the_display(self):
        """ The display follows a rename (the compute depends on name). """
        self.child.name = 'Main USD Operating Account'
        display = self.child.with_context(
            formatted_display_name=True).display_name
        self.assertIn('Main USD Operating Account', display)
        self.assertNotIn('Cash at Bank', display)
