# -*- coding: utf-8 -*-
"""Phase 19 runtime tests: the branch picks the price list of the order.

Three decisions shape this phase (they were chosen explicitly):

* the link itself lives on the branch (``pricelist_id``, a Many2one), so
  a branch points at **one** price list at most and can never show up
  under two of them, while the price list carries the branches that use
  it (``branch_ids``, the other side of the same column) and is free to
  cover as many of them as needed,
* the price list of the branch is proposed on the quotation and the
  prices of its lines follow it, through the very mechanism Odoo uses
  for a change of price list (``_recompute_prices()``, never as a
  dependency of the price of a line — Odoo forbids that in a comment of
  its own),
* a confirmed order, a price list of another company and a price written
  by hand are all left alone.

Run with:  odoo shell -d balance_mod ... < test_phase19.py
The whole script runs in one transaction and rolls it back at the end.
"""
from contextlib import contextmanager

from odoo.exceptions import UserError
from odoo.tests import Form

PASS = FAIL = 0
LINES = []


def check(label, func):
    global PASS, FAIL
    try:
        func()
    except Exception as exc:  # noqa: BLE001 - every test failure is reported
        FAIL += 1
        LINES.append("FAIL  %s :: %s: %s" % (label, type(exc).__name__, exc))
    else:
        PASS += 1
        LINES.append("PASS  %s" % label)


def eq(actual, expected, msg=""):
    if actual != expected:
        raise AssertionError("%s expected=%r actual=%r" % (msg, expected, actual))


def truthy(value, msg=""):
    if not value:
        raise AssertionError("%s: got %r" % (msg, value))


@contextmanager
def expect(exc_types):
    """Assert that the block raises one of ``exc_types`` (savepoint + cache)."""
    raised = None
    try:
        try:
            with env.cr.savepoint(flush=True):
                yield
        except exc_types as exc:
            raised = exc
    finally:
        env.invalidate_all()
    if raised is None:
        name = getattr(exc_types, "__name__", str(exc_types))
        raise AssertionError("expected %s: nothing raised" % name)


# ---------------------------------------------------------------------------
# Fixtures
#
# * the customer already has a price list of its own (no rule in it, so it
#   keeps the catalogue price of 100),
# * list A sells the product at 120 and list B at 130, through one fixed
#   price rule each,
# * branch A carries list A, branch B and branch C carry none, and branch D
#   is only used to move between lists.
# ---------------------------------------------------------------------------
def build():
    Branch = env['branch.branch']
    Pricelist = env['product.pricelist']
    currency = env.company.currency_id
    company = env.company

    # The price list of a *customer* is only computed while the "Pricelists"
    # feature is switched on: ``_is_feature_enabled`` asks whether user 1
    # holds ``product.group_product_pricelist``. That says nothing about
    # this phase — the branch brings its own price list either way, and the
    # price of a line follows it — but the customer list created below
    # needs it to be able to exist at all, and it is what the quotation
    # starts on when the branch has no list of its own.
    pricelist_group = env.ref('product.group_product_pricelist')
    for user in (env.user, env.ref('base.user_admin')):
        if pricelist_group not in user.group_ids:
            user.write({'group_ids': [(4, pricelist_group.id)]})

    partner = env['res.partner'].create({'name': 'T19 Customer'})
    product = env['product.product'].create({
        'name': 'T19 Product', 'list_price': 100.0, 'invoice_policy': 'order'})

    pl_customer = Pricelist.create({'name': 'T19 Customer List',
                                    'currency_id': currency.id,
                                    'company_id': company.id})
    pl_a = Pricelist.create({'name': 'T19 List A',
                             'currency_id': currency.id,
                             'company_id': company.id})
    pl_b = Pricelist.create({'name': 'T19 List B',
                             'currency_id': currency.id,
                             'company_id': company.id})
    partner.write({'property_product_pricelist': pl_customer.id})

    Item = env['product.pricelist.item']
    for pl, price in ((pl_a, 120.0), (pl_b, 130.0)):
        Item.create({'pricelist_id': pl.id, 'applied_on': '1_product',
                     'product_tmpl_id': product.product_tmpl_id.id,
                     'compute_price': 'fixed', 'fixed_price': price})

    b_pl = Branch.create({'name': 'T19 Branch A', 'code': 'T19-A',
                          'pricelist_id': pl_a.id})
    b_none = Branch.create({'name': 'T19 Branch B', 'code': 'T19-B'})
    b_none2 = Branch.create({'name': 'T19 Branch C', 'code': 'T19-C'})
    b_move = Branch.create({'name': 'T19 Branch D', 'code': 'T19-D',
                            'pricelist_id': pl_a.id})

    return {'partner': partner, 'product': product,
            'pl_customer': pl_customer, 'pl_a': pl_a, 'pl_b': pl_b,
            'b_pl': b_pl, 'b_none': b_none, 'b_none2': b_none2,
            'b_move': b_move, 'currency': currency, 'company': company}


