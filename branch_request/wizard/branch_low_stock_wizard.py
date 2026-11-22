# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError

PROCUREMENT_GROUP = 'branch_request.group_branch_request_procurement'


class BranchLowStockWizard(models.TransientModel):
    _name = 'branch.low.stock.wizard'
    _description = 'Low Stock Search'

    threshold = fields.Float(
        string='Threshold', digits='Product Unit', default=0.0,
        help='Show products with an on hand quantity below this value. '
             'Set 0 to show every storable product.')
    location_id = fields.Many2one(
        'stock.location', string='Location',
        domain="[('usage', '=', 'internal')]",
        help='Leave empty to include all internal locations.')

    def _check_procurement(self):
        if not (self.env.su or self.env.user.has_group(PROCUREMENT_GROUP)):
            raise AccessError(
                _('Only the procurement team may use this screen.'))

    def action_search(self):
        """Search the storable products below the threshold and return the
        result list.  Quantity is the sum of the stock quants of the
        selected location (or of every internal location)."""
        self.ensure_one()
        self._check_procurement()

        threshold = self.threshold
        location = self.location_id
        products = self.env['product.product'].search([
            ('is_storable', '=', True),
            '|',
            ('company_id', 'parent_of', self.env.companies.ids),
            ('company_id', '=', False),
        ])
        if location:
            quant_domain = [('location_id', 'child_of', location.id)]
        else:
            quant_domain = [('location_id.usage', '=', 'internal')]
        on_hand = {}
        groups = self.env['stock.quant']._read_group(
            quant_domain, ['product_id'], ['quantity:sum'])
        for product, quantity in groups:
            on_hand[product.id] = quantity or 0.0

        rows = []
        for product in products:
            quantity = on_hand.get(product.id, 0.0)
            if threshold > 0:
                if product.uom_id.compare(quantity, threshold) >= 0:
                    continue
                shortage = threshold - quantity
            else:
                shortage = 0.0
            rows.append({
                'product_id': product.id,
                'location_id': location.id,
                'qty_available': quantity,
                'shortage': shortage,
                'qty_to_order': shortage,
            })

        lines = self.env['branch.low.stock.line'].create(rows)
        action = self.env['ir.actions.act_window']._for_xml_id(
            'branch_request.action_branch_low_stock_list')
        action['domain'] = [('id', 'in', lines.ids)]
        action['context'] = {}
        return action


class BranchLowStockLine(models.TransientModel):
    _name = 'branch.low.stock.line'
    _description = 'Low Stock Product Line'
    _order = 'qty_available asc, product_id'

    product_id = fields.Many2one(
        'product.product', string='Product', required=True,
        index=True, ondelete='cascade')
    default_code = fields.Char(
        related='product_id.default_code', string='Reference')
    image_128 = fields.Image(related='product_id.image_128')
    categ_id = fields.Many2one(
        'product.category', related='product_id.categ_id',
        string='Category', store=True)
    uom_id = fields.Many2one(
        'uom.uom', related='product_id.uom_id', string='Unit')
    location_id = fields.Many2one(
        'stock.location', string='Location', ondelete='cascade')
    location_display = fields.Char(
        string='Location', compute='_compute_location_display', store=True)
    qty_available = fields.Float(string='On Hand', digits='Product Unit')
    shortage = fields.Float(string='Shortage', digits='Product Unit')
    qty_to_order = fields.Float(
        string='To Order', digits='Product Unit', default=0.0)

    @api.depends('location_id', 'location_id.complete_name')
    def _compute_location_display(self):
        for line in self:
            line.location_display = (
                line.location_id.complete_name or _('All internal locations'))

    def _check_procurement(self):
        if not (self.env.su or self.env.user.has_group(PROCUREMENT_GROUP)):
            raise AccessError(
                _('Only the procurement team may use this screen.'))

    @api.model_create_multi
    def create(self, vals_list):
        self._check_procurement()
        return super().create(vals_list)

    def write(self, vals):
        self._check_procurement()
        return super().write(vals)

    def unlink(self):
        self._check_procurement()
        return super().unlink()
