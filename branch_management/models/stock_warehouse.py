# -*- coding: utf-8 -*-
from odoo import api, fields, models


class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    branch_ids = fields.One2many(
        'branch.branch', 'warehouse_id',
        string='Branches',
        help='Technical inverse of the "Warehouse" field of the branch.',
    )
    branch_id = fields.Many2one(
        'branch.branch', string='Branch',
        compute='_compute_branch_id', store=True, readonly=True,
        help='Branch that works with this warehouse. It is maintained from '
             'the branch form: set "Warehouse" on the branch and this field '
             'follows automatically. It is never set by hand.',
    )

    @api.depends('branch_ids')
    def _compute_branch_id(self):
        # one warehouse belongs to at most one branch (branch constraint),
        # so the first (and only) branch of the warehouse is the answer.
        for warehouse in self:
            warehouse.branch_id = warehouse.branch_ids[:1]
