from odoo import Command, _, models
from odoo.exceptions import UserError

# Account types that Odoo 20 classifies as expenses (account.account.account_type).
# Verified against odoo/addons/account/models/account_account.py -> Selection field.
EXPENSE_ACCOUNT_TYPES = (
    'expense',                # Expenses
    'expense_other',          # Other Expenses
    'expense_depreciation',   # Depreciation
    'expense_direct_cost',    # Cost of Revenue
)


class AccountMoveLine(models.Model):
    """ Only adds the button handler used by the Bank Fees Allocation wizard.

    No core method is overridden here: ``action_reconcile`` (the standard
    Reconcile button) is left untouched.
    """
    _inherit = 'account.move.line'

    def _bank_fees_eligibility_error(self):
        """ Return a user-facing message when this journal item cannot be used
        by the Bank Fees Allocation wizard, ``False`` otherwise.

        This is a read-only helper; it does not modify anything.
        """
        self.ensure_one()
        if self.display_type in ('line_section', 'line_subsection', 'line_note'):
            return _("Sections and notes cannot be used with Closing Fees.")
        if self.parent_state == 'cancel':
            return _("You can not use a cancelled journal item.")
        if self.parent_state != 'posted':
            return _("Only posted journal items can be used with Closing Fees.")
        if not self.account_id.reconcile:
            return _("The account %s does not allow reconciliation.", self.account_id.display_name)
        if self.reconciled or self.full_reconcile_id:
            return _("This journal item has already been reconciled.")
        return False

    @staticmethod
    def _bank_fees_line_currency(line):
        """ Currency used to express the residual of one journal item.

        Same rule as Odoo's reconciliation wizard: a foreign currency is used
        when the item carries one that differs from the company currency,
        otherwise the company currency.
        """
        if line.currency_id and line.currency_id != line.company_currency_id:
            return line.currency_id
        return line.company_currency_id

    def _bank_fees_selection_error(self):
        """ Return a user-facing message when the *selection* itself cannot be
        handled in one go, ``False`` otherwise.

        The wizard works on one account at a time: the reconciling line is
        always posted on the account of the selection itself, and the
        *Unlink Account* (optional, Bank and Cash only) only receives the
        remaining amount when it is filled in.
        """
        if not self:
            return _("Please select at least one journal item to use Closing Fees.")
        if len(self.company_id) > 1:
            return _("The selected journal items belong to different companies.")
        if len(self.account_id) > 1:
            return _(
                "All selected journal items must belong to the same account.\n"
                "Selected accounts: %s",
                ", ".join(self.account_id.mapped('display_name')),
            )
        currencies = self.env['res.currency']
        for line in self:
            currencies |= self._bank_fees_line_currency(line)
        if len(currencies) > 1:
            return _(
                "All selected journal items must use the same currency.\n"
                "Selected currencies: %s",
                ", ".join(currencies.mapped('name')),
            )
        return False

    def action_bank_fees_allocation(self):
        """ Open the Bank Fees Allocation wizard for the selected journal items.

        Called by the 'Closing Fees' list-header button that this module adds
        right next to the standard 'Reconcile' button. One wizard handles any
        number of selected items and produces a single journal entry.
        """
        if not self:
            raise UserError(_("Please select at least one journal item to use Closing Fees."))
        for line in self:
            error = line._bank_fees_eligibility_error()
            if error:
                raise UserError("%s\n%s" % (error, _("Journal item: %s", line.display_name)))
        error = self._bank_fees_selection_error()
        if error:
            raise UserError(error)
        return {
            'name': _('Closing Fees'),
            'type': 'ir.actions.act_window',
            'res_model': 'bank.fees.allocation.wizard',
            'view_mode': 'form',
            'view_id': self.env.ref('bank_fees_allocation.bank_fees_wizard_form').id,
            'target': 'new',
            'context': {
                'active_model': 'account.move.line',
                'active_ids': self.ids,
                'default_line_ids': [Command.set(self.ids)],
            },
        }
