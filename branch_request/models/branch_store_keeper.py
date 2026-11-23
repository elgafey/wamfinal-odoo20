# -*- coding: utf-8 -*-
from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

PROCUREMENT_GROUP = 'branch_request.group_branch_request_procurement'
SYSTEM_GROUP = 'base.group_system'


class BranchStoreKeeper(models.Model):
    """The tab that defines the responsibility of a branch.

    One record per internal location: the users listed here are the ones
    allowed to act on the transfers of that location (requesting,
    approving, sending and receiving).
    """

    _name = 'branch.store.keeper'
    _description = 'Branch Store Keeper'
    _order = 'location_id, id'
    _rec_name = 'location_id'

    location_id = fields.Many2one(
        'stock.location', string='Location', required=True, index=True,
        domain=[('usage', '=', 'internal')],
        help='Internal location handled by the responsible users below.')
    user_ids = fields.Many2many(
        'res.users', 'branch_store_keeper_user_rel', 'keeper_id', 'user_id',
        string='Responsible users', domain=[('share', '=', False)],
        help='Users responsible for this location.  They are the only ones, '
             'apart from the procurement team, allowed to act on the '
             'transfers of this location.')

    _location_unique = models.Constraint(
        'unique(location_id)',
        'A location can only have one store keeper record.',
    )

    # ------------------------------------------------------------------
    # Access: everybody may read the keepers (the transfer domains and
    # record rules need them), only the procurement team and the system
    # administrators may create, change or delete them.
    # ------------------------------------------------------------------
    @api.model
    def _check_write_access(self):
        if self.env.su:
            return
        user = self.env.user
        if not (user.has_group(PROCUREMENT_GROUP) or user.has_group(SYSTEM_GROUP)):
            raise AccessError(_(
                'Only the procurement team or a system administrator may '
                'manage the store keepers.'))

    @api.model_create_multi
    def create(self, vals_list):
        self._check_write_access()
        return super().create(vals_list)

    def write(self, vals):
        if self:
            self._check_write_access()
        return super().write(vals)

    def unlink(self):
        if self:
            self._check_write_access()
        return super().unlink()

    @api.constrains('location_id')
    def _check_location(self):
        for keeper in self:
            # sudo: never depend on the access rights on stock.location.
            if keeper.location_id and keeper.sudo().location_id.usage != 'internal':
                raise ValidationError(_(
                    'Only internal locations can have a store keeper.'))


class StockLocation(models.Model):
    """Reverse relation used by the transfer domains and by the depends of
    the stored ``from_user_ids`` / ``to_user_ids`` fields.  The name is
    prefixed to avoid any collision with the other installed modules."""

    _inherit = 'stock.location'

    branch_transfer_keeper_ids = fields.One2many(
        'branch.store.keeper', 'location_id', string='Store Keeper',
        help='Store keeper record defining the users responsible for this '
             'location.')


class BranchRequestUsers(models.Model):
    """The locations the user is responsible for, used by the record rule
    that limits an employee to his own branches.  Non stored: it is read
    through the rule domain, so it is computed on the fly and never needs
    a column nor a write."""

    _inherit = 'res.users'

    branch_store_keeper_location_ids = fields.Many2many(
        'stock.location', 'res_users_branch_keeper_location_rel',
        'user_id', 'location_id',
        string='Branch Store Keeper Locations',
        compute='_compute_branch_store_keeper_location_ids',
        # Same pattern as the core all_group_ids helper used in access
        # domains: the compute always runs as superuser, so evaluating the
        # rule domain never depends on the access rights of the current
        # user (nor recurses into the stock.location check).
        compute_sudo=True)

    @api.depends_context('uid')
    def _compute_branch_store_keeper_location_ids(self):
        # sudo: the keeper rows are read while a stock.location access is
        # being checked, so neither the keeper nor the location may be read
        # through the current access rights (that would recurse).
        keepers = self.env['branch.store.keeper'].sudo().search(
            [('user_ids', 'in', self.ids)])
        locations_by_user = {}
        for keeper in keepers:
            location_ids = keeper.location_id.ids
            for user_id in keeper.user_ids.ids:
                locations_by_user.setdefault(user_id, set()).update(location_ids)
        for user in self:
            user.branch_store_keeper_location_ids = [
                Command.set(sorted(locations_by_user.get(user.id, ())))]
