# -*- coding: utf-8 -*-
"""Builder of the dynamic window action of the allocation view.

The domain of the main view cannot be written statically in the XML: it
depends on the accounts the administrator configured for the company, and
it must also be restricted to the company of the user.

The action is therefore built here, at runtime, and returned as a plain
``ir.actions.act_window`` dictionary by the server action that the menu
item points to.
"""

from odoo import _, api, models


class BankFeesAllocationLineAction(models.AbstractModel):
    """ Build the window action of the *Bank Fees Allocation* view. """

    _name = 'bank.fees.allocation.line.action'
    _description = 'Bank Fees Allocation View Action'

    @api.model
    def _allocation_account_ids(self):
        """ The allocation accounts configured for the companies of the user.

        :return: a recordset of ``account.account``.
        """
        companies = self.env.companies
        accounts = self.env['account.account'].browse()
        for company in companies:
            accounts |= company.bank_fees_allocation_account_ids
        return accounts

    @api.model
    def _allocation_domain(self):
        """ The domain of the allocation view.

        It shows the posted journal items that are not fully reconciled and
        that belong to the configured allocation accounts, restricted to the
        companies of the user.
        """
        accounts = self._allocation_account_ids()
        domain = [
            ('display_type', 'not in', ('line_section', 'line_subsection', 'line_note')),
            ('parent_state', '=', 'posted'),
            ('reconciled', '=', False),
            ('full_reconcile_id', '=', False),
            ('company_id', 'in', self.env.companies.ids),
        ]
        if accounts:
            domain.append(('account_id', 'in', accounts.ids))
        else:
            # No account configured: the view would show everything, which
            # is never what the accountant wants.  An impossible domain is
            # used instead, and the list shows an explicit message.
            domain.append(('id', '=', False))
        return domain

    @api.model
    def action_bank_fees_allocation_lines(self):
        """ Return the window action opening the allocation view. """
        return {
            'type': 'ir.actions.act_window',
            'name': _('Bank Fees Allocation'),
            'res_model': 'account.move.line',
            'view_mode': 'list,pivot,graph',
            'views': [
                (self.env.ref('bank_fees_allocation.view_bank_fees_allocation_move_line_list').id, 'list'),
                (self.env.ref('account.view_move_line_pivot').id, 'pivot'),
                (self.env.ref('account.account_move_line_graph_date').id, 'graph'),
            ],
            'search_view_id': self.env.ref(
                'bank_fees_allocation.view_bank_fees_allocation_move_line_search'
            ).id,
            'domain': self._allocation_domain(),
            'context': {
                'search_default_group_by_branch': 1,
                'search_default_posted': 1,
                'search_default_not_reconciled': 1,
            },
            'target': 'current',
        }
