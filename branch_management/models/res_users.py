# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResUsers(models.Model):
    _inherit = 'res.users'

    branch_ids = fields.Many2many(
        'branch.branch', 'res_users_branch_rel', 'user_id', 'branch_id',
        string='Branches',
        help='Branches the user is allowed to work with. It is taken into '
             'account as soon as the "Branch User" group is set on the user.',
    )
    default_branch_id = fields.Many2one(
        'branch.branch', string='Default Branch',
        help='Branch proposed by default on the documents created by this user.',
    )
    branch_visible_ids = fields.Many2many(
        'branch.branch', compute='_compute_branch_visible_ids',
        string='Visible Branches',
        help='Technical field used by the access rules: every branch for a '
             'user that is not restricted, the assigned branches otherwise.',
    )
    branch_restricted = fields.Boolean(
        compute='_compute_branch_visible_ids',
        string='Branch Restricted',
        help='Technical field: the branches of this user are limited to the '
             'ones assigned to them. It is the counterpart of the field '
             'above: "every branch" and "restricted" are two sides of one '
             'decision, so they are computed together. Reports that bypass '
             'the access rules (accounting reports search with '
             'bypass_access=True) use it to know whether they have to apply '
             'the branch condition themselves.',
    )

    # ------------------------------------------------------------------
    # Visibility set used by the ir.access domains
    # ------------------------------------------------------------------
    @api.depends('branch_ids', 'group_ids')
    def _compute_branch_visible_ids(self):
        """Compute the branches a user is allowed to see, and whether the
        list is a restriction at all.

        * Not a "Branch User" (or a "Branch Manager"): every branch, so that
          nothing breaks for the users that do not use the restriction —
          ``branch_restricted`` is then False.
        * "Branch User": only the branches assigned to the user, and
          ``branch_restricted`` is True.

        Both fields share this compute method on purpose: they are the same
        decision, and a caller that reads only ``branch_restricted`` (the
        accounting reports) must never be able to disagree with a caller
        that reads ``branch_visible_ids`` (the access domains).

        The search is done as ``sudo()`` because this method is called while
        an access domain is evaluated: it must never trigger an access check
        on ``branch.branch`` (that would recurse).
        """
        Branch = self.env['branch.branch'].sudo().with_context(active_test=False)
        all_branches = Branch.search([])
        branch_user_group = self.env.ref(
            'branch_management.group_branch_user', raise_if_not_found=False,
        )
        branch_manager_group = self.env.ref(
            'branch_management.group_branch_manager', raise_if_not_found=False,
        )
        for user in self:
            restricted = bool(branch_user_group) and branch_user_group in user.all_group_ids
            if restricted and branch_manager_group:
                # a manager manages every branch, even if the "Branch User"
                # group is implied by the manager group.
                restricted = branch_manager_group not in user.all_group_ids
            # The branches are read with ``active_test=False``: an archived
            # branch stays visible to the rules (its documents must remain
            # readable), the ``active`` filter is applied by the caller.
            user.branch_restricted = restricted
            user.branch_visible_ids = (
                user.with_context(active_test=False).branch_ids
                if restricted else all_branches
            )

    # ------------------------------------------------------------------
    # Domains returned by the ir.access rows of the stock models (phase 18)
    # ------------------------------------------------------------------
    def _branch_strict_domain(self, field_name='branch_id'):
        """Access domain of a model that carries its own branch.

        * The user is not restricted (not a "Branch User"): **no domain at
          all**. Without this branch of the decision, the plain
          ``('branch_id', 'in', branch_visible_ids)`` would hide
          ``stock.warehouse0`` even from the administrator, because
          "every branch" does not contain "no branch".
        * The user is restricted: only the records of his branches, and
          **not** the ones without a branch — asked and decided in phase
          18: a user must not see a warehouse he cannot work with.

        ``ensure_one`` because the access domains are evaluated for the
        current user only (``ir.access._eval_context()`` passes
        ``env.user``).
        """
        self.ensure_one()
        if not self.branch_restricted:
            return []
        # ``active_test=False`` on purpose: an archived branch stays
        # visible to the rules (its documents must remain readable).
        return [(field_name, 'in',
                 self.with_context(active_test=False).branch_visible_ids.ids)]

    def _branch_through_warehouse_domain(self, warehouse_field='warehouse_id'):
        """Access domain of a model that has no branch of its own but hangs
        off a warehouse — ``stock.picking.type`` (the screen of the
        application) and ``stock.location`` (the stock itself).

        * Not restricted: no domain at all (same reason as above).
        * Restricted: a record **without** a warehouse stays visible — the
          shared locations ("Partners/Vendors", "Production") and the
          operation types that belong to no warehouse (dropship) have no
          branch to belong to. Everything else follows the branch of its
          warehouse: the warehouse is hidden from him, so is what is
          inside it, operation types and stock locations alike.

        The ``warehouse_id = False`` leaf is **not** redundant with the
        dotted path: ``warehouse_id.branch_id = False`` resolves through
        an inner join, so a record with no warehouse at all does not match
        it (verified against a real ``search`` + ``read`` in phase 18).

        Precondition — same as the warehouses themselves: a warehouse that
        no branch owns yet hides its own operation types and locations
        from every restricted user, so every warehouse must be given a
        branch before this phase is applied. The apply script refuses to
        run while that is not the case.

        The dotted path works because both ``warehouse_id`` fields are
        stored (verified in Odoo 20: ``stock_location.py`` line 86 and
        ``stock_picking_type.py`` line 84), so the domain becomes a join.
        """
        self.ensure_one()
        if not self.branch_restricted:
            return []
        branch_path = warehouse_field + '.branch_id'
        return ['|', (warehouse_field, '=', False),
                (branch_path, 'in',
                 self.with_context(active_test=False).branch_visible_ids.ids)]

    @api.constrains('default_branch_id', 'branch_ids', 'group_ids')
    def _check_default_branch_is_visible(self):
        """The default branch must be one of the branches of the user."""
        for user in self:
            branch = user.default_branch_id
            visible = user.with_context(active_test=False).branch_visible_ids
            if branch and branch not in visible:
                raise ValidationError(_(
                    'The default branch "%(branch)s" is not one of the '
                    'branches allowed for the user "%(user)s".',
                    branch=branch.display_name,
                    user=user.display_name,
                ))

    # ------------------------------------------------------------------
    # Cache invalidation
    # ------------------------------------------------------------------
    def _get_invalidation_fields(self):
        """``branch_ids`` changes the access domains, invalidate like groups."""
        return super()._get_invalidation_fields() | {'branch_ids'}

    def write(self, vals):
        if 'branch_ids' in vals:
            # The Many2many write computes the removed links from the value it
            # reads, and a read is filtered by ``active_test``: an archived
            # branch of the list would then never be unlinked. Writing with
            # ``active_test=False`` makes Odoo read the full relation.
            self = self.with_context(active_test=False)
        res = super().write(vals)
        if 'branch_ids' in vals:
            # the domains of the ir.access rules embed the visible branch ids
            self.env['ir.access']._clear_caches()
        return res
