# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class BranchTransferReceiveLine(models.TransientModel):
    _name = 'branch.transfer.receive.line'
    _description = 'Branch Transfer Receive Line'

    wizard_id = fields.Many2one(
        'branch.transfer.receive.wizard', string='Wizard', required=True,
        ondelete='cascade')
    transfer_line_id = fields.Many2one(
        'branch.transfer.line', string='Transfer Line', required=True,
        ondelete='cascade')
    product_id = fields.Many2one(
        'product.product', string='Product', readonly=True)
    sent_qty = fields.Float(
        string='Sent', readonly=True, digits='Product Unit')
    qty_counted = fields.Float(
        string='Quantity counted', default=0.0, digits='Product Unit')

    @api.constrains('qty_counted')
    def _check_qty_counted(self):
        for line in self:
            if line.qty_counted < 0:
                raise ValidationError(_('Counted quantities cannot be '
                                        'negative.'))


class BranchTransferReceiveWizard(models.TransientModel):
    """Receive the goods that are waiting in the transit location.

    The stock always moves completely, for the full sent quantity: nothing
    stays in the transit location.  The counted quantity is bookkeeping
    only, the difference against the sent quantity is kept for
    accountability.
    """

    _name = 'branch.transfer.receive.wizard'
    _description = 'Receive Branch Transfer'

    transfer_id = fields.Many2one(
        'branch.transfer', string='Transfer', required=True,
        ondelete='cascade')
    line_ids = fields.One2many(
        'branch.transfer.receive.line', 'wizard_id', string='Products')

    def action_receive(self):
        self.ensure_one()
        transfer = self.transfer_id
        transfer._check_can_receive()
        if transfer.state != 'in_transit':
            raise UserError(_('Only a transfer in transit can be received.'))
        if not self.line_ids:
            raise UserError(_('This transfer has no product lines.'))

        counted_by_line = {
            wizard_line.transfer_line_id.id: wizard_line.qty_counted
            for wizard_line in self.line_ids
        }
        sent_lines = transfer.line_ids.filtered(lambda line: line.sent_qty > 0)
        if not sent_lines:
            raise UserError(_('There is nothing to receive on this transfer.'))

        transit = transfer._get_transit_location()
        moves = [(line.product_id, line.sent_qty, line.uom_id)
                 for line in sent_lines]
        picking = transfer._create_and_validate_picking(
            transit, transfer.to_location_id, moves)

        # The counted quantities are written while the transfer is still in
        # transit, then the state changes.
        for line in transfer.line_ids:
            line.write({'received_qty': counted_by_line.get(line.id, 0.0)})
        transfer.write({
            'state': 'received',
            'in_picking_id': picking.id,
            'received_by_id': self.env.uid,
            'received_date': fields.Datetime.now(),
        })
        transfer._post_receive_message()
        return {
            'type': 'ir.actions.act_window',
            'name': transfer.name,
            'res_model': 'branch.transfer',
            'res_id': transfer.id,
            'view_mode': 'form',
            'target': 'current',
        }
