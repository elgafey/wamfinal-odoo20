# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    branch_id = fields.Many2one(
        'branch.branch', string='Branch',
        compute='_compute_branch_id', store=True, readonly=False,
        domain=lambda self: [
            ('id', 'in', self.env.user.with_context(active_test=False).branch_visible_ids.ids),
        ],
        help='Branch given to the payment that is created and to its '
             'journal entry. It is proposed from the invoice or the bill '
             'that is paid, and it can be changed before creating the '
             'payment.',
    )

    # ------------------------------------------------------------------
    # The branch proposed on the wizard
    # ------------------------------------------------------------------
    @api.depends('line_ids.branch_id', 'journal_id.branch_id')
    def _compute_branch_id(self):
        """Propose the branch of the journal of the payment.

        The journal decides the branch (same rule as the entry), so a
        payment journal of a branch wins over the branch of the invoice:
        the entry created for the payment and the entry of the invoice then
        only meet through a journal of that branch. A payment journal
        without a branch keeps proposing the branch of the invoice.

        When several invoices are paid together, the branch of the first
        one is proposed: the field stays editable to correct it before the
        payment is created.
        """
        for wizard in self:
            wizard.branch_id = (
                wizard.journal_id.branch_id
                or wizard.line_ids[:1].branch_id
            )

    # ------------------------------------------------------------------
    # The values of the payments created by the wizard
    # ------------------------------------------------------------------
    def _create_payment_vals_from_wizard(self, batch_result):
        vals = super()._create_payment_vals_from_wizard(batch_result)
        vals['branch_id'] = self.branch_id.id
        return vals

    def _create_payment_vals_from_batch(self, batch_result):
        vals = super()._create_payment_vals_from_batch(batch_result)
        vals['branch_id'] = self.branch_id.id
        return vals
