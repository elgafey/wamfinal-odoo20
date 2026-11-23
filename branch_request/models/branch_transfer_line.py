# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

# Filled in by the workflow wizards, in the matching state only.
WIZARD_FIELDS = {'sent_qty', 'received_qty'}


class BranchTransferLine(models.Model):
    _name = 'branch.transfer.line'
    _description = 'Branch Transfer Line'
    _order = 'id'

    transfer_id = fields.Many2one(
        'branch.transfer', string='Transfer', required=True,
        ondelete='cascade', index=True)
    product_id = fields.Many2one(
        'product.product', string='Product', required=True,
        domain="[('is_storable', '=', True),"
               " ('tracking', 'not in', ('lot', 'serial'))]")
    uom_id = fields.Many2one(
        'uom.uom', string='UoM', compute='_compute_uom_id',
        store=True, readonly=False, precompute=True)
    requested_qty = fields.Float(
        string='Requested', default=1.0, digits='Product Unit')
    sent_qty = fields.Float(
        string='Sent', default=0.0, digits='Product Unit',
        readonly=True, copy=False)
    received_qty = fields.Float(
        string='Received', default=0.0, digits='Product Unit',
        readonly=True, copy=False)
    available_qty = fields.Float(
        string='Available', compute='_compute_available_qty',
        digits='Product Unit',
        help='On hand quantity of the product at the supplying branch. Only '
             'shown to the responsible users of the supplying branch and to '
             'the procurement team.')
    difference_qty = fields.Float(
        string='Difference', compute='_compute_difference_qty', store=True,
        digits='Product Unit',
        help='Sent quantity minus counted quantity, meaningful once the '
             'transfer has been received: positive = shortage, negative = '
             'excess.')

    @api.depends('product_id')
    def _compute_uom_id(self):
        for line in self:
            line.uom_id = line.product_id.uom_id

    @api.depends('product_id', 'transfer_id.from_location_id',
                 'transfer_id.from_user_ids')
    @api.depends_context('uid')
    def _compute_available_qty(self):
        quants = self.env['stock.quant'].sudo()
        user = self.env.user
        is_allowed = user.has_group(
            'branch_request.group_branch_request_procurement')
        for line in self:
            line.available_qty = 0.0
            transfer = line.transfer_id.sudo()
            if not line.product_id or not transfer.from_location_id:
                continue
            if not is_allowed and user.id not in transfer.from_user_ids.ids:
                continue
            result = quants._read_group(
                [('product_id', '=', line.product_id.id),
                 ('location_id', 'child_of', transfer.from_location_id.id)],
                aggregates=['quantity:sum'])
            line.available_qty = result[0][0] if result and result[0][0] else 0.0

    @api.depends('sent_qty', 'received_qty', 'transfer_id.state')
    def _compute_difference_qty(self):
        for line in self:
            if line.transfer_id.state == 'received':
                line.difference_qty = line.sent_qty - line.received_qty
            else:
                line.difference_qty = 0.0

    @api.constrains('product_id')
    def _check_product(self):
        for line in self:
            if not line.product_id:
                continue
            if not line.product_id.is_storable:
                raise ValidationError(_(
                    'Only storable products can be transferred: %s.',
                    line.product_id.display_name))
            if line.product_id.tracking in ('lot', 'serial'):
                raise ValidationError(_(
                    'Lots and serial numbers are not supported: %s.',
                    line.product_id.display_name))

    @api.constrains('requested_qty')
    def _check_requested_qty(self):
        for line in self:
            if line.requested_qty <= 0:
                raise ValidationError(_(
                    'Requested quantities must be greater than zero.'))

    # ------------------------------------------------------------------
    # Lines follow their parent: they are editable in the draft state only,
    # except for the counted quantities filled in by the wizards.
    # ------------------------------------------------------------------
    def _check_lines_editable(self, vals=None):
        if self.env.su or not self:
            return
        if vals is None:
            # create / unlink: only while the transfer is a draft
            if any(line.transfer_id.state != 'draft' for line in self):
                raise AccessError(_(
                    'The lines of a transfer can only be changed while it '
                    'is a draft.'))
            return
        wizard_fields = set(vals) & WIZARD_FIELDS
        if set(vals) - wizard_fields:
            if any(line.transfer_id.state != 'draft' for line in self):
                raise AccessError(_(
                    'The lines of a transfer can only be changed while it '
                    'is a draft.'))
            return
        for line in self:
            state = line.transfer_id.state
            if 'sent_qty' in wizard_fields and state != 'submitted':
                raise AccessError(_(
                    'The sent quantities can only be set while the transfer '
                    'is waiting to be sent.'))
            if 'received_qty' in wizard_fields and state != 'in_transit':
                raise AccessError(_(
                    'The counted quantities can only be set while the '
                    'transfer is in transit.'))

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._check_lines_editable()
        return lines

    def write(self, vals):
        self._check_lines_editable(vals)
        return super().write(vals)

    def unlink(self):
        self._check_lines_editable()
        return super().unlink()
