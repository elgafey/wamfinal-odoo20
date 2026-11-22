# -*- coding: utf-8 -*-
"""Phase 20 runtime tests: lock the price list of the order, and give an
existing branch to a price list.

Two requests, one answer:

* **an order whose branch sells with a price list cannot have its price
  list changed.** The lock is drawn in the form (a read-only field, which
  Odoo keeps from the save payload as well) and enforced in ``write()``,
  so an import or a call to the API cannot slip past it either. It only
  applies while the order can still be changed, and only to a price list
  the branch really would take — a price list of another company is
  never taken, so it never locks anything,

* **the Branches tab of a price list adds an existing branch.** The field
  is now a *non-stored* ``Many2many``: the "Add" button of a many2many
  opens the search dialog (the one of a one2many opened a creation
  form), taking a row out only unlinks it instead of deleting the
  branch, and there is still only one copy of the link in the whole
  database — the ``Many2one`` column on the branch. A branch added to a
  price list that already had another one simply moves over, which is
  how "never in two" keeps holding while the table is what gets edited.

Run with:  odoo shell -d balance_mod ... < test_phase20.py
The whole script runs in one transaction and rolls it back at the end.
"""
from contextlib import contextmanager

from odoo.exceptions import ValidationError
from odoo.tests import Form
from odoo.tools.safe_eval import safe_eval

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
# * list A and list B belong to the company, the "free" list belongs to no
#   company at all (a price list of no company may take any branch),
# * branch 1 starts on list A, branch 2 and branch 3 start on none, branch
#   4 starts on list A as well so that "one list, many branches" is the
#   starting state and not only something the tests build.
# ---------------------------------------------------------------------------
def build():
    Branch = env['branch.branch']
    Pricelist = env['product.pricelist']
    currency = env.company.currency_id
    company = env.company

    # A price list can only exist while the "Pricelists" feature is on,
    # which means the group on user 1 (see phase 19 for the details).
    pricelist_group = env.ref('product.group_product_pricelist')
    for user in (env.user, env.ref('base.user_admin')):
        if pricelist_group not in user.group_ids:
            user.write({'group_ids': [(4, pricelist_group.id)]})

    partner = env['res.partner'].create({'name': 'T20 Customer'})
    product = env['product.product'].create({
        'name': 'T20 Product', 'list_price': 100.0, 'invoice_policy': 'order'})

    pl_a = Pricelist.create({'name': 'T20 List A', 'currency_id': currency.id,
                             'company_id': company.id})
    pl_b = Pricelist.create({'name': 'T20 List B', 'currency_id': currency.id,
                             'company_id': company.id})
    pl_free = Pricelist.create({'name': 'T20 Free List',
                                'currency_id': currency.id, 'company_id': False})
    partner.write({'property_product_pricelist': pl_free.id})

    b1 = Branch.create({'name': 'T20 Branch 1', 'code': 'T20-1',
                        'pricelist_id': pl_a.id})
    b2 = Branch.create({'name': 'T20 Branch 2', 'code': 'T20-2'})
    b3 = Branch.create({'name': 'T20 Branch 3', 'code': 'T20-3'})
    b4 = Branch.create({'name': 'T20 Branch 4', 'code': 'T20-4',
                        'pricelist_id': pl_a.id})

    return {'partner': partner, 'product': product, 'pl_a': pl_a, 'pl_b': pl_b,
            'pl_free': pl_free, 'b1': b1, 'b2': b2, 'b3': b3, 'b4': b4,
            'currency': currency, 'company': company}


