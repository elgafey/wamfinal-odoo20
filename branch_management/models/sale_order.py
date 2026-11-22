# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    branch_id = fields.Many2one(
        'branch.branch', string='Branch',
        default=lambda self: self.env.user.default_branch_id,
        domain=lambda self: [
            ('id', 'in', self.env.user.with_context(active_test=False).branch_visible_ids.ids),
        ],
        index=True, check_company=True, tracking=True,
        help='Branch of the company that handles this order. It is proposed '
             'from the default branch of the user, and it drives the warehouse '
             'of the order, the pickings, the invoices and their analytic '
             'distribution.',
    )

    # A technical flag the form reads: as soon as the branch of the order
    # brings a price list of its own, the price list of the order stops
    # being a free choice and the form makes the field read-only.
    has_branch_pricelist = fields.Boolean(
        compute='_compute_has_branch_pricelist',
        help='Technical field used by the form: the branch of this order '
             'sells with a price list, and that price list decides the '
             'price list of the order, which is therefore not free to be '
             'changed by hand.',
    )

    # ------------------------------------------------------------------
    # Warehouse of the branch
    # ------------------------------------------------------------------
    @api.depends('branch_id', 'user_id', 'company_id')
    def _compute_warehouse_id(self):
        """Propose the warehouse of the branch of the order."""
        super()._compute_warehouse_id()
        for order in self:
            warehouse = order.branch_id.warehouse_id
            # never touch a confirmed order: its pickings already exist
            if warehouse and order.state not in ('sale', 'cancel'):
                order.warehouse_id = warehouse

    # ------------------------------------------------------------------
    # Price list of the branch
    # ------------------------------------------------------------------
    @api.depends('branch_id', 'partner_id', 'company_id')
    def _compute_pricelist_id(self):
        """Propose the price list of the branch of the order.

        Odoo gives the order the price list of the customer and stops as
        soon as the order leaves the draft state. That rule is kept and
        only the price list of the branch is put on top of it, on an order
        that can still be changed — the same states as the branch field
        itself, and the same states in which the warehouse of the branch
        is proposed (see ``_compute_warehouse_id`` above).

        A branch without a price list changes nothing: the customer keeps
        its own, which is the rule of Odoo. A price list of another
        company is never taken, because ``pricelist_id`` carries
        ``check_company=True`` and the order would become unsavable.
        """
        super()._compute_pricelist_id()
        for order in self:
            if order.state in ('sale', 'cancel'):
                continue                # a confirmed order keeps its prices
            pricelist = order.branch_id.pricelist_id
            if not pricelist:
                continue                # no price list on the branch: Odoo rule
            if pricelist.company_id and pricelist.company_id != order.company_id:
                continue                # never cross companies
            order.pricelist_id = pricelist

    @api.depends('branch_id.pricelist_id', 'company_id')
    def _compute_has_branch_pricelist(self):
        """Whether the price list of the branch is the one the order keeps.

        It answers yes only when that price list really would be taken,
        which is the rule of the compute above: a price list of another
        company is never put on an order, so it locks nothing. The form
        reads this to turn its price list field read-only (README
        section 20).
        """
        for order in self:
            pricelist = order.branch_id.pricelist_id
            order.has_branch_pricelist = bool(
                pricelist
                and (not pricelist.company_id
                     or pricelist.company_id == order.company_id)
            )

    @api.onchange('branch_id')
    def _onchange_branch_pricelist(self):
        """Refresh the prices of the lines when the branch moved them.

        The price of a line is *not* a compute of the price list: Odoo
        refuses it in a comment above its own
        ``_onchange_pricelist_id_recompute_prices``, because the ORM would
        recompute every line of every order whenever a price list is
        touched. On a change of price list Odoo calls
        ``_recompute_prices()`` from an onchange instead, and this does
        the same when the branch is what moved the price list.

        The comparison is made with the price list *stored on the order*
        (``_origin``, the record in the database), never with the value
        on the virtual record: the compute above has already run by now
        and would always report itself. A branch that does not move the
        price list therefore leaves the prices — and a price written by
        hand — untouched.
        """
        if self.env.context.get('sale_onchange_first_call'):
            return                      # a new record: nothing to refresh
        if self.state in ('sale', 'cancel'):
            return                      # a confirmed order keeps its prices
        stored = self._origin.pricelist_id if self._origin \
            else self.env['product.pricelist']
        if self.pricelist_id == stored:
            return                      # the branch changed, the list did not
        if self.order_line:
            self._recompute_prices()

    # ------------------------------------------------------------------
    # Sales journal of the branch
    # ------------------------------------------------------------------
    def _sale_journal_for_branch(self, branch):
        """The sales journal this branch invoices in.

        The journal *of the branch* comes first; then a journal shared by
        every branch (a journal with no branch imposes no branch on the
        entries made in it, README section 16); then nothing, and Odoo
        falls back to its own rule — the sales journal with the lowest
        sequence.

        An order with no branch is given no journal: it cannot be
        confirmed anyway (``_confirmation_error_message``).

        Only the journals of the company of the order are looked at, and
        only the ones the reader is allowed to read: the rule of phase 16
        on the journals applies to this search like to any other.
        """
        self.ensure_one()
        Journal = self.env['account.journal']
        if not branch:
            return Journal
        domain = [('type', '=', 'sale'),
                  ('company_id', 'in', (False, self.company_id.id))]
        journal = Journal.search(domain + [('branch_id', '=', branch.id)],
                                 order='sequence, id', limit=1)
        if journal:
            return journal
        return Journal.search(domain + [('branch_id', '=', False)],
                              order='sequence, id', limit=1)

    @api.depends('branch_id')
    def _compute_journal_id(self):
        """The branch of the order proposes its own sales journal.

        This is the other half of the rule of phase 16: there the journal
        decides the branch of the entry, here the branch decides the
        journal that will invoice it, so the invoice is created in a
        journal that already agrees with its branch.

        The value already on the order is kept whenever it still belongs
        to the same branch. Without that, picking a journal in the form
        would push the order onto the branch of the journal (see the
        onchange below), which would recompute the journal back to the
        *first* journal of that branch and undo the choice that was just
        made.

        The previous value is read before the core compute, which sets the
        field to ``False``, runs.
        """
        previous = {order: order.journal_id for order in self}
        super()._compute_journal_id()
        for order in self:
            old = previous[order]
            if old and old.branch_id == order.branch_id:
                order.journal_id = old       # still right: keep the choice
            else:
                order.journal_id = order._sale_journal_for_branch(
                    order.branch_id)

    @api.model
    def _branch_of_journal_value(self, value):
        """The branch of a journal given as a create / write value."""
        if not value:
            return self.env['branch.branch']
        if isinstance(value, models.BaseModel):
            journal = value
        else:
            journal = self.env['account.journal'].browse(value)
        return journal.branch_id

    @api.model_create_multi
    def create(self, vals_list):
        """An order given a journal lands on the branch of that journal.

        The branch proposed by the form (the default branch of the user)
        is replaced here, so the two values can never start out apart:
        the journal decides, as it does on the entry itself (phase 16).
        """
        for vals in vals_list:
            branch = self._branch_of_journal_value(vals.get('journal_id'))
            if branch:
                vals['branch_id'] = branch.id
        return super().create(vals_list)

    def _check_pricelist_written(self, vals):
        """An order whose branch sells with a price list keeps that price list.

        The form turns its price list field read-only as soon as
        ``has_branch_pricelist`` says so; this is the same rule for
        everything that writes an order without ever seeing a form — an
        import, a call to the API, a route.

        It applies exactly where the compute of the price list applies,
        and nowhere else: while the order can still be changed (a
        confirmed order is settled and keeps its own prices) and only to
        a price list of the company of the order (a price list of another
        company is never taken, so it cannot lock anything either).
        """
        wanted = vals.get('pricelist_id')
        if isinstance(wanted, models.BaseModel):
            wanted = wanted.id
        else:
            wanted = wanted or False
        has_branch = 'branch_id' in vals
        for order in self:
            if order.state in ('sale', 'cancel'):
                continue                # a confirmed order keeps its prices
            if not has_branch:
                branch = order.branch_id
            elif isinstance(vals['branch_id'], models.BaseModel):
                branch = vals['branch_id']
            else:
                branch = self.env['branch.branch'].browse(
                    vals['branch_id'] or [])
            pricelist = branch.pricelist_id
            if not pricelist:
                continue                # no price list on the branch
            if pricelist.company_id and pricelist.company_id != order.company_id:
                continue                # never cross companies
            if wanted == pricelist.id:
                continue                # it is the price list of the branch
            raise ValidationError(_(
                'The order "%(order)s" belongs to the branch "%(branch)s", '
                'which sells with the price list "%(pricelist)s". That '
                'price list is put on the order and cannot be changed.',
                order=order.display_name,
                branch=branch.display_name,
                pricelist=pricelist.display_name,
            ))

    def write(self, vals):
        """Moving the order to another journal moves it to its branch.

        A journal with no branch imposes nothing and the branch of the
        order is left as it is.

        A branch written outside the form (an import, an API call, a
        route) moves the price list of the order exactly like the form
        does, and the prices of the lines follow it. The onchange above
        only ever runs for somebody sitting in the form; this covers the
        other ways of writing an order. Nothing happens when the price
        list stays where it was, so a price written by hand survives a
        branch change that changes no price list.

        An order whose branch sells with a price list keeps that price
        list: the form makes the field read-only, and the check below is
        the same rule for the ways of writing that never see a form.
        """
        if 'journal_id' in vals:
            branch = self._branch_of_journal_value(vals['journal_id'])
            if branch:
                vals = dict(vals, branch_id=branch.id)
        if 'pricelist_id' in vals:
            self._check_pricelist_written(vals)
        before = ({order: order.pricelist_id for order in self}
                  if 'branch_id' in vals else None)
        res = super().write(vals)
        if before:
            for order in self:
                if order.state in ('sale', 'cancel'):
                    continue
                if order.pricelist_id != before[order] and order.order_line:
                    order._recompute_prices()
        return res

    @api.onchange('journal_id')
    def _onchange_journal_branch(self):
        """Show the branch of the journal as soon as it is selected."""
        if self.journal_id.branch_id:
            self.branch_id = self.journal_id.branch_id

    # ------------------------------------------------------------------
    # Confirmation check
    # ------------------------------------------------------------------
    def _confirmation_error_message(self):
        """A quotation without branch cannot be confirmed.

        The field is required on the form; this check also covers the orders
        created through an import, an API call or a route.
        """
        error = super()._confirmation_error_message()
        if error:
            return error
        if not self.branch_id:
            return _(
                'The order "%(order)s" has no branch. Set a branch on the '
                'order before confirming it.',
                order=self.display_name,
            )
        return False

    # ------------------------------------------------------------------
    # Invoice
    # ------------------------------------------------------------------
    def _prepare_invoice(self):
        values = super()._prepare_invoice()
        values['branch_id'] = self.branch_id.id
        # An order written before the branch started picking its journal,
        # or a journal given a branch after the order was made: the invoice
        # still goes to the journal of its branch, which is the only thing
        # a journal with a branch accepts (phase 16). An order whose journal
        # was chosen keeps it (core only passes journal_id when it is set).
        if not values.get('journal_id') and self.branch_id:
            journal = self._sale_journal_for_branch(self.branch_id)
            if journal:
                values['journal_id'] = journal.id
        return values


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def _prepare_procurement_values(self):
        """Give the branch of the order to the moves it will create."""
        values = super()._prepare_procurement_values()
        self.ensure_one()
        values['branch_id'] = self.order_id.branch_id.id
        return values
