# -*- coding: utf-8 -*-
from odoo import fields, models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    branch_id = fields.Many2one(
        'branch.branch', string='Branch',
        domain=lambda self: [
            ('id', 'in', self.env.user.with_context(active_test=False).branch_visible_ids.ids),
        ],
        index=True, check_company=True, tracking=True,
        help='Branch that handles this transfer. It is taken from the moves '
             'when the transfer is created, and it is given back to the '
             'moves of the transfer when you change it here.',
    )

    def write(self, vals):
        res = super().write(vals)
        if 'branch_id' in vals:
            # a transfer and its moves must stay on the same branch
            for picking in self:
                moves = picking.move_ids.filtered(
                    lambda move: move.branch_id != picking.branch_id)
                if moves:
                    moves.sudo().write({'branch_id': picking.branch_id.id})
        return res