def new_order(branch=None, price=None, qty=1):
    """A quotation saying its branch."""
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
    Branch = env['branch.branch']
    Pricelist = env['product.pricelist']

    # -----------------------------------------------------------------
    def t1():
        """Both sides keep the shape the rule needs: one Many2one column
        on the branch is the link, and the price list only reads it."""
        bfield = Branch._fields['pricelist_id']
        eq(bfield.type, 'many2one', 'a branch holds one price list')
        eq(bfield.comodel_name, 'product.pricelist', 'of type price list')

        pfield = Pricelist._fields['branch_ids']
        eq(pfield.type, 'many2many', 'the price list lists its branches')
        eq(pfield.comodel_name, 'branch.branch', 'of type branch')
        truthy(not pfield.store,
               'and nothing is stored here: there is only one copy of'
               ' the link, the column on the branch')
        eq(pfield.compute, '_compute_branch_ids', 'read from the branches')
        eq(pfield.inverse, '_inverse_branch_ids',
           'and writing the table writes the branch')
        truthy(pfield.search, 'and it is searchable, without which Odoo'
               ' could not know what to read again after a branch moves')
    check('T1  one column on the branch, a reading on the price list', t1)

    # -----------------------------------------------------------------
    def t2():
        """An existing branch is given to a price list from its form, and
        nothing is created on the way."""
        before = Branch.search_count([])
        pl = f['pl_b']
        eq(pl.branch_ids, Branch, 'list B starts empty')
        pl.write({'branch_ids': [(6, 0, [f['b2'].id])]})
        eq(f['b2'].pricelist_id, pl, 'the branch now sells with list B')
        eq(pl.branch_ids, f['b2'], 'and the table shows it')
        eq(Branch.search_count([]), before, 'no branch was created')
    check('T2  an existing branch is added, nothing is created', t2)

    # -----------------------------------------------------------------
    def t3():
        """A branch can never sit under two price lists: being added to
        another one moves it, and the list it left loses it."""
        pl_a, pl_b, b1 = f['pl_a'], f['pl_b'], f['b1']
        truthy(b1 in pl_a.branch_ids, 'branch 1 starts on list A')
        truthy(b1 not in pl_b.branch_ids, 'and not on list B')

        pl_b.write({'branch_ids': [(6, 0, [b1.id])]})
        eq(b1.pricelist_id, pl_b, 'it moved to list B')
        truthy(b1 not in pl_a.branch_ids, 'list A lost it')
        eq(pl_b.branch_ids, b1, 'list B has it')
        # put it back for the tests that follow
        pl_a.write({'branch_ids': [(6, 0, [b1.id])]})
        eq(b1.pricelist_id, pl_a, 'and it is back on list A')
        eq(pl_b.branch_ids, Branch, 'list B is empty again')
    check('T3  a branch is never in two lists, it moves', t3)

    # -----------------------------------------------------------------
    def t4():
        """Taking a row out of the table takes the price list away from
        the branch — and only unlinks it, the branch itself stays."""
        pl, b2 = f['pl_b'], f['b2']
        pl.write({'branch_ids': [(6, 0, [b2.id])]})
        eq(b2.pricelist_id, pl, 'branch 2 starts on list B')
        eq(pl.branch_ids, b2, 'and the table says so')
        pl.write({'branch_ids': [(5, 0, 0)]})
        eq(b2.pricelist_id.id, False, 'list B is no longer on branch 2')
        truthy(b2.exists(), 'and the branch still exists')
        eq(pl.branch_ids, Branch, 'the table is empty')
    check('T4  taking a row out unlinks, it does not delete', t4)

    # -----------------------------------------------------------------
    def t5():
        """One price list covers as many branches as needed."""
        pl, b2, b3 = f['pl_b'], f['b2'], f['b3']
        pl.write({'branch_ids': [(6, 0, [b2.id, b3.id])]})
        eq(len(pl.branch_ids), 2, 'list B holds two branches')
        eq(set(pl.branch_ids.ids), {b2.id, b3.id},
           'and they are exactly the two that were given to it')
        eq(set((b2 | b3).mapped('pricelist_id').ids), {pl.id},
           'both of them point back at it')
        pl.write({'branch_ids': [(5, 0, 0)]})
    check('T5  one price list holds many branches', t5)

    # -----------------------------------------------------------------
    def t6():
        """The table is only a reading of the branch column, so a branch
        moved somewhere else shows up here without anything else."""
        pl, b3 = f['pl_a'], f['b3']
        truthy(b3 not in pl.branch_ids, 'branch 3 is not on list A yet')
        b3.pricelist_id = pl
        truthy(b3 in pl.branch_ids, 'the table sees the new branch')
        truthy(pl in Pricelist.search([('branch_ids', 'in', b3.ids)]),
               'and a search on the branches finds the price list')
        b3.pricelist_id = False
        truthy(b3 not in pl.branch_ids, 'and it disappears again')
    check('T6  the table follows the branch column', t6)

    # -----------------------------------------------------------------
    def t7():
        """An archived branch is not managed from the table, and saving
        the table never quietly takes its price list away."""
        pl, b4 = f['pl_a'], f['b4']
        pl.write({'branch_ids': [(6, 0, [b4.id])]})
        truthy(b4 in pl.branch_ids, 'branch 4 is on list A')
        b4.action_archive()
        truthy(b4 not in pl.branch_ids, 'an archived branch is not listed')
        # editing the table while branch 4 is archived
        pl.write({'branch_ids': [(6, 0, [f['b1'].id])]})
        eq(b4.pricelist_id, pl,
           'the archived branch keeps its price list all the same')
        b4.action_unarchive()
        truthy(b4 in pl.branch_ids, 'and it is back in the table')
    check('T7  archiving a branch never costs it its price list', t7)

    # -----------------------------------------------------------------
    def t8():
        """The form of the order draws the lock: the price list becomes
        read-only as soon as the branch brings one of its own."""
        order = new_order(branch=f['b1'])
        truthy(order.has_branch_pricelist,
               'a branch with a price list locks the order')
        order2 = new_order(branch=f['b2'])
        truthy(not order2.has_branch_pricelist,
               'a branch with no price list locks nothing')

        arch = env['sale.order'].get_view(None, 'form')['arch']
        truthy('name="has_branch_pricelist"' in arch,
               'the flag is in the form, so the form can read it')
        nodes = [n for n in arch.split('<field')[1:]
                 if 'name="pricelist_id"' in n.split('>')[0]]
        truthy(nodes, 'the price list is still in the form')
        for node in nodes:
            truthy('has_branch_pricelist' in node.split('>')[0],
                   'every copy of the price list is locked: %s'
                   % node.split('>')[0][:80])
    check('T8  the order form locks the price list of the branch', t8)

    # -----------------------------------------------------------------
    def t9():
        """The lock is enforced, not merely drawn: writing a price list
        that is not the one of the branch is refused, while everything
        the rule leaves free still works."""
        order = new_order(branch=f['b1'])
        other = Pricelist.create({'name': 'T20 Other List',
                                  'currency_id': f['currency'].id,
                                  'company_id': f['company'].id})

        with expect(ValidationError):
            order.write({'pricelist_id': other.id})
        eq(order.pricelist_id, f['pl_a'],
           'the order kept the price list of its branch')

        order.write({'pricelist_id': f['pl_a'].id})
        eq(order.pricelist_id, f['pl_a'], 'the price list of the branch is fine')

        # a branch with no price list: the field stays free
        free = new_order(branch=f['b2'])
        free.write({'pricelist_id': other.id})
        eq(free.pricelist_id, other, 'no price list on the branch, no lock')

        # a price list of another company is never taken, so it locks nothing
        foreign = Pricelist.create({'name': 'T20 Foreign List',
                                    'currency_id': f['currency'].id,
                                    'company_id': False})
        b_foreign = Branch.create({'name': 'T20 Branch 5', 'code': 'T20-5',
                                   'pricelist_id': foreign.id})
        other_company = env['res.company'].create({'name': 'T20 Other Co'})
        foreign.write({'company_id': other_company.id})
        cross = new_order(branch=b_foreign)
        truthy(not cross.has_branch_pricelist,
               'a price list of another company locks nothing')
        cross.write({'pricelist_id': other.id})
        eq(cross.pricelist_id, other, 'and it does not block the order')

        # a quotation whose branch is changed keeps the right price list
        moved = new_order(branch=f['b2'])
        moved.write({'branch_id': f['b1'].id})
        eq(moved.pricelist_id, f['pl_a'],
           'changing the branch moves the price list')
    check('T9  the price list of the order cannot be changed by hand', t9)

    # -----------------------------------------------------------------
    def t10():
        """The same rule survives a save through the form of Odoo, which
        skips read-only fields: the value still ends up on the branch's
        price list."""
        with Form(env['sale.order']) as fo:
            fo.partner_id = f['partner']
            fo.branch_id = f['b2']
        order = fo.record
        order.invalidate_recordset()
        eq(order.pricelist_id, f['pl_free'],
           'no price list on the branch, the customer list is kept')

        with Form(order) as fo2:
            fo2.branch_id = f['b1']
        order.invalidate_recordset()
        eq(order.pricelist_id, f['pl_a'],
           'the branch brings its price list into the form')
    check('T10 the form keeps putting the price list of the branch', t10)

    # -----------------------------------------------------------------
    def t11():
        """The Branches tab picks an existing branch: it is a many2many
        list (its "Add" opens the search dialog, never a creation form),
        and the domain it carries keeps the choice inside the company."""
        pview = env.ref('branch_management.product_pricelist_view_branch',
                        raise_if_not_found=False)
        truthy(pview, 'the inherited form of the price list is registered')
        arch = env['product.pricelist'].get_view(None, 'form')['arch']
        truthy('name="branches"' in arch, 'the price list has the Branches tab')
        truthy('name="branch_ids"' in arch, 'and the table of branches is in it')
        truthy('<list' in arch, 'it is shown as a table, with its columns')
        truthy('name="code"' in arch, 'the branch code is a column of it')

        node = [n for n in arch.split('<field')[1:]
                if 'name="branch_ids"' in n.split('>')[0]][0]
        domain = node.split('domain="')[1].split('"')[0] if 'domain="' in node \
            else None
        truthy(domain, 'the table carries a domain')
        eq(safe_eval(domain, {'company_id': f['company'].id}),
           [('company_id', '=', f['company'].id)],
           'a price list of a company only takes its branches')
        eq(safe_eval(domain, {'company_id': False}), [],
           'a price list of no company takes them all')
        truthy('name="company_id"' in arch,
               'the company is readable from the form, which is what the'
               ' domain needs to be evaluated')
    check('T11 the tab picks an existing branch of the right company', t11)

    # -----------------------------------------------------------------
    def t12():
        """A price list created in one go with its branches behaves like
        one that was filled in later."""
        b_new = Branch.create({'name': 'T20 Branch 6', 'code': 'T20-6'})
        created = Pricelist.create({
            'name': 'T20 Made With Branches',
            'currency_id': f['currency'].id,
            'branch_ids': [(6, 0, [b_new.id])]})
        eq(b_new.pricelist_id, created, 'the branch carries the new list')
        eq(created.branch_ids, b_new, 'and the table shows it')
    check('T12 a price list can be created with its branches', t12)

except Exception:  # noqa: BLE001 - never leave the shell in a broken state
    import traceback
    LINES.append("FATAL " + traceback.format_exc())
    FAIL += 1
finally:
    print("\n".join([""] + LINES))
    print("\n==== PHASE 20: %d PASS / %d FAIL ====" % (PASS, FAIL))
    env.cr.rollback()
