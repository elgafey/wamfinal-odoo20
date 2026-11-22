# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    branch_id = fields.Many2one(
        'branch.branch', string='Branch',
        compute='_compute_branch_id', store=True, readonly=False,
        domain=lambda self: [
            ('id', 'in', self.env.user.with_context(active_test=False).branch_visible_ids.ids),
        ],
        index=True, check_company=True, tracking=True,
        help='Branch of the journal entry created for this payment. It is '
             'proposed from the invoice or the bill that is paid, and it is '
             'given to the entry when the payment is posted.',
    )

    # ------------------------------------------------------------------
    # The branch of the payment
    # ------------------------------------------------------------------
    @api.depends('move_id.branch_id')
    def _compute_branch_id(self):
        """The payment always shows the branch of its journal entry.

        The field is stored and editable (and not a simple related field)
        because the entry does not exist yet when the payment is created:
        the branch is kept by the payment and given to the entry by
        ``_generate_move_vals``. As soon as the entry exists, the payment
        follows it, so the two records can never disagree.
        """
        for payment in self:
            payment.branch_id = payment.move_id.branch_id

    def _generate_move_vals(self, write_off_line_vals=None, force_balance=None, line_ids=None):
        """Give the branch of the payment to the entry it creates."""
        vals = super()._generate_move_vals(
            write_off_line_vals=write_off_line_vals,
            force_balance=force_balance,
            line_ids=line_ids,
        )
        vals['branch_id'] = self.branch_id.id
        return vals

    # ------------------------------------------------------------------
    # The journal decides the branch
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        """A payment made in the journal of a branch lands on that branch.

        Same rule as the journal entry: the branch is filled before the
        payment is written when the caller does not give one, and an
        explicit branch that disagrees with the journal is turned into an
        error by the constraint below instead of being corrected quietly.
        """
        journal_ids = {
            vals['journal_id'] for vals in vals_list if vals.get('journal_id')
        }
        journal_branch = {
            journal.id: journal.branch_id.id
            for journal in self.env['account.journal'].browse(list(journal_ids))
        }
        for vals in vals_list:
            branch_id = journal_branch.get(vals.get('journal_id'))
            if branch_id and not vals.get('branch_id'):
                vals['branch_id'] = branch_id
        payments = super().create(vals_list)
        # safety net: the journal of a payment is a stored computed field,
        # so it can be chosen by Odoo itself and never reach ``vals``.
        for payment in payments:
            if payment.journal_id.branch_id and not payment.branch_id:
                payment.branch_id = payment.journal_id.branch_id
        return payments

    @api.onchange('journal_id')
    def _onchange_journal_branch(self):
        """Show the branch of the journal as soon as it is selected."""
        if self.journal_id.branch_id:
            self.branch_id = self.journal_id.branch_id

    @api.constrains('branch_id', 'journal_id')
    def _check_branch_matches_journal(self):
        """A payment can only be made in a journal of its own branch."""
        for payment in self:
            journal_branch = payment.journal_id.branch_id
            if journal_branch and payment.branch_id != journal_branch:
                raise ValidationError(_(
                    'The journal "%(journal)s" belongs to the branch '
                    '"%(journal_branch)s": a payment can only be made in a '
                    'journal of that branch. This payment is on '
                    '"%(payment_branch)s". Choose another journal, or move '
                    'the payment to the branch of the journal.',
                    journal=payment.journal_id.display_name,
                    journal_branch=journal_branch.display_name,
                    payment_branch=payment.branch_id.display_name or _('No branch'),
                ))

    def write(self, vals):
        """Keep the entry on the branch chosen on the payment.

        Choosing another journal moves the payment to the branch of that
        journal, unless a branch is written at the same time, in which case
        the constraint checks the two values against each other.
        """
        if 'journal_id' in vals and 'branch_id' not in vals:
            journal_branch = self.env['account.journal'].browse(
                vals['journal_id']
            ).branch_id
            if journal_branch:
                vals = dict(vals, branch_id=journal_branch.id)
        res = super().write(vals)
        if 'branch_id' in vals:
            # the payment of a posted entry can only be changed by code:
            # the entry follows so that the two never disagree.
            self.move_id.branch_id = vals['branch_id']
        return res
