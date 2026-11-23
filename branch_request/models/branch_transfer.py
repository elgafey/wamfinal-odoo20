# -*- coding: utf-8 -*-
from markupsafe import Markup

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import format_datetime
from odoo.tools.sql import drop_not_null, table_exists

PROCUREMENT_GROUP = 'branch_request.group_branch_request_procurement'
TRANSIT_LOCATION_XMLID = 'branch_request.branch_transfer_location_transit'
ACTIVITY_TODO_XMLID = 'mail.mail_activity_data_todo'

# Fields a responsible user is allowed to change while the transfer is not
# a draft.  They are filled in by the workflow wizards; everything else is
# editable in the draft state only (or by the procurement team).
WORKFLOW_FIELDS = {
    'state', 'rejection_reason', 'sent_by_id', 'sent_date',
    'received_by_id', 'received_date', 'out_picking_id', 'in_picking_id',
}


class BranchTransfer(models.Model):
    """A branch asks another branch for goods.

    The supplying branch approves and sends the goods to a single global
    transit location; the requesting branch then receives them from that
    transit location.  Two internal pickings are created (one per leg) and
    are validated by the system, so employees need no inventory rights.
    """

    _name = 'branch.transfer'
    _description = 'Branch Transfer'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(
        string='Reference', readonly=True, copy=False, default='/', index=True)
    requester_id = fields.Many2one(
        'res.users', string='Requester', readonly=True, index=True,
        default=lambda self: self.env.user, copy=False, tracking=True)
    to_location_id = fields.Many2one(
        'stock.location', string='Requesting branch', required=True, index=True,
        domain=lambda self: self._domain_to_location(),
        bypass_search_access=True,
        help='Branch that receives the goods.  Referencing it never depends '
             'on the access rights on stock.location.')
    to_location_name = fields.Char(
        string='Requesting Branch', compute='_compute_to_location_name',
        store=True, readonly=True,
        help='Complete name of the requesting branch, read with sudo().')
    from_location_id = fields.Many2one(
        'stock.location', string='Supplying branch',
        compute='_compute_from_location_id', store=True, readonly=True,
        index=True, bypass_search_access=True,
        domain="[('usage', '=', 'internal'), ('id', '!=', to_location_id)]",
        help='Branch that sends the goods.  Taken from the ticked row of the '
             'supplying branch list.  Referencing it never depends on the '
             'access rights on stock.location.')
    from_location_name = fields.Char(
        string='Supplying Branch', compute='_compute_from_location_name',
        store=True, readonly=True,
        help='Complete name of the supplying branch, read with sudo().')
    supplier_line_ids = fields.One2many(
        'branch.transfer.supplier', 'transfer_id', string='Supplying branches',
        copy=False)
    request_date = fields.Date(
        string='Request Date', default=fields.Date.context_today, tracking=True)
    note = fields.Text(string='Note')
    state = fields.Selection(
        [('draft', 'Draft'), ('submitted', 'Submitted'),
         ('in_transit', 'In Transit'), ('received', 'Received'),
         ('rejected', 'Rejected'), ('cancelled', 'Cancelled')],
        string='Status', default='draft', required=True, tracking=True, copy=False)
    line_ids = fields.One2many(
        'branch.transfer.line', 'transfer_id', string='Products', copy=True)
    rejection_reason = fields.Text(string='Rejection Reason', copy=False)
    sent_by_id = fields.Many2one(
        'res.users', string='Sent by', readonly=True, copy=False)
    sent_date = fields.Datetime(string='Sent on', readonly=True, copy=False)
    received_by_id = fields.Many2one(
        'res.users', string='Received by', readonly=True, copy=False)
    received_date = fields.Datetime(string='Received on', readonly=True, copy=False)
    out_picking_id = fields.Many2one(
        'stock.picking', string='Outgoing Transfer', readonly=True, copy=False,
        help='Supplying branch -> Branch Transit.')
    in_picking_id = fields.Many2one(
        'stock.picking', string='Incoming Transfer', readonly=True, copy=False,
        help='Branch Transit -> Requesting branch.')
    out_picking_count = fields.Integer(compute='_compute_picking_count')
    in_picking_count = fields.Integer(compute='_compute_picking_count')
    has_difference = fields.Boolean(
        string='With Difference', compute='_compute_has_difference', store=True,
        help='True when at least one line was not counted as sent.')
    # Stored so that the record rules never have to read stock.location or
    # branch.store.keeper.
    from_user_ids = fields.Many2many(
        'res.users', 'branch_transfer_from_user_rel', 'transfer_id', 'user_id',
        string='Supplying Responsible Users', compute='_compute_from_user_ids',
        store=True, readonly=True, copy=False)
    to_user_ids = fields.Many2many(
        'res.users', 'branch_transfer_to_user_rel', 'transfer_id', 'user_id',
        string='Requesting Responsible Users', compute='_compute_to_user_ids',
        store=True, readonly=True, copy=False)
    is_procurement = fields.Boolean(compute='_compute_user_flags')
    is_requester = fields.Boolean(compute='_compute_user_flags')
    is_supplying = fields.Boolean(compute='_compute_user_flags')
    is_requesting = fields.Boolean(compute='_compute_user_flags')

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends('from_location_id.branch_transfer_keeper_ids.user_ids')
    def _compute_from_user_ids(self):
        users_by_location = self._keeper_users_by_location()
        for rec in self:
            rec.from_user_ids = [Command.set(users_by_location.get(
                rec.sudo().from_location_id.id, []))]

    @api.depends('to_location_id.branch_transfer_keeper_ids.user_ids')
    def _compute_to_user_ids(self):
        users_by_location = self._keeper_users_by_location()
        for rec in self:
            rec.to_user_ids = [Command.set(users_by_location.get(
                rec.sudo().to_location_id.id, []))]

    @api.depends('to_location_id.complete_name')
    def _compute_to_location_name(self):
        for rec in self:
            rec.to_location_name = rec.sudo().to_location_id.complete_name or ''

    @api.depends('supplier_line_ids.selected', 'supplier_line_ids.location_name')
    def _compute_from_location_name(self):
        for rec in self:
            ticked = rec.sudo().supplier_line_ids.filtered('selected')
            rec.from_location_name = ticked[:1].location_name or ''

    @api.model
    def _keeper_users_by_location(self):
        """{location id: [user ids]} for every store keeper record."""
        result = {}
        keepers = self.env['branch.store.keeper'].sudo().search([])
        for keeper in keepers:
            result.setdefault(keeper.location_id.id, []).extend(keeper.user_ids.ids)
        return result

    @api.depends('line_ids.difference_qty')
    def _compute_has_difference(self):
        for rec in self:
            rec.has_difference = any(rec.line_ids.mapped('difference_qty'))

    @api.depends('out_picking_id', 'in_picking_id')
    def _compute_picking_count(self):
        for rec in self:
            rec.out_picking_count = 1 if rec.sudo().out_picking_id else 0
            rec.in_picking_count = 1 if rec.sudo().in_picking_id else 0

    @api.depends('requester_id', 'from_user_ids', 'to_user_ids')
    @api.depends_context('uid')
    def _compute_user_flags(self):
        user = self.env.user
        is_procurement = user.has_group(PROCUREMENT_GROUP)
        for rec in self:
            rec.is_procurement = is_procurement
            rec.is_requester = rec.requester_id.id == user.id
            rec.is_supplying = is_procurement or user.id in rec.from_user_ids.ids
            rec.is_requesting = is_procurement or user.id in rec.to_user_ids.ids

    @api.depends('supplier_line_ids.selected')
    def _compute_from_location_id(self):
        for rec in self:
            ticked = rec.supplier_line_ids.filtered('selected')
            rec.from_location_id = ticked[:1].sudo().location_id if ticked else False

    @api.constrains('supplier_line_ids')
    def _check_single_supplier(self):
        """Only one supplying branch may be ticked."""
        for rec in self:
            if len(rec.supplier_line_ids.filtered('selected')) > 1:
                raise UserError(_('Choose only one supplying branch'))

    # ------------------------------------------------------------------
    # Supplying branch list (checkboxes instead of a dropdown)
    # ------------------------------------------------------------------
    @api.onchange('to_location_id')
    def _onchange_to_location_id(self):
        commands = self._supplier_line_commands()
        if commands:
            self.supplier_line_ids = commands

    def _supplier_locations(self):
        """Every internal location but the requesting one, read with sudo so
        that every user gets the same complete list."""
        domain = [('usage', '=', 'internal'), ('active', '=', True)]
        if self.to_location_id:
            domain.append(('id', '!=', self.to_location_id.id))
        return self.env['stock.location'].sudo().search(
            domain, order='complete_name, id')

    def _supplier_line_commands(self):
        """Commands bringing the list in line with the requesting branch.

        A row whose location is still offered is kept as it is, a missing
        location is created (always with its ``location_id``) and a row whose
        location disappeared is dropped.  Rows that are not saved yet cannot
        be addressed by their id: the whole list is rebuilt in that case.

        The rows are identified by their technical ``location_ref``: the
        employee's form holds no stock.location many2one, so ``location_id``
        is not part of the values the client sends back.
        """
        self.ensure_one()
        if not self.to_location_id:
            return [Command.clear()]
        locations = self._supplier_locations()
        rows = list(self.supplier_line_ids)
        if any(not isinstance(row.id, int) for row in rows):
            ticked = {row.location_ref for row in rows if row.selected}
            return [Command.clear()] + [
                Command.create({
                    'location_id': location.id,
                    'selected': location.id in ticked,
                })
                for location in locations
            ]
        wanted = {location.id for location in locations}
        listed = {row.location_ref for row in rows}
        commands = [
            Command.delete(row.id)
            for row in rows if row.location_ref not in wanted
        ]
        commands += [
            Command.create({'location_id': location.id, 'selected': False})
            for location in locations if location.id not in listed
        ]
        return commands

    def _rebuild_supplier_lines(self):
        """Server side twin of the onchange: keep the list in step with the
        requesting branch, keeping the ticked row when it is still valid."""
        self.ensure_one()
        if self.state != 'draft':
            return
        # Read before touching the rows: creating or removing one triggers
        # the recomputation of from_location_id.
        previous = self.from_location_id
        Supplier = self.env['branch.transfer.supplier'].sudo()
        if not self.to_location_id:
            if self.supplier_line_ids:
                self.supplier_line_ids.sudo().unlink()
            return
        locations = self._supplier_locations()
        wanted = set(locations.ids)
        rows = list(self.supplier_line_ids)
        keep = {}
        for row in rows:
            # sudo: the employee may not read the supplying branch
            # location, and the plain many2one value would silently come
            # back empty in his environment.
            loc_id = row.sudo().location_id.id
            if loc_id in wanted and (loc_id not in keep or (
                    row.selected and not keep[loc_id].selected)):
                keep[loc_id] = row
        keep_ids = {row.id for row in keep.values()}
        for row in rows:
            if row.id not in keep_ids:
                row.sudo().unlink()
        missing = [lid for lid in locations.ids if lid not in keep]
        if missing:
            Supplier.create([
                {'transfer_id': self.id, 'location_id': lid}
                for lid in missing
            ])
        # Nothing ticked but the transfer already knows its supplying branch
        # (a record created before the checkbox list existed): tick it back.
        if not previous or self.supplier_line_ids.filtered('selected'):
            return
        row = self.supplier_line_ids.filtered(
            lambda candidate: candidate.sudo().location_id.id == previous.id)
        if row:
            row[:1].sudo().selected = True

    @staticmethod
    def _order_supplier_commands(commands):
        """Untick commands must be applied before tick commands: switching
        the ticked row would otherwise transiently leave two rows ticked and
        trip the single selection constraint."""
        if not isinstance(commands, (list, tuple)):
            return commands

        def unticks(command):
            return (len(command) > 2 and command[0] == Command.UPDATE
                    and isinstance(command[2], dict)
                    and command[2].get('selected') is not None
                    and not command[2]['selected'])

        head = [command for command in commands if unticks(command)]
        if not head:
            return commands
        return head + [command for command in commands
                       if not unticks(command)]

    # ------------------------------------------------------------------
    # Domains
    # ------------------------------------------------------------------
    def _domain_to_location(self):
        """Internal locations the current user is responsible for; the
        procurement team may pick any location that has a store keeper."""
        user = self.env.user
        keepers = self.env['branch.store.keeper'].sudo()
        if user.has_group(PROCUREMENT_GROUP):
            locations = keepers.search([]).location_id
        else:
            locations = keepers.search([('user_ids', 'in', user.id)]).location_id
        return [('usage', '=', 'internal'), ('id', 'in', locations.ids)]

    # ------------------------------------------------------------------
    # Create / write / unlink
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('state') and vals['state'] != 'draft':
                raise UserError(_('A new transfer always starts as a draft.'))
            if not vals.get('name') or vals['name'] in ('/', 'New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'branch.transfer') or '/'
        records = super().create(vals_list)
        if not (self.env.su or self.env.user.has_group(PROCUREMENT_GROUP)):
            for rec in records:
                if rec.requester_id.id != self.env.uid:
                    raise AccessError(_(
                        'Only a responsible user of the requesting branch can '
                        'create a transfer for it.'))
                if self.env.uid not in rec.to_user_ids.ids:
                    raise AccessError(_(
                        'You are not a responsible user of the requesting '
                        'branch, so you cannot create a transfer for it.'))
        for rec in records:
            rec._rebuild_supplier_lines()
        return records

    def write(self, vals):
        if vals and 'supplier_line_ids' in vals:
            vals = dict(vals)
            vals['supplier_line_ids'] = self._order_supplier_commands(
                vals['supplier_line_ids'])
        if vals and not (self.env.su
                         or self.env.user.has_group(PROCUREMENT_GROUP)):
            extra = set(vals) - WORKFLOW_FIELDS
            if extra:
                # Regular fields: the requester may change a draft only.
                if any(rec.state != 'draft' for rec in self):
                    raise AccessError(_('Only draft transfers can be changed.'))
            elif 'state' not in vals:
                # Workflow fields are always written together with the state
                # change they belong to, so that nobody can tamper with the
                # pickings or the counted quantities on their own.
                raise AccessError(_(
                    'The follow-up information of a transfer can only be set '
                    'together with a status change.'))
        if 'state' in vals:
            for rec in self:
                rec._check_state_transition(vals['state'])
        res = super().write(vals)
        for rec in self:
            rec._rebuild_supplier_lines()
        return res

    def unlink(self):
        if any(rec.sudo().out_picking_id or rec.sudo().in_picking_id
               for rec in self):
            raise UserError(_(
                'Transfers linked to a stock operation cannot be deleted.'))
        if not (self.env.su or self.env.user.has_group(PROCUREMENT_GROUP)):
            if any(rec.state != 'draft' for rec in self):
                raise AccessError(_('Only draft transfers can be deleted.'))
        return super().unlink()

    @api.private
    def init(self):
        """``from_location_id`` used to be a plain required Many2one: now
        that it is computed from the ticked row, the column has to accept
        NULL so that unticking the last row stays possible."""
        cr = self.env.cr
        if not table_exists(cr, 'branch_transfer'):
            return
        cr.execute("""
            SELECT a.attnotnull FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            WHERE c.oid = 'branch_transfer'::regclass
              AND a.attname = 'from_location_id'
              AND NOT a.attisdropped
        """)
        row = cr.fetchone()
        if row and row[0]:
            drop_not_null(cr, 'branch_transfer', 'from_location_id')

    @api.model
    def _backfill_supplier_lines(self):
        """Give every draft transfer created before the checkbox list
        existed its list of supplying branches, ticking the branch it used
        to be sent from.  Called from the module data, safe to run again."""
        Supplier = self.env['branch.transfer.supplier'].sudo()
        internal = self.env['stock.location'].sudo().search(
            [('usage', '=', 'internal'), ('active', '=', True)],
            order='complete_name, id')
        transfers = self.sudo().search([
            ('state', '=', 'draft'),
            ('supplier_line_ids', '=', False),
            ('from_location_id', '!=', False),
        ])
        for transfer in transfers:
            locations = internal.filtered(
                lambda location: location != transfer.to_location_id)
            if not locations:
                continue
            Supplier.create([
                {'transfer_id': transfer.id,
                 'location_id': location.id,
                 'selected': location == transfer.from_location_id}
                for location in locations
            ])

    @api.constrains('to_location_id', 'from_location_id')
    def _check_locations(self):
        for rec in self:
            # sudo: this runs when a requester ticks a supplying branch, and
            # the supplying branch is a location he is not responsible for
            # and may not read (the requesting branch, on the other hand, is
            # one of his own locations).
            to_location = rec.sudo().to_location_id
            from_location = rec.sudo().from_location_id
            for location in (to_location, from_location):
                if not location:
                    continue
                if location.usage != 'internal':
                    raise ValidationError(_(
                        'Only internal locations can be used as branches.'))
            # The supplying branch may be picked before its store keeper
            # exists: action_submit() reports that case with a clearer
            # message than a constraint would.
            if to_location and not to_location.branch_transfer_keeper_ids:
                raise ValidationError(_(
                    'The location "%s" has no store keeper. Please '
                    'configure one first.', to_location.display_name))
            if to_location and to_location == from_location:
                raise ValidationError(_(
                    'The requesting and supplying branches must be different.'))

    # ------------------------------------------------------------------
    # Permission helpers (Python enforcement of the workflow rules)
    # ------------------------------------------------------------------
    def _check_can_supply(self):
        if self.env.su or self.env.user.has_group(PROCUREMENT_GROUP):
            return
        user = self.env.user
        if any(user.id not in rec.from_user_ids.ids for rec in self):
            raise AccessError(_(
                'Only a responsible user of the supplying branch can do this.'))

    def _check_can_receive(self):
        if self.env.su or self.env.user.has_group(PROCUREMENT_GROUP):
            return
        user = self.env.user
        if any(user.id not in rec.to_user_ids.ids for rec in self):
            raise AccessError(_(
                'Only a responsible user of the requesting branch can do this.'))

    def _check_can_cancel(self):
        if self.env.su or self.env.user.has_group(PROCUREMENT_GROUP):
            return
        user = self.env.user
        if any(rec.requester_id.id != user.id for rec in self):
            raise AccessError(_(
                'Only the requester or the procurement team can cancel a '
                'transfer.'))

    def _check_state_transition(self, target):
        """Validate both the state change itself and who may perform it."""
        self.ensure_one()
        user = self.env.user
        is_procurement = self.env.su or user.has_group(PROCUREMENT_GROUP)
        current = self.state
        if target == current:
            # Nothing to do: leave the record alone instead of refusing a
            # harmless no-op (a client may resend the current status).
            return
        if target == 'submitted':
            if current != 'draft':
                raise UserError(_('Only a draft transfer can be submitted.'))
            if not (self.env.su or self.requester_id.id == user.id):
                raise AccessError(_('Only the requester can submit a transfer.'))
        elif target == 'rejected':
            if current != 'submitted':
                raise UserError(_('Only a submitted transfer can be rejected.'))
            if not (self.env.su or is_procurement
                    or user.id in self.from_user_ids.ids):
                raise AccessError(_(
                    'Only the supplying branch can reject a transfer.'))
        elif target == 'in_transit':
            if current != 'submitted':
                raise UserError(_('Only a submitted transfer can be sent.'))
            if not (self.env.su or is_procurement
                    or user.id in self.from_user_ids.ids):
                raise AccessError(_(
                    'Only the supplying branch can send a transfer.'))
        elif target == 'received':
            if current != 'in_transit':
                raise UserError(_('Only a transfer in transit can be received.'))
            if not (self.env.su or is_procurement
                    or user.id in self.to_user_ids.ids):
                raise AccessError(_(
                    'Only the requesting branch can receive a transfer.'))
        elif target == 'cancelled':
            if current not in ('draft', 'submitted'):
                raise UserError(_(
                    'A transfer whose goods have been sent cannot be '
                    'cancelled.'))
            if not (self.env.su or is_procurement
                    or self.requester_id.id == user.id):
                raise AccessError(_(
                    'Only the requester or the procurement team can cancel a '
                    'transfer.'))
        elif target == 'draft':
            if current not in ('rejected', 'cancelled'):
                raise UserError(_(
                    'Only a rejected or cancelled transfer can be reset to '
                    'draft.'))
            if not (self.env.su or self.requester_id.id == user.id):
                raise AccessError(_(
                    'Only the requester can reset a transfer to draft.'))
        else:
            raise UserError(_('Unknown status: %s.', target))

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only a draft transfer can be submitted.'))
            if not (self.env.su or rec.requester_id.id == self.env.uid):
                raise AccessError(_('Only the requester can submit a transfer.'))
            if not rec.line_ids:
                raise UserError(_(
                    'Add at least one product line before submitting.'))
            if any(line.requested_qty <= 0 for line in rec.line_ids):
                raise UserError(_(
                    'All requested quantities must be greater than zero.'))
            if len(rec.supplier_line_ids.filtered('selected')) != 1:
                raise UserError(_('Please tick the supplying branch.'))
            keepers = rec.sudo().from_location_id.branch_transfer_keeper_ids
            if not keepers or not any(keepers.mapped('user_ids')):
                raise UserError(_(
                    'This branch has no responsible store keeper. Ask the '
                    'Procurement Team to add one in Store Keepers.'))
            rec.write({'state': 'submitted'})
            rec._notify_supplying()
        return True

    def action_cancel(self):
        for rec in self:
            if rec.state not in ('draft', 'submitted'):
                raise UserError(_(
                    'Only a draft or submitted transfer can be cancelled.'))
            rec._check_can_cancel()
            rec.write({'state': 'cancelled'})
            rec.message_post(body=_('Transfer cancelled by %s.',
                                    self.env.user.name))
        return True

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state not in ('rejected', 'cancelled'):
                raise UserError(_(
                    'Only a rejected or cancelled transfer can be reset to '
                    'draft.'))
            if not (self.env.su or rec.requester_id.id == self.env.uid):
                raise AccessError(_(
                    'Only the requester can reset a transfer to draft.'))
            rec.write({'state': 'draft', 'rejection_reason': False})
            rec.message_post(body=_('Transfer reset to draft by %s.',
                                    self.env.user.name))
        return True

    def action_open_reject_wizard(self):
        self.ensure_one()
        self._check_can_supply()
        if self.state != 'submitted':
            raise UserError(_('Only a submitted transfer can be rejected.'))
        return self._open_wizard(
            'branch.transfer.reject.wizard', _('Reject'),
            {'transfer_id': self.id})

    def action_open_send_wizard(self):
        self.ensure_one()
        self._check_can_supply()
        if self.state != 'submitted':
            raise UserError(_('Only a submitted transfer can be sent.'))
        if not self.line_ids:
            raise UserError(_('This transfer has no product lines.'))
        return self._open_wizard(
            'branch.transfer.send.wizard', _('Approve and Send'),
            {
                'transfer_id': self.id,
                'line_ids': [Command.create({
                    'transfer_line_id': line.id,
                    'product_id': line.product_id.id,
                    'requested_qty': line.requested_qty,
                    'available_qty': line.available_qty,
                    'qty_to_send': line.requested_qty,
                }) for line in self.line_ids],
            })

    def action_open_receive_wizard(self):
        self.ensure_one()
        self._check_can_receive()
        if self.state != 'in_transit':
            raise UserError(_('Only a transfer in transit can be received.'))
        if not self.line_ids:
            raise UserError(_('This transfer has no product lines.'))
        return self._open_wizard(
            'branch.transfer.receive.wizard', _('Receive'),
            {
                'transfer_id': self.id,
                'line_ids': [Command.create({
                    'transfer_line_id': line.id,
                    'product_id': line.product_id.id,
                    'sent_qty': line.sent_qty,
                    'qty_counted': line.sent_qty,
                }) for line in self.line_ids],
            })

    @api.model
    def _open_wizard(self, model, title, vals):
        """Create the wizard then hand it over to the client."""
        wizard = self.env[model].create(vals)
        return {
            'type': 'ir.actions.act_window',
            'name': title,
            'res_model': model,
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_view_out_picking(self):
        self.ensure_one()
        if not (self.env.su or self.env.user.has_group(PROCUREMENT_GROUP)):
            raise AccessError(_(
                'Only the procurement team can open the stock operations.'))
        if not self.out_picking_id:
            raise UserError(_('No outgoing stock operation on this transfer.'))
        return {
            'type': 'ir.actions.act_window',
            'name': self.out_picking_id.display_name,
            'res_model': 'stock.picking',
            'view_mode': 'form',
            'res_id': self.out_picking_id.id,
        }

    def action_view_in_picking(self):
        self.ensure_one()
        if not (self.env.su or self.env.user.has_group(PROCUREMENT_GROUP)):
            raise AccessError(_(
                'Only the procurement team can open the stock operations.'))
        if not self.in_picking_id:
            raise UserError(_('No incoming stock operation on this transfer.'))
        return {
            'type': 'ir.actions.act_window',
            'name': self.in_picking_id.display_name,
            'res_model': 'stock.picking',
            'view_mode': 'form',
            'res_id': self.in_picking_id.id,
        }

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------
    def _notify_supplying(self):
        self.ensure_one()
        users = self.from_user_ids
        if not users:
            return
        self.message_post(
            body=_('A goods transfer has been requested from your branch.'),
            partner_ids=users.sudo().partner_id.ids)
        for user in users:
            self.activity_schedule(
                act_type_xmlid=ACTIVITY_TODO_XMLID,
                user_id=user.id,
                summary=_('Review branch transfer %s', self.name),
                note=_('Approve and send the goods requested by %s.',
                       self.sudo().to_location_id.display_name))

    def _notify_requesting(self):
        self.ensure_one()
        users = self.to_user_ids
        if not users:
            return
        self.message_post(
            body=_('The goods have been sent to the branch transit '
                   'location. Please receive them.'),
            partner_ids=users.sudo().partner_id.ids)
        for user in users:
            self.activity_schedule(
                act_type_xmlid=ACTIVITY_TODO_XMLID,
                user_id=user.id,
                summary=_('Receive branch transfer %s', self.name),
                note=_('The goods are waiting in the branch transit '
                       'location.'))

    def _notify_rejection(self):
        self.ensure_one()
        requester = self.requester_id
        if not requester:
            return
        self.message_post(
            body=_('Transfer rejected by %(user)s. Reason: %(reason)s',
                   user=self.env.user.name,
                   reason=self.rejection_reason or '-'),
            partner_ids=requester.sudo().partner_id.ids)

    def _post_receive_message(self):
        """Accountability message once the goods have been counted."""
        self.ensure_one()
        differences = self.line_ids.filtered(lambda line: line.difference_qty)
        if not differences:
            self.message_post(body=_('Transfer received by %s.',
                                     self.env.user.name))
            return
        items = Markup('').join(
            Markup('<li>%s</li>') % _(
                '%(product)s: sent %(sent)s, counted %(counted)s, '
                'difference %(diff)s',
                product=line.product_id.display_name,
                sent=line.sent_qty,
                counted=line.received_qty,
                diff=line.difference_qty)
            for line in differences)
        header = _(
            'Transfer received with differences by %(receiver)s. '
            'Sent by %(sender)s on %(sent_date)s, received on '
            '%(received_date)s:',
            receiver=self.received_by_id.name or self.env.user.name,
            sender=self.sent_by_id.name or '-',
            sent_date=format_datetime(self.env, self.sent_date)
            if self.sent_date else '-',
            received_date=format_datetime(self.env, self.received_date)
            if self.received_date else '-')
        self.message_post(
            body=Markup('<p>%s</p><ul>%s</ul>') % (header, items))

    # ------------------------------------------------------------------
    # Stock operations: always executed with sudo() after the permission
    # checks, so that employees need no inventory access rights.
    # ------------------------------------------------------------------
    @api.model
    def _get_transit_location(self):
        location = self.env.ref(TRANSIT_LOCATION_XMLID, raise_if_not_found=False)
        if not location:
            raise UserError(_(
                'The branch transit location is missing. Please upgrade the '
                'Branch Request application.'))
        return location.sudo()

    @api.model
    def _get_internal_picking_type(self, location):
        """Internal operation type of the warehouse owning ``location``.

        Read with sudo: the responsible users sending or receiving have no
        access to stock.warehouse, stock.picking.type nor stock.location."""
        picking_type_model = self.env['stock.picking.type'].sudo()
        location = location.sudo()
        warehouse = location.warehouse_id
        picking_type = picking_type_model.browse()
        if warehouse:
            picking_type = picking_type_model.search(
                [('code', '=', 'internal'), ('warehouse_id', '=', warehouse.id)],
                limit=1)
        if not picking_type and location.company_id:
            picking_type = picking_type_model.search(
                [('code', '=', 'internal'),
                 ('company_id', '=', location.company_id.id)], limit=1)
        if not picking_type:
            picking_type = picking_type_model.search(
                [('code', '=', 'internal')], limit=1)
        if not picking_type:
            raise UserError(_(
                'No internal operation type is available. Please configure a '
                'warehouse with an internal operation type.'))
        return picking_type

    def _create_and_validate_picking(self, location_src, location_dest,
                                     moves_data):
        """Create and fully validate one internal picking.

        :param moves_data: list of (product, quantity, uom); quantities of
                           zero are ignored.
        :return: the validated ``stock.picking``
        """
        self.ensure_one()
        moves_data = [move for move in moves_data if move[1] > 0]
        if not moves_data:
            raise UserError(_('There is no quantity to move.'))
        vals = {
            'picking_type_id': self._get_internal_picking_type(location_src).id,
            'location_id': location_src.id,
            'location_dest_id': location_dest.id,
            'origin': self.name,
            'user_id': self.env.user.id,
            'move_ids': [Command.create({
                'product_id': product.id,
                'product_uom_qty': qty,
                'uom_id': uom.id,
                'location_id': location_src.id,
                'location_dest_id': location_dest.id,
            }) for product, qty, uom in moves_data],
        }
        picking = self.env['stock.picking'].sudo().create(vals)
        picking.with_context(skip_zero_demand_check=True).action_confirm()
        for move in picking.move_ids:
            # The quantity creates the move lines, the second write flags
            # them as picked (the inverses run inside write()).
            move.quantity = move.product_uom_qty
            move.picked = True
        # No backorder wizard, no immediate transfer popup: the picking is
        # always validated for the whole quantity in one go.
        picking.with_context(
            skip_backorder=True,
            picking_ids_not_to_backorder=[picking.id],
        ).button_validate()
        if picking.state != 'done':
            raise UserError(_(
                'The stock operation %s could not be validated.', picking.name))
        return picking
