# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class BranchTransferSendLine(models.TransientModel):
    _name = 'branch.transfer.send.line'
    _description = 'Branch Transfer Send Line'

    wizard_id = fields.Many2one(
        'branch.transfer.send.wizard', string='Wizard', required=True,
        ondelete='cascade')
    transfer_line_id = fields.Many2one(
        'branch.transfer.line', string='Transfer Line', required=True,
        ondelete='cascade')
    product_id = fields.Many2one(
        'product.product', string='Product', readonly=True)
    requested_qty = fields.Float(
        string='Requested', readonly=True, digits='Product Unit')
    available_qty = fields.Float(
        string='Available', readonly=True, digits='Product Unit')
    qty_to_send = fields.Float(
        string='Quantity to send', default=0.0, digits='Product Unit')

    @api.constrains('qty_to_send')
    def _check_qty_to_send(self):
        for line in self:
            if line.qty_to_send < 0:
                raise ValidationError(_('Quantities to send cannot be '
                                        'negative.'))


class BranchTransferSendWizard(models.TransientModel):
    """Approve a submitted transfer and send the goods to the transit
    location.

    The quantity to send may exceed what is available at the supplying
    branch (the responsible user takes ownership of any mismatch) and may
    be lower than requested: the remainder is simply cancelled, without any
    backorder.
    """

    _name = 'branch.transfer.send.wizard'
    _description = 'Approve and Send Branch Transfer'

    transfer_id = fields.Many2one(
        'branch.transfer', string='Transfer', required=True,
        ondelete='cascade')
    line_ids = fields.One2many(
        'branch.transfer.send.line', 'wizard_id', string='Products')

    def action_send(self):
        self.ensure_one()
        transfer = self.transfer_id
        transfer._check_can_supply()
        if transfer.state != 'submitted':
            raise UserError(_('Only a submitted transfer can be sent.'))
        if not self.line_ids:
            raise UserError(_('This transfer has no product lines.'))

        qty_by_line = {
            wizard_line.transfer_line_id.id: wizard_line.qty_to_send
            for wizard_line in self.line_ids
        }
        send_lines = transfer.line_ids.filtered(
            lambda line: qty_by_line.get(line.id, 0.0) > 0)
        if not send_lines:
            raise UserError(_(
                'Enter a quantity to send for at least one product line.'))

        transit = transfer._get_transit_location()
        moves = [(line.product_id, qty_by_line.get(line.id, 0.0), line.uom_id)
                 for line in send_lines]
        picking = transfer._create_and_validate_picking(
            transfer.from_location_id, transit, moves)

        # The sent quantities are written while the transfer is still
        # submitted, then the state changes.
        for line in transfer.line_ids:
            line.write({'sent_qty': qty_by_line.get(line.id, 0.0)})
        transfer.write({
            'state': 'in_transit',
            'out_picking_id': picking.id,
            'sent_by_id': self.env.uid,
            'sent_date': fields.Datetime.now(),
        })
        transfer._notify_requesting()
        return {
            'type': 'ir.actions.act_window',
            'name': transfer.name,
            'res_model': 'branch.transfer',
            'res_id': transfer.id,
            'view_mode': 'form',
            'target': 'current',
        }
