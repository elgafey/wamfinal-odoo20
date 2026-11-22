# -*- coding: utf-8 -*-
"""Phase 17 runtime tests: the branch picks the sales journal of the order.

Three decisions shape this phase (they were chosen explicitly):

* the branch of the order looks for the sales journal of that branch and
  makes it the journal of the order — the other half of the rule of phase
  16, where the journal decides the branch of the entry,
* when a branch has no sales journal of its own, a journal shared by every
  branch (a journal with no branch) is used, and only then nothing at all,
  which leaves Odoo its own rule (lowest sequence sales journal),
* the order follows the journal: picking a journal by hand moves the order
  onto the branch of that journal, exactly as on the entry itself.

The journal field of the order, until now hidden behind the developer mode
(``groups="base.group_no_one"``), is shown in the "Invoicing" group of the
form, because it is now chosen automatically and has to be readable.

Run with:  odoo shell -d balance_mod ... < test_phase17.py
The whole script runs in one transaction and rolls it back at the end.
"""
from contextlib import contextmanager

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
# Fixtures: branch one owns two sales journals (the lowest sequence must be
# the one proposed), branch two owns none yet, and one sales journal is
# shared by every branch with a sequence lower than any other shared sales
# journal of the database so that "the shared journal" is this one.
# ---------------------------------------------------------------------------
def build():
    Branch = env['branch.branch']
    Journal = env['account.journal']

    b1 = Branch.create({'name': 'T17 Branch One', 'code': 'T17-1'})
    b2 = Branch.create({'name': 'T17 Branch Two', 'code': 'T17-2'})

    js1_first = Journal.create({'name': 'T17 Sales One', 'code': 'T17SA',
                                'type': 'sale', 'branch_id': b1.id,
                                'sequence': 10})
    js1_last = Journal.create({'name': 'T17 Sales One Bis', 'code': 'T17SB',
                               'type': 'sale', 'branch_id': b1.id,
                               'sequence': 20})
    jshared = Journal.create({'name': 'T17 Sales Shared', 'code': 'T17SS',
                              'type': 'sale', 'sequence': 1})

    income = env['account.account'].search(
        [('account_type', 'in', ('income', 'income_other'))], limit=1)
    receivable = env['account.account'].search(
        [('account_type', '=', 'asset_receivable')], limit=1)
    truthy(income, 'no income account')
    truthy(receivable, 'no receivable account')

    partner = env['res.partner'].create({'name': 'T17 Customer'})
    partner.write({'property_account_receivable_id': receivable.id})
    product = env['product.product'].create({
        'name': 'T17 Product', 'list_price': 100.0,
        'invoice_policy': 'order',
        'property_account_income_id': income.id})

    return {'b1': b1, 'b2': b2,
            'js1_first': js1_first, 'js1_last': js1_last,
            'jshared': jshared,
            'partner': partner, 'product': product, 'income': income}


def new_order(branch=None, journal=None, line=True):
    """A quotation, saying its branch (and its journal when asked)."""
    vals = {'partner_id': f['partner'].id}
    if branch is not None:
        vals['branch_id'] = branch.id if branch else False
    if journal is not None:
        vals['journal_id'] = journal.id if journal else False
    if line:
        vals['order_line'] = [(0, 0, {'product_id': f['product'].id,
                                      'product_uom_qty': 1,
                                      'price_unit': 100.0})]
    return env['sale.order'].create(vals)