def new_order(branch=None, price=None, qty=1):
    """A quotation saying its branch.

    ``price`` is left out by default so that the unit price comes from
    the price list, which is what this phase is about.
    """
    vals = {'partner_id': f['partner'].id}
    if branch is not None:
        vals['branch_id'] = branch.id if branch else False
    line = {'product_id': f['product'].id, 'product_uom_qty': qty}
    if price is not None:
        line['price_unit'] = price
    vals['order_line'] = [(0, 0, line)]
    return env['sale.order'].create(vals)


try:
    f = build()

    # -----------------------------------------------------------------
    def t1():
        """The link is declared the way the rule needs it: one price list
        per branch (a Many2one can only carry one id, which is what stops
        a branch from appearing under two lists), the reverse side on the
        price list, and the price list of the order still the very field
        Odoo declares — stored, editable, and now following the branch as
        well as the customer."""
        bfield = env['branch.branch']._fields['pricelist_id']
        eq(bfield.type, 'many2one', 'a branch holds one price list')
        eq(bfield.comodel_name, 'product.pricelist', 'of type price list')
        eq(bfield.string, 'Price List', 'and it is called Price List')

        pfield = env['product.pricelist']._fields['branch_ids']
        eq(pfield.type, 'many2many', 'the price list shows its branches')
        eq(pfield.comodel_name, 'branch.branch', 'of type branch')
        truthy(not pfield.store,
               'and it is only a reading: the link itself is stored once,'
               ' on the branch, so the two sides cannot contradict')
        eq(pfield.compute, '_compute_branch_ids', 'read from the branches')
        eq(pfield.inverse, '_inverse_branch_ids',
           'and writing it writes the branch')
        truthy(pfield.search, 'and it is searchable, which is what lets'
               ' the price list be read again when a branch moves')

        so = env['sale.order']._fields['pricelist_id']
        eq(so.compute, '_compute_pricelist_id', 'still the compute of Odoo')
        truthy(so.store, 'the price list of the order is stored')
        truthy(not so.readonly,
               'and the field itself is never locked: the lock lives in'
               ' the form, and only while the branch brings a list')
        depends, _context = so.get_depends(env['sale.order'])
        truthy('branch_id' in depends,
               'the price list is recomputed when the branch changes')
        for name in ('partner_id', 'company_id'):
            truthy(name in depends,
                   'the rule of Odoo is kept: %s' % name)
    check('T1  the link and the compute are the right shape', t1)

    # -----------------------------------------------------------------
    def t2():
        """The branch proposes its own price list and the lines are
        priced with it."""
        order = new_order(branch=f['b_pl'])
        eq(order.pricelist_id, f['pl_a'], 'the branch proposes its list')
        eq(order.order_line.price_unit, 120.0,
           'the line is priced with that list')
        eq(order.amount_untaxed, 120.0, 'and so is the untaxed total')
    check('T2  the branch proposes its price list and the price follows', t2)

    # -----------------------------------------------------------------
    def t3():
        """A branch with no price list changes nothing: the customer
        keeps the one it already had, which is the rule of Odoo."""
        order = new_order(branch=f['b_none'])
        eq(order.pricelist_id, f['partner'].property_product_pricelist,
           'the list of the customer is kept')
        eq(order.order_line.price_unit, 100.0,
           'and the catalogue price of the product')
    check('T3  a branch without price list keeps the customer one', t3)

    # -----------------------------------------------------------------
    def t4():
        """A quotation made in the form lands on the price list of the
        branch, and its line is priced with it from the start."""
        with Form(env['sale.order']) as fo:
            fo.partner_id = f['partner']
            fo.branch_id = f['b_pl']
            with fo.order_line.new() as line:
                line.product_id = f['product']
                line.product_uom_qty = 1
        order = fo.record
        eq(order.pricelist_id, f['pl_a'], 'the order gets the list of its branch')
        eq(order.order_line.price_unit, 120.0,
           'and the line is priced with it')
    check('T4  a new quotation in the form starts on the branch list', t4)

    # -----------------------------------------------------------------
    def t5():
        """The heart of the phase: moving the branch inside the form
        moves the price list and re-prices the lines, both ways."""
        order = new_order(branch=f['b_none'])
        eq(order.pricelist_id, f['pl_customer'], 'it starts on the customer list')
        eq(order.order_line.price_unit, 100.0, 'priced at 100')

        with Form(order) as fo:
            fo.branch_id = f['b_pl']
        order.invalidate_recordset()
        eq(order.pricelist_id, f['pl_a'], 'the new branch brings its list')
        eq(order.order_line.price_unit, 120.0, 'and the line follows it')

        with Form(order) as fo:
            fo.branch_id = f['b_none']
        order.invalidate_recordset()
        eq(order.pricelist_id, f['pl_customer'], 'back to a branch with no list')
        eq(order.order_line.price_unit, 100.0, 'and the price comes back')
    check('T5  changing the branch moves the list and the prices', t5)

    # -----------------------------------------------------------------
    def t6():
        """A price typed by hand is not touched when the branch changes
        without moving the price list: there is nothing to re-price."""
        order = new_order(branch=f['b_none'])
        order.order_line.price_unit = 77.0
        order.invalidate_recordset()
        eq(order.order_line.price_unit, 77.0, 'the price was taken')

        with Form(order) as fo:
            fo.branch_id = f['b_none2']
        order.invalidate_recordset()
        eq(order.pricelist_id, f['pl_customer'],
           'the price list did not move')
        eq(order.order_line.price_unit, 77.0,
           'the price written by hand survived')
    check('T6  a price written by hand survives the branch change', t6)

    # -----------------------------------------------------------------
    def t7():
        """The rule also holds outside the form: an import or a call to
        the API writes the branch and the prices follow it."""
        order = new_order(branch=f['b_none'])
        eq(order.order_line.price_unit, 100.0, 'priced at 100')
        order.write({'branch_id': f['b_pl'].id})
        order.invalidate_recordset()
        eq(order.pricelist_id, f['pl_a'], 'the branch brought its list')
        eq(order.order_line.price_unit, 120.0, 'and the price followed')
    check('T7  a branch written outside the form moves the prices', t7)

    # -----------------------------------------------------------------
    def t8():
        """A confirmed order is never moved: its pickings and its
        invoices exist, the prices are settled."""
        order = new_order(branch=f['b_none'])
        order.action_confirm()
        eq(order.state, 'sale', 'the order is confirmed')
        before = order.pricelist_id
        truthy(before != f['pl_a'], 'sanity: the two lists differ')

        order.write({'branch_id': f['b_pl'].id})
        order.invalidate_recordset()
        eq(order.pricelist_id, before, 'a confirmed order keeps its list')
        eq(order.order_line.price_unit, 100.0,
           'and its lines keep their price')
    check('T8  a confirmed order keeps its price list', t8)

    # -----------------------------------------------------------------
    def t9():
        """A price list of another company is never proposed — the field
        carries check_company, and the order would become unsavable. The
        branch refuses such a price list too (Odoo 20 raises UserError
        from its own _check_company, not ValidationError)."""
        other = env['res.company'].create({'name': 'T19 Other Company'})
        pl_co = env['product.pricelist'].create({
            'name': 'T19 Foreign List',
            'currency_id': f['currency'].id, 'company_id': False})
        b_foreign = env['branch.branch'].create({
            'name': 'T19 Branch E', 'code': 'T19-E',
            'pricelist_id': pl_co.id})
        # the price list now belongs to the other company; the branch is
        # left holding it, which is the situation the guard is for
        pl_co.write({'company_id': other.id})

        order = new_order(branch=b_foreign)
        eq(order.pricelist_id, f['pl_customer'],
           'the price list of the other company is not taken')
        eq(order.order_line.price_unit, 100.0,
           'the price of the customer list is used')

        with expect(UserError):
            env['branch.branch'].create({
                'name': 'T19 Branch F', 'code': 'T19-F',
                'pricelist_id': pl_co.id})
    check('T9  a price list of another company is refused', t9)

    # -----------------------------------------------------------------
    def t10():
        """The two halves of the rule asked for: one price list covers
        as many branches as needed, and a branch is never in two of
        them — it can only move from one to the other."""
        pl_a, pl_b = f['pl_a'], f['pl_b']
        branch = f['b_move']
        eq(branch.pricelist_id, pl_a, 'the branch starts in list A')
        eq(sorted(pl_a.branch_ids.ids), sorted((f['b_pl'] | branch).ids),
           'list A shows every branch that carries it')
        truthy(branch not in pl_b.branch_ids, 'list B does not have it')

        branch.write({'pricelist_id': pl_b.id})
        eq(branch.pricelist_id, pl_b, 'the branch moved to list B')
        truthy(branch not in pl_a.branch_ids, 'list A lost it')
        eq(pl_b.branch_ids, branch, 'list B has it now')

        f['b_none'].write({'pricelist_id': pl_b.id})
        eq(len(pl_b.branch_ids), 2, 'one price list holds two branches')
        eq(set(pl_b.branch_ids.ids), set((branch | f['b_none']).ids),
           'and they are exactly the two that were given to it')
    check('T10 one list for many branches, one branch for one list', t10)

    # -----------------------------------------------------------------
    def t11():
        """Both sides of the link are reachable from the interface: the
        price list field in the form of the branch, and the table of
        branches in the form of the price list."""
        bview = env.ref('branch_management.branch_view_form',
                        raise_if_not_found=False)
        truthy(bview, 'the form of the branch is registered')
        truthy('name="pricelist_id"' in bview.arch,
               'the form of the branch shows the price list')
        arch = env['branch.branch'].get_view(bview.id, 'form')['arch']
        truthy('name="pricelist_id"' in arch,
               'and the resolved form shows it too')
        truthy('string="Sales"' in arch, 'in a Sales section of its own')

        pview = env.ref('branch_management.product_pricelist_view_branch',
                        raise_if_not_found=False)
        truthy(pview, 'the inherited form of the price list is registered')
        truthy('branch_ids' in pview.arch, 'it touches the branches')
        parch = env['product.pricelist'].get_view(
            env.ref('product.product_pricelist_view').id, 'form')['arch']
        truthy('name="branches"' in parch, 'the price list has the Branches tab')
        truthy('branch_ids' in parch, 'and the table of branches is in it')
        truthy('name="code"' in parch, 'the table can be filled in')
    check('T11 the two forms carry the link', t11)

except Exception:  # noqa: BLE001 - never leave the shell in a broken state
    import traceback
    LINES.append("FATAL " + traceback.format_exc())
    FAIL += 1
finally:
    print("\n".join([""] + LINES))
    print("\n==== PHASE 19: %d PASS / %d FAIL ====" % (PASS, FAIL))
    env.cr.rollback()
