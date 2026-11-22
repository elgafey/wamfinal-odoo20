# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

PROCUREMENT_GROUP = 'branch_request.group_branch_request_procurement'


class BranchRequest(models.Model):
    _name = 'branch.request'
    _description = 'Branch Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(
        string='Reference', readonly=True, copy=False, default='New', index=True)
    requester_id = fields.Many2one(
        'res.users', string='Requester', readonly=True,
        default=lambda self: self.env.user, index=True, tracking=True)
    department_id = fields.Many2one(
        'hr.department', string='Department',
        compute='_compute_department_id', store=True, readonly=True)
    request_date = fields.Date(
        string='Request Date', default=fields.Date.context_today, tracking=True)
    required_date = fields.Date(string='Needed By', tracking=True)
    priority = fields.Selection(
        [('low', 'Low'), ('normal', 'Normal'), ('urgent', 'Urgent')],
        string='Priority', default='normal', tracking=True)
    reason = fields.Text(string='Reason')
    state = fields.Selection(
        [('draft', 'Draft'), ('submitted', 'Submitted'),
         ('approved', 'Approved'), ('rejected', 'Rejected'), ('done', 'Done')],
        string='Status', default='draft', required=True, tracking=True, copy=False)
    line_ids = fields.One2many(
        'branch.request.line', 'request_id', string='Products', copy=True)
    rejection_reason = fields.Text(string='Rejection Reason', copy=False)
    is_procurement = fields.Boolean(
        string='Is Procurement Team', compute='_compute_is_procurement')

    @api.depends('requester_id')
    def _compute_department_id(self):
        for rec in self:
            rec.department_id = rec.requester_id.department_id

    @api.depends_context('uid')
    def _compute_is_procurement(self):
        is_procurement = self.env.user.has_group(PROCUREMENT_GROUP)
        for rec in self:
            rec.is_procurement = is_procurement

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('branch.request') or 'New'
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Edit guards: the requester may change a request only while it is a
    # draft, the procurement team at any time.  Enforced here as well as
    # in the form view readonly expressions, so the API cannot bypass it.
    # ------------------------------------------------------------------
    def _check_editable(self):
        if self.env.su or self.env.user.has_group(PROCUREMENT_GROUP):
            return
        if any(rec.state != 'draft' for rec in self):
            raise AccessError(_('Only draft requests can be changed by the requester.'))

    def write(self, vals):
        self._check_editable()
        return super().write(vals)

    def unlink(self):
        self._check_editable()
        return super().unlink()

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def _check_procurement(self):
        if not (self.env.su or self.env.user.has_group(PROCUREMENT_GROUP)):
            raise AccessError(_('Only the procurement team may do this.'))

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only a draft request can be submitted.'))
            if not (self.env.su or rec.requester_id == self.env.user):
                raise AccessError(_('Only the requester can submit this request.'))
            rec.state = 'submitted'
            rec._notify_procurement()
        return True

    def _notify_procurement(self):
        """Notify every member of the procurement team in the chatter."""
        group = self.env.ref(PROCUREMENT_GROUP)
        users = self.env['res.users'].sudo().search(
            [('all_group_ids', 'in', [group.id])])
        self.message_post(
            body=_('Request submitted for review by the procurement team.'),
            partner_ids=users.partner_id.ids,
        )

    def action_approve(self):
        self._check_procurement()
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(_('Only a submitted request can be approved.'))
            rec.state = 'approved'
            rec.message_post(body=_('Request approved.'))
        return True

    def action_reject(self):
        self._check_procurement()
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(_('Only a submitted request can be rejected.'))
            if not rec.rejection_reason:
                raise UserError(_('Set a rejection reason before rejecting the request.'))
            rec.state = 'rejected'
            rec.message_post(body=_('Request rejected.'))
        return True

    def action_mark_done(self):
        self._check_procurement()
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_('Only an approved request can be marked as done.'))
            rec.state = 'done'
            rec.message_post(body=_('Request marked as done.'))
        return True
