# -*- coding: utf-8 -*-
"""Extension of ``account.move.line``.

The module does **not** override any core method.  It only adds:

* ``action_bank_fees_allocation()``: the object method behind the
  *Bank Fees Allocation* button of the list header, which opens the wizard
  on the selected journal items;
* a few read-only helpers used by the wizard to validate the selection
  and to compute the amounts.

The helpers rely on the real Odoo 20 fields:

* ``parent_state`` tells whether the entry is posted;
* ``reconciled`` / ``full_reconcile_id`` tell whether the item is already
  reconciled;
* ``balance`` is the signed amount of the item in the company currency;
* ``amount_residual`` is the amount still available for reconciliation;
* ``account_id.reconcile`` is the *Payment Reconciliation* flag of the
  account (the account must allow reconciliation to be reconciled at all).
"""

from odoo import _, api, models
from odoo.exceptions import UserError


class AccountMoveLine(models.Model):
    """ Journal items: the Bank Fees Allocation button and its helpers. """

    _inherit = 'account.move.line'

    # ------------------------------------------------------------------
    # Eligibility
    # ------------------------------------------------------------------
    def _bank_fees_eligibility_error(self):
        """ Return a user-facing message when this journal item cannot be
        allocated, ``False`` otherwise.

        This is a read-only helper: it never modifies anything.
        """
        self.ensure_one()
        if self.display_type in ('line_section', 'line_subsection', 'line_note'):
            return _("Sections and notes cannot be allocated.")
        if self.parent_state == 'cancel':
            return _("You cannot use a cancelled journal item.")
        if self.parent_state != 'posted':
            return _("Only posted journal items can be allocated.")
        if not self.account_id.reconcile:
            return _(
                "The account %s does not allow reconciliation.",
                self.account_id.display_name,
            )
        if self.reconciled or self.full_reconcile_id:
            return _("This journal item has already been reconciled.")
        if not self.amount_residual:
            return _("This journal item has nothing left to allocate.")
        return False

    def _bank_fees_selection_error(self):
        """ Return a user-facing message when the *selection* itself cannot
        be handled in one go, ``False`` otherwise.

        The allocation works on one company and one currency at a time:
        the entries are posted in the currency of the company.
        """
        if not self:
            return _("Please select at least one journal item to allocate.")
        if len(self.company_id) > 1:
            return _("The selected journal items belong to different companies.")
        currencies = self.env['res.currency']
        for line in self:
            currencies |= line.currency_id
        if len(currencies) > 1:
            return _(
                "All selected journal items must use the same currency.\n"
                "Selected currencies: %s",
                ", ".join(currencies.mapped('name')),
            )
        return False

    # ------------------------------------------------------------------
    # Amounts
    # ------------------------------------------------------------------
    def _bank_fees_currency(self):
        """ Currency used to express the amounts of the allocation.

        Same rule as Odoo's own reconciliation wizard: the currency of the
        journal item is used when it differs from the company currency,
        otherwise the company currency is used.
        """
        self.ensure_one()
        if self.currency_id and self.currency_id != self.company_currency_id:
            return self.currency_id
        return self.company_currency_id

    def _bank_fees_amounts(self):
        """ Amounts of one journal item for the allocation.

        :return: a tuple ``(currency, signed residual in that currency,
                 signed residual in the company currency)``.
        """
        self.ensure_one()
        if self.currency_id and self.currency_id != self.company_currency_id:
            return self.currency_id, self.amount_residual_currency, self.amount_residual
        return self.company_currency_id, self.amount_residual, self.amount_residual

    # ------------------------------------------------------------------
    # Action
    # ------------------------------------------------------------------
    def action_bank_fees_allocation(self):
        """ Open the Bank Fees Allocation wizard on the selected items.

        Called by the *Bank Fees Allocation* button of the list header.
        One wizard handles any number of selected items, across several
        days and several accounts, and produces a single journal entry.
        """
        if not self:
            raise UserError(_("Please select at least one journal item to allocate."))
        for line in self:
            error = line._bank_fees_eligibility_error()
            if error:
                raise UserError("%s\n%s" % (error, _("Journal item: %s", line.display_name)))
        error = self._bank_fees_selection_error()
        if error:
            raise UserError(error)
        return {
            'name': _('Bank Fees Allocation'),
            'type': 'ir.actions.act_window',
            'res_model': 'bank.fees.allocation.wizard',
            'view_mode': 'form',
            'view_id': self.env.ref('bank_fees_allocation.bank_fees_allocation_wizard_form').id,
            'target': 'new',
            'context': {
                'active_model': 'account.move.line',
                'active_ids': self.ids,
                'default_line_ids': self.ids,
            },
        }
