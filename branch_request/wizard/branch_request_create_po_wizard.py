# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

PROCUREMENT_GROUP = 'branch_request.group_branch_request_procurement'


class BranchRequestCreatePoWizard(models.TransientModel):
    _name = 'branch.request.create.po.wizard'
    _description = 'Create RFQ from Branch Requests'

    partner_id = fields.Many2one(
        'res.partner', string='Vendor', required=True)
    request_ids = fields.Many2many(
        'branch.request', string='Requests')
    merge_lines = fields.Boolean(
        string='Merge identical products', default=True)
    warning_message = fields.Text(
        string='Warning', compute='_compute_warning_message')

    @api.depends('request_ids')
    def _compute_warning_message(self):
        for wiz in self:
            already = wiz.request_ids.filtered('purchase_order_ids')
            if already:
                wiz.warning_message = _(
                    'Some selected requests already have a purchase order: '
                    '%s. A new RFQ can still be created.',
                    ', '.join(already.mapped('name')))
            else:
                wiz.warning_message = ''

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'request_ids' in fields_list and not res.get('request_ids'):
            active_ids = self.env.context.get('active_ids') or []
            res['request_ids'] = [(6, 0, active_ids)]
        return res

    def _check_procurement(self):
        if not (self.env.su or self.env.user.has_group(PROCUREMENT_GROUP)):
            raise AccessError(
                _('Only the procurement team may create RFQs.'))

    def _prepare_order_lines(self, requests):
        """ Build the purchase.order.line create values from the request
        lines.  No price is set: purchase.order.line computes the unit
        price itself from the vendor price lists (or the standard price). """
        self.ensure_one()
        vals_list = []
        if self.merge_lines:
            merged = {}
            for request in requests:
                for line in request.line_ids:
                    key = (line.product_id.id, line.uom_id.id)
                    if key in merged:
                        merged[key]['product_qty'] += line.quantity
                    else:
                        merged[key] = {
                            'product_id': line.product_id.id,
                            'product_qty': line.quantity,
                            'uom_id': line.uom_id.id,
                            'name': line.name,
                        }
            vals_list = list(merged.values())
        else:
            for request in requests:
                for line in request.line_ids:
                    vals_list.append({
                        'product_id': line.product_id.id,
                        'product_qty': line.quantity,
                        'uom_id': line.uom_id.id,
                        'name': line.name,
                    })
        return vals_list

    def action_create_rfq(self):
        self.ensure_one()
        self._check_procurement()

        requests = self.request_ids
        if not requests:
            raise UserError(_('Select at least one request.'))

        not_approved = requests.filtered(lambda r: r.state != 'approved')
        if not_approved:
            raise UserError(_(
                'Only approved requests can be converted to a RFQ. '
                'These requests are not approved: %s',
                ', '.join(not_approved.mapped('name'))))

        po = self.env['purchase.order'].create({
            'partner_id': self.partner_id.id,
            'origin': ', '.join(requests.mapped('name')),
            'order_line': [
                (0, 0, vals) for vals in self._prepare_order_lines(requests)
            ],
        })

        for request in requests:
            request.purchase_order_ids = [(4, po.id)]
            request.message_post(
                body=_('RFQ %s created from this request', po.name))

        return {
            'type': 'ir.actions.act_window',
            'name': po.name,
            'res_model': 'purchase.order',
            'res_id': po.id,
            'view_mode': 'form',
            'target': 'current',
        }
