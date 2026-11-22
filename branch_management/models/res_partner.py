# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # NOTE: no check_company=True here.  res.partner.company_id is very often
    # empty (a contact shared by every company), and in that case Odoo would
    # only accept a branch whose own company is empty (_check_company_domain
    # returns ('company_id', '=', False) for an empty company) -- and every
    # branch has a company, so no branch could ever be selected.
    branch_ids = fields.Many2many(
        'branch.branch', 'res_partner_branch_rel', 'partner_id', 'branch_id',
        string='Branches',
        domain=lambda self: [
            ('id', 'in', self.env.user.with_context(active_test=False).branch_visible_ids.ids),
        ],
        help='Branches this contact belongs to. Several branches can be '
             'selected for the same contact. The list only shows the '
             'branches the current user is allowed to see.',
    )

    # Technical mirror used by the access rule of res.partner.  An ir.access
    # domain *cannot* say ("branch_ids", "=", False): Odoo 20 rewrites that
    # leaf on a x2many into "does not own any value that the user may read on
    # branch.branch", i.e. "owns no *visible* branch" -- which would keep
    # every other-branch contact visible (see README, section 8).  A plain
    # boolean on res.partner has no comodel, so it is not rewritten.
    has_branch = fields.Boolean(
        string='Has a Branch',
        compute='_compute_has_branch', store=True,
        help='Technical field used by the access rules: it is False as long '
             'as the contact is not linked to any branch, so that contacts '
             'without a branch stay visible to everybody.',
    )

    @api.depends('branch_ids')
    def _compute_has_branch(self):
        for partner in self:
            partner.has_branch = bool(partner.branch_ids)
