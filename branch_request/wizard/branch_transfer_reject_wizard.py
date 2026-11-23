# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class BranchTransferRejectWizard(models.TransientModel):
    """Small wizard: the supplying branch refuses the request and must say
    why."""

    _name = 'branch.transfer.reject.wizard'
    _description = 'Reject Branch Transfer'

    transfer_id = fields.Many2one(
        'branch.transfer', string='Transfer', required=True,
        ondelete='cascade')
    # Not required at the field level: the wizard record is created before
    # the user types.  The form marks it as required and action_reject()
    # refuses an empty reason.
    reason = fields.Text(string='Reason')

    def action_reject(self):
        self.ensure_one()
        transfer = self.transfer_id
        transfer._check_can_supply()
        if transfer.state != 'submitted':
            raise UserError(_('Only a submitted transfer can be rejected.'))
        if not (self.reason or '').strip():
            raise UserError(_('A reason is required to reject a transfer.'))
        transfer.write({
            'state': 'rejected',
            'rejection_reason': self.reason,
        })
        transfer._notify_rejection()
        return {
            'type': 'ir.actions.act_window',
            'name': transfer.name,
            'res_model': 'branch.transfer',
            'res_id': transfer.id,
            'view_mode': 'form',
            'target': 'current',
        }
