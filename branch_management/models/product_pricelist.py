# -*- coding: utf-8 -*-
from collections.abc import Iterable

from odoo import api, fields, models


class ProductPricelist(models.Model):
    _inherit = 'product.pricelist'

    # The link lives on the branch: ``branch.branch.pricelist_id`` is a
    # Many2one, so a branch carries one price list at most -- two price
    # lists can never claim the same branch, and no constraint is needed
    # to say so. This field is the very same column read from the other
    # end, and it is deliberately *not* stored: there is only ever one
    # copy of the link in the database, so this side cannot contradict
    # the branch and nothing has to be kept in step with it.
    #
    # It is a many2many rather than the one2many it used to be because of
    # what its buttons do. The "Add" of a one2many opens a creation form;
    # the "Add" of a many2many opens the search dialog, and what is wanted
    # here is to give **an existing branch** to this price list, not to
    # make a new one. Deleting a row of a one2many deletes the record
    # itself, while taking a row out of a many2many only unlinks it: the
    # branch is left alive and simply loses the price list.
    branch_ids = fields.Many2many(
        'branch.branch',
        string='Branches',
        compute='_compute_branch_ids',
        inverse='_inverse_branch_ids',
        search='_search_branch_ids',
        help='Branches that sell with this price list. Giving this price '
             'list to a branch that already sells with another one moves '
             'it here: a branch keeps exactly one price list, so it can '
             'never show up under two of them.',
    )

    @api.model
    def _search_branch_ids(self, operator, value):
        """Search price lists through the branches that carry them.

        The link lives on the branch, so this is only the mirror of the
        read above: the branches the search names give the price lists
        that carry them. A field used in ``@api.depends`` must be
        searchable, and without this Odoo would not know which price
        lists to read again when ``branch.pricelist_id`` moves -- which
        is the very thing that keeps this table right after a branch is
        given to, or taken away from, its price list somewhere else.
        """
        Branch = self.env['branch.branch']
        # ``value`` is not always a plain list: Odoo's domain optimiser
        # hands over an ``OrderedSet`` for an "in", so anything that can
        # be iterated is turned into a list of ids here.
        if isinstance(value, models.BaseModel):
            values = value.ids
        elif isinstance(value, str) or not isinstance(value, Iterable):
            values = [value] if value else []
        else:
            values = list(value)
        # Odoo rewrites "no branch at all" (``('branch_ids', '=',
        # False)``) into ``('branch_ids', 'in', [False])`` for any
        # relational field, so a list that names nothing but False is
        # about the price lists that hold no branch -- never about the
        # ones that happen to carry a branch of id 0.
        only_false = bool(values) and not any(values)
        values = [value_id for value_id in values if value_id]
        if operator in ('in', 'not in'):
            if only_false and not values:
                linked = Branch.search(
                    [('pricelist_id', '!=', False)]).pricelist_id
                if operator == 'in':
                    return [('id', 'not in', linked.ids)]
                return [('id', 'in', linked.ids)]
            found = Branch.search([('id', 'in', values)]).pricelist_id
            if operator == 'not in':
                return [('id', 'not in', found.ids)]
            return [('id', 'in', found.ids)]
        if operator in ('=', '!='):
            if not values:
                # No branch named: "=" then means "a price list that
                # holds no branch at all", the only way it can answer.
                linked = Branch.search(
                    [('pricelist_id', '!=', False)]).pricelist_id
                return [('id', 'in' if operator == '!=' else 'not in',
                         linked.ids)]
            # ``search`` and not ``browse``: a branch that was archived
            # is not managed from this table any more, here and in the
            # compute above alike.
            found = Branch.search([('id', 'in', values)]).pricelist_id
            if operator == '!=':
                return [('id', 'not in', found.ids)]
            return [('id', 'in', found.ids)]
        # Any other operator is a search on the branches themselves, and
        # the price lists are simply the ones those branches carry. A
        # string stays as it is (Odoo wants the raw value to match on),
        # anything else is already a list of ids.
        leaf = value if isinstance(value, str) else values
        return [('id', 'in',
                 Branch.search([('id', operator, leaf)]).pricelist_id.ids)]

    @api.depends('branch_ids.pricelist_id')
    def _compute_branch_ids(self):
        """The branches that carry this price list, read from the branches.

        Archived branches are left out: they are not managed from this
        table, and the inverse below only ever touches what this table
        shows, so archiving a branch can never cost it its price list.
        """
        Branch = self.env['branch.branch']
        groups = {}
        for branch in Branch.search(
                [('pricelist_id', 'in', [pl.id for pl in self if pl.id])]):
            key = branch.pricelist_id.id
            groups[key] = groups.get(key, Branch) | branch
        for pricelist in self:
            # ``pricelist.id`` is false on a record that is not saved yet
            # (a NewId says so itself), and a price list still being made
            # has no branch of its own.
            pricelist.branch_ids = (
                groups.get(pricelist.id, Branch) if pricelist.id else Branch
            )

    def _inverse_branch_ids(self):
        """Give this price list to the branches added to the table, and take
        it away from the ones taken out of it.

        Nothing is written but ``branch.pricelist_id``, the one column the
        whole rule lives in. A branch added here therefore also leaves the
        price list it may have had -- that is how "a branch belongs to at
        most one price list" keeps holding when the table is the thing
        being edited. A branch taken out of the table only loses the price
        list while it still points at it, so a branch moved by somebody
        else in the same write is never cleared by mistake.
        """
        Branch = self.env['branch.branch']
        for pricelist in self:
            if not pricelist.id:
                continue                # nothing stored to write back to
            before = Branch.search([('pricelist_id', '=', pricelist.id)])
            after = pricelist.branch_ids
            gone = (before - after).filtered(
                lambda branch: branch.pricelist_id == pricelist)
            if gone:
                gone.pricelist_id = False
            arrived = after.filtered(
                lambda branch: branch.pricelist_id != pricelist)
            if arrived:
                arrived.pricelist_id = pricelist
