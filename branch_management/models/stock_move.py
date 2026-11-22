# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.fields import Domain


class StockMove(models.Model):
    _inherit = 'stock.move'

    branch_id = fields.Many2one(
        'branch.branch', string='Branch',
        domain=lambda self: [
            ('id', 'in', self.env.user.with_context(active_test=False).branch_visible_ids.ids),
        ],
        index=True, check_company=True,
        help='Branch this move belongs to. It comes from the sales order '
             '(through the procurement values), from the transfer it is '
             'created in, or from the move it returns.',
    )

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        """Give the branch to the moves that do not have one yet.

        * a move created inside a transfer takes the branch of the transfer
          (the transfer comes from the context as ``default_picking_id``),
        * a returned move takes the branch of the move it returns.
        """
        context_picking_id = self.env.context.get('default_picking_id')
        for vals in vals_list:
            if vals.get('branch_id'):
                continue
            picking_id = vals.get('picking_id') or context_picking_id
            if picking_id:
                if not isinstance(picking_id, int):
                    picking_id = picking_id.id
                vals['branch_id'] = self.env['stock.picking'].sudo().browse(
                    picking_id).branch_id.id
            elif vals.get('origin_returned_move_id'):
                vals['branch_id'] = self.env['stock.move'].sudo().browse(
                    vals['origin_returned_move_id']).branch_id.id
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Assignment of the moves to a transfer
    # ------------------------------------------------------------------
    def _get_new_picking_values(self):
        """The new transfer is created on the branch of its moves.

        The branch is only set when **all** the moves share the same one:
        ``mapped()`` removes the duplicates, so a move without branch must
        be checked one by one.
        """
        vals = super()._get_new_picking_values()
        branches = self.mapped('branch_id')
        if len(branches) == 1 and all(move.branch_id == branches for move in self):
            vals['branch_id'] = branches.id
        else:
            vals['branch_id'] = False
        return vals

    def _key_assign_picking(self):
        """Moves of two branches never share the same transfer."""
        return super()._key_assign_picking() + (self.branch_id,)

    def _search_picking_for_assignation_domain(self):
        """Same as above, for the transfer that already exists."""
        domain = super()._search_picking_for_assignation_domain()
        return Domain.AND([domain, [('branch_id', '=', self.branch_id.id)]])


class StockRule(models.Model):
    _inherit = 'stock.rule'

    def _get_custom_move_fields(self):
        """Propagate ``branch_id`` from the procurement values to the move."""
        names = super()._get_custom_move_fields()
        return names + ['branch_id']