try:
    f = build()

    # -----------------------------------------------------------------
    def t1():
        """The journal of the order is still the same field Odoo declares,
        still stored and still editable, but it is now recomputed from the
        branch of the order: that single line is what makes the branch pick
        the journal."""
        field = env['sale.order']._fields['journal_id']
        eq(field.comodel_name, 'account.journal', 'journal_id points at a journal')
        eq(field.compute, '_compute_journal_id', 'it keeps the compute of Odoo')
        truthy(field.store, 'the journal of the order is stored')
        truthy(not field.readonly, 'and it can still be chosen by hand')
        depends, _context = field.get_depends(env['sale.order'])
        truthy('branch_id' in depends,
               'the journal is recomputed when the branch changes')
        eq(tuple(depends), ('branch_id',),
           'the branch is the only thing the journal follows')
    check('T1  the journal follows the branch', t1)

    # -----------------------------------------------------------------
    def t2():
        """The order lands on the sales journal of its branch, and on the
        first one of them when the branch owns several."""
        order = new_order(branch=f['b1'])
        eq(order.journal_id, f['js1_first'],
           'the first sales journal of the branch is proposed')
        eq(order.journal_id.type, 'sale', 'and it is a sales journal')
        eq(order.journal_id.branch_id, f['b1'], 'and it belongs to the branch')
        eq(order.journal_id.company_id, order.company_id,
           'and it is a journal of the company of the order')
    check('T2  the branch proposes its own sales journal', t2)

    # -----------------------------------------------------------------
    def t3():
        """A branch without a sales journal of its own falls back to a
        journal shared by every branch (a journal with no branch imposes
        no branch on anything, README section 16)."""
        order = new_order(branch=f['b2'])
        truthy(not env['account.journal'].search(
            [('branch_id', '=', f['b2'].id)]),
            'branch 2 really has no journal yet')
        eq(order.journal_id, f['jshared'],
           'a shared sales journal is used instead')
        truthy(not order.journal_id.branch_id, 'and it carries no branch')
    check('T3  a branch without journal falls back to a shared one', t3)

    # -----------------------------------------------------------------
    def t4():
        """An order with no branch gets no journal at all: there is nothing
        to look for, and such an order cannot be confirmed anyway."""
        order = new_order(branch=False)
        truthy(not order.branch_id, 'the order has no branch')
        truthy(not order.journal_id, 'and so no journal is proposed')
    check('T4  no branch, no journal', t4)

    # -----------------------------------------------------------------
    def t5():
        """Moving the order to another branch moves it to the journal of
        that branch, including when the journal is created later on."""
        order = new_order(branch=f['b1'])
        eq(order.journal_id, f['js1_first'], 'starts on the journal of branch 1')

        order.write({'branch_id': f['b2'].id})
        eq(order.journal_id, f['jshared'], 'branch 2 has no journal of its own')

        f['js2_first'] = env['account.journal'].create(
            {'name': 'T17 Sales Two', 'code': 'T17S2', 'type': 'sale',
             'branch_id': f['b2'].id, 'sequence': 10})
        f['js2_last'] = env['account.journal'].create(
            {'name': 'T17 Sales Two Bis', 'code': 'T17S3', 'type': 'sale',
             'branch_id': f['b2'].id, 'sequence': 20})

        order.write({'branch_id': f['b1'].id})
        eq(order.journal_id, f['js1_first'], 'and back to the journal of branch 1')
        order.write({'branch_id': f['b2'].id})
        eq(order.journal_id, f['js2_first'],
           'now that branch 2 has a journal, that one is proposed')
    check('T5  changing the branch changes the journal', t5)

    # -----------------------------------------------------------------
    def t6():
        """The order follows the journal it is given: it moves to the
        branch of the journal, and keeps the journal that was chosen
        instead of being sent back to the first journal of that branch.
        A journal without a branch imposes nothing."""
        order = new_order(branch=f['b1'])
        eq(order.journal_id, f['js1_first'], 'starts on the journal of branch 1')

        order.write({'journal_id': f['js2_last'].id})
        eq(order.branch_id, f['b2'], 'the order moves to the branch of the journal')
        eq(order.journal_id, f['js2_last'],
           'and keeps the journal chosen, not the first of branch 2')

        order.write({'journal_id': f['js1_last'].id})
        eq(order.branch_id, f['b1'], 'and back to branch 1')
        eq(order.journal_id, f['js1_last'], 'still the journal that was chosen')

        order.write({'journal_id': f['jshared'].id})
        eq(order.branch_id, f['b1'], 'a shared journal leaves the branch alone')
        eq(order.journal_id, f['jshared'], 'and stays the journal of the order')
    check('T6  the order follows the journal', t6)

    # -----------------------------------------------------------------
    def t7():
        """The journal wins at creation too, over the branch the form
        proposes (the default branch of the user)."""
        order = new_order(branch=f['b1'], journal=f['js2_last'])
        eq(order.branch_id, f['b2'],
           'the journal decides the branch, even at creation')
        eq(order.journal_id, f['js2_last'], 'and the journal is kept')
        # a journal without a branch leaves the branch that was given
        plain = new_order(branch=f['b1'], journal=f['jshared'])
        eq(plain.branch_id, f['b1'], 'a shared journal imposes nothing')
        eq(plain.journal_id, f['jshared'], 'and is used as it was given')
    check('T7  at creation the journal decides the branch', t7)

    # -----------------------------------------------------------------
    def t8():
        """What the form does: the branch proposes the journal, and a
        journal picked by hand proposes its branch without the branch
        sending the journal back to the first one of the branch."""
        order = env['sale.order'].new({'partner_id': f['partner'].id,
                                       'branch_id': f['b1'].id})
        eq(order.journal_id, f['js1_first'],
           'the form proposes the journal of the branch')

        order.journal_id = f['js2_last']
        order._onchange_journal_branch()
        eq(order.branch_id, f['b2'], 'a journal of branch 2 proposes branch 2')
        eq(order.journal_id, f['js2_last'],
           'and does not send the order back to the first journal of branch 2')

        order.journal_id = f['jshared']
        order._onchange_journal_branch()
        eq(order.branch_id, f['b2'], 'a journal without a branch proposes nothing')
        eq(order.journal_id, f['jshared'], 'and keeps the journal chosen')
    check('T8  the journal proposes its branch in the form', t8)

    # -----------------------------------------------------------------
    def t9():
        """Only sales journals are ever proposed: a journal of the branch
        that is not a sales journal is ignored, however low its sequence."""
        other = env['account.journal'].create(
            {'name': 'T17 Misc One', 'code': 'T17M1', 'type': 'general',
             'branch_id': f['b1'].id, 'sequence': 1})
        eq(other.branch_id, f['b1'], 'a general journal of the branch exists')
        order = new_order(branch=f['b1'])
        eq(order.journal_id, f['js1_first'],
           'a general journal of the branch is never proposed')
        eq(order.journal_id.type, 'sale', 'only sales journals are proposed')
    check('T9  only sales journals are proposed', t9)

    # -----------------------------------------------------------------
    def t10():
        """End to end: the invoice built from a confirmed order is created
        in the journal of the branch and on the branch of the order, so the
        two agree and the rule of phase 16 is satisfied."""
        order = new_order(branch=f['b1'])
        eq(order.journal_id, f['js1_first'], 'the order knows its journal')
        order.action_confirm()
        invoices = order._create_invoices()
        truthy(invoices, 'no invoice was created')
        eq(invoices.journal_id, f['js1_first'],
           'the invoice is created in the journal of the branch')
        eq(invoices.branch_id, f['b1'], 'and on the branch of the order')
        eq(invoices.journal_id.branch_id, invoices.branch_id,
           'journal and invoice agree (rule of phase 16)')
    check('T10 the invoice is created in the journal of the branch', t10)

    # -----------------------------------------------------------------
    def t11():
        """Even when the order carries no journal — an order written before
        this rule, or a journal given a branch after the order was made —
        the invoice still goes to the journal of its branch."""
        order = new_order(branch=f['b1'], journal=False)
        truthy(not order.journal_id, 'the order carries no journal')
        values = order._prepare_invoice()
        eq(values.get('journal_id'), f['js1_first'].id,
           'the invoice still gets the journal of its branch')
        eq(values.get('branch_id'), f['b1'].id, 'and the branch of the order')

        # an order whose journal was chosen keeps it
        chosen = new_order(branch=f['b1'], journal=f['js1_last'])
        values = chosen._prepare_invoice()
        eq(values.get('journal_id'), f['js1_last'].id,
           'a journal chosen on the order is passed on as it is')
    check('T11 the invoice still gets the journal of its branch', t11)

    # -----------------------------------------------------------------
    def t12():
        """The journal is no longer hidden behind the developer mode: our
        view rewrites the groups of the field, and a user who is not in
        base.group_no_one still finds it in the form."""
        view = env.ref('branch_management.view_order_form_sale_journal',
                       raise_if_not_found=False)
        truthy(view, 'the view that shows the journal is not registered')
        truthy('journal_id' in view.arch, 'it does not touch the journal')
        truthy('base.group_no_one' not in view.arch,
               'the journal is no longer behind the developer mode')
        truthy('base.group_user' in view.arch,
               'every internal user may see it')

        groups = env.user.group_ids - env.ref('base.group_no_one')
        plain = env['res.users'].create({
            'name': 'T17 Plain', 'login': 't17_plain', 'password': 't17',
            'group_ids': [(6, 0, groups.ids)]})
        truthy(not plain.has_group('base.group_no_one'),
               'the reader is not in the developer mode')
        arch = env['sale.order'].with_user(plain).get_view(
            env.ref('sale.view_order_form').id, 'form')['arch']
        truthy('name="journal_id"' in arch,
               'a normal user finds the journal in the form')
    check('T12 the journal is visible in the form', t12)

except Exception:  # noqa: BLE001 - never leave the shell in a broken state
    import traceback
    LINES.append("FATAL " + traceback.format_exc())
    FAIL += 1
finally:
    print("\n".join([""] + LINES))
    print("\n==== PHASE 17: %d PASS / %d FAIL ====" % (PASS, FAIL))
    env.cr.rollback()
