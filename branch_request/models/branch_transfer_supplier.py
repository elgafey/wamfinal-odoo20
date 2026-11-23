# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BranchTransferSupplier(models.Model):
    """One row per internal location offered as a supplying branch.

    ``branch.transfer`` keeps a row for every internal location but the
    requesting one: the requester ticks exactly one of them and
    ``from_location_id`` is computed from that tick.  A normal model (not a
    transient one) because the rows are saved with the transfer.

    The ``location_id`` many2one is technical and never appears in the
    views.  It must NOT be flagged ``bypass_search_access``: that flag makes
    the ORM check the current user's read access on the location whenever
    the field is written (odoo/orm/models.py, create()), which is exactly
    the access error an employee got when saving a transfer with a ticked
    supplying branch he may not read.  The employee's form only round-trips
    the plain integer ``location_ref``; ``create()`` resolves it back into
    ``location_id`` with sudo(), and ``branch.transfer`` rebuilds the rows
    server side with sudo().
    """

    _name = 'branch.transfer.supplier'
    _description = 'Branch Transfer Supplier'
    _order = 'id'
    _rec_name = 'location_name'

    transfer_id = fields.Many2one(
        'branch.transfer', string='Transfer', required=True,
        ondelete='cascade', index=True)
    location_id = fields.Many2one(
        'stock.location', string='Branch', required=True, index=True,
        domain=[('usage', '=', 'internal')],
        help='Technical link to the branch, written by the server only.  '
             'The label below is what is shown to everybody.')
    location_ref = fields.Integer(
        string='Location Reference', compute='_compute_location_ref',
        store=True, readonly=True, precompute=True,
        help='Technical copy of the location id, so the form can round-trip '
             'a row without ever requesting the stock.location many2one.  '
             'Resolved back into location_id by create(), with sudo().')
    location_name = fields.Char(
        string='Location', compute='_compute_location_name',
        store=True, readonly=True, precompute=True,
        help='Complete name of the branch, read with sudo() when the row '
             'is created.')
    selected = fields.Boolean(
        string='Select', default=False,
        help='Tick exactly one supplying branch.')

    @api.depends('location_id')
    def _compute_location_ref(self):
        # sudo: the employee may not read the supplying branch location.
        for rec in self:
            rec.location_ref = rec.sudo().location_id.id or False

    @api.depends('location_id.complete_name')
    def _compute_location_name(self):
        for rec in self:
            rec.location_name = rec.sudo().location_id.complete_name or ''

    @api.constrains('selected')
    def _check_single_selected(self):
        for line in self:
            if not line.selected or not line.transfer_id:
                continue
            others = line.transfer_id.supplier_line_ids.filtered(
                lambda row: row.selected and row != line)
            if others:
                raise UserError(_('Choose only one supplying branch'))

    @api.model_create_multi
    def create(self, vals_list):
        # The web form never sends the location_id many2one: it echoes the
        # technical location_ref instead.  Resolve it here with sudo (the
        # employee may not read the supplying branch location) and drop the
        # rows that do not match an internal location: a row without its
        # location is meaningless and would only fail the whole save.
        # branch.transfer rebuilds its list right after, so the location is
        # added back with its value.
        Location = self.env['stock.location'].sudo()
        resolved = []
        for vals in vals_list:
            vals = dict(vals)
            ref = vals.pop('location_ref', None)
            if not vals.get('location_id') and ref:
                vals['location_id'] = ref
            location = Location.browse(vals.get('location_id')).exists()
            if not location or location.usage != 'internal':
                continue
            resolved.append(vals)
        if not resolved:
            return self.browse()
        return super().create(resolved)
