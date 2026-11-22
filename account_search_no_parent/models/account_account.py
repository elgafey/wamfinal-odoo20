# -*- coding: utf-8 -*-
from odoo import api, models


class AccountAccount(models.Model):
    _inherit = 'account.account'

    @api.depends('code', 'name')
    @api.depends_context('company', 'formatted_display_name', 'from_bill')
    def _compute_display_name(self):
        """Show the account itself in the dropdowns — without its parents.

        The core renders the account dropdown as ``<code> <name_path>``, and
        ``name_path`` is the whole chain of parent-account names
        ("Cash at Bank / Main SAR Operating Account"). This module shows only
        the account: its code (for accounting users) and its own name —
        exactly what the core already does outside the dropdown context.
        """
        super()._compute_display_name()
        if not self.env.context.get('formatted_display_name'):
            return
        show_code = self.env.user.has_group('account.group_account_readonly')
        for account in self:
            account.display_name = (
                f"{account.code} {account.name}"
                if show_code and account.code
                else account.name
            )
