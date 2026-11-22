# -*- coding: utf-8 -*-
from odoo import api, fields, models


class BranchRequestLine(models.Model):
    _name = 'branch.request.line'
    _description = 'Branch Request Line'
    _order = 'id'

    request_id = fields.Many2one(
        'branch.request', string='Request', required=True,
        ondelete='cascade', index=True)
    product_id = fields.Many2one(
        'product.product', string='Product', required=True)
    name = fields.Text(
        string='Description', compute='_compute_name',
        store=True, readonly=False, precompute=True)
    quantity = fields.Float(string='Quantity', default=1.0)
    uom_id = fields.Many2one(
        'uom.uom', string='UoM', compute='_compute_uom_id',
        store=True, readonly=False, precompute=True)

    @api.depends('product_id')
    def _compute_name(self):
        for line in self:
            line.name = line.product_id.display_name

    @api.depends('product_id')
    def _compute_uom_id(self):
        for line in self:
            line.uom_id = line.product_id.uom_id

    # Lines follow their parent request: the same draft/procurement guard
    # applies, so the API cannot change the lines of a submitted request.
    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines.mapped('request_id')._check_editable()
        return lines

    def write(self, vals):
        self.mapped('request_id')._check_editable()
        return super().write(vals)

    def unlink(self):
        self.mapped('request_id')._check_editable()
        return super().unlink()
