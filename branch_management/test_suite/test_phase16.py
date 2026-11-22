# -*- coding: utf-8 -*-
"""Phase 16 runtime tests: a branch for every journal, so that each branch
runs its own journals.

Three decisions shape this phase (they were chosen explicitly):

* the journal is the source of truth for the branch: an entry made in the
  journal of a branch lands on that branch automatically, and an entry on
  another branch is refused with a clear error (``ValidationError``),
* the visibility of the journals follows the rule of phase 11: a restricted
  user sees the journals of his branches **plus** the journals without a
  branch, and never the journals of the other branches,
* nothing is migrated: the journals of the database keep no branch until
  they are assigned by hand, and a journal without a branch imposes no
  branch on anything.

The rule is enforced on ``account.move`` (the journal entry) and on
``account.payment`` (the payment), which are the two records that actually
use a journal.

Run with:  odoo shell -d balance_mod ... < test_phase16.py
The whole script runs in one transaction and rolls it back at the end.
"""
import csv
import os
from contextlib import contextmanager
from datetime import date

from odoo.exceptions import AccessError, ValidationError
from odoo.modules.module import get_module_path

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
# Fixtures: two branches with their own journals, one shared journal, and
# the three kinds of users used since phase 3.
# ---------------------------------------------------------------------------
def build():
    Branch = env['branch.branch']
    b1 = Branch.create({'name': 'T16 Branch One', 'code': 'T16-1'})
    b2 = Branch.create({'name': 'T16 Branch Two', 'code': 'T16-2'})
    truthy(b1.analytic_account_id, 'branch 1 must have its analytic account')

    group_user = env.ref('base.group_user')
    group_branch = env.ref('branch_management.group_branch_user')
    group_manager = env.ref('branch_management.group_branch_manager')
    group_account = env.ref('account.group_account_readonly')
    group_account_manager = env.ref('account.group_account_manager')

    def new_user(login, branch, extra_groups):
        return env['res.users'].create({
            'name': login,
            'login': login,
            'password': 't16',
            'group_ids': [(6, 0, [group_user.id, group_account.id]
                           + list(extra_groups))],
            'branch_ids': [(6, 0, [branch.id] if branch else [])],
            'default_branch_id': branch.id if branch else False,
        })

    u1 = new_user('t16_branch_one', b1, [group_branch.id])
    u2 = new_user('t16_branch_two', b2, [group_branch.id])
    manager = new_user('t16_manager', b1, [group_manager.id])
    # a branch user who may also administer the journals: without him the
    # write and create side of the rule could never be tested
    w1 = new_user('t16_journal_writer', b1,
                  [group_branch.id, group_account_manager.id])

    Journal = env['account.journal']
    j_shared = Journal.create({'name': 'T16 Shared Misc', 'code': 'T16SM',
                               'type': 'general'})
    j1 = Journal.create({'name': 'T16 Misc One', 'code': 'T16M1',
                         'type': 'general', 'branch_id': b1.id})
    j2 = Journal.create({'name': 'T16 Misc Two', 'code': 'T16M2',
                         'type': 'general', 'branch_id': b2.id})

    # The liquidity account of the payment journals: a bank journal needs
    # one to be able to post a payment.
    liquidity = env['account.account'].search(
        [('account_type', '=', 'asset_cash'),
         ('company_ids', 'in', [env.company.id])], limit=1)
    truthy(liquidity, 'the chart of accounts needs a cash account')

    bank_shared = Journal.create({'name': 'T16 Bank Shared', 'code': 'T16BS',
                                  'type': 'bank',
                                  'default_account_id': liquidity.id})
    bank1 = Journal.create({'name': 'T16 Bank One', 'code': 'T16B1',
                            'type': 'bank', 'branch_id': b1.id,
                            'default_account_id': liquidity.id})
    bank2 = Journal.create({'name': 'T16 Bank Two', 'code': 'T16B2',
                            'type': 'bank', 'branch_id': b2.id,
                            'default_account_id': liquidity.id})

    income = env['account.account'].search(
        [('account_type', '=', 'income'),
         ('company_ids', 'in', [env.company.id])], limit=1)
    expense = env['account.account'].search(
        [('account_type', '=', 'expense'),
         ('company_ids', 'in', [env.company.id])], limit=1)
    truthy(income and expense,
           'the chart of accounts needs an income and an expense account')

    # the switch that puts the analytic account of the branch on the lines
    env.company.branch_analytic_auto = True

    return {
        'b1': b1, 'b2': b2,
        'a1': b1.analytic_account_id, 'a2': b2.analytic_account_id,
        'u1': u1, 'u2': u2, 'manager': manager, 'w1': w1,
        'j_shared': j_shared, 'j1': j1, 'j2': j2,
        'bank_shared': bank_shared, 'bank1': bank1, 'bank2': bank2,
        'income': income, 'expense': expense,
        'partner': env['res.partner'].create({'name': 'T16 Customer'}),
        'all_journals': {'shared': j_shared, 'one': j1, 'two': j2,
                         'bank_shared': bank_shared, 'bank1': bank1,
                         'bank2': bank2},
    }


def new_entry(journal, branch=None, extra=None):
    """A balanced miscellaneous entry, without a branch unless asked."""
    vals = {
        'move_type': 'entry',
        'journal_id': journal.id,
        'line_ids': [
            (0, 0, {'name': 'T16 debit', 'account_id': f['expense'].id,
                    'debit': 100.0, 'credit': 0.0}),
            (0, 0, {'name': 'T16 credit', 'account_id': f['income'].id,
                    'debit': 0.0, 'credit': 100.0}),
        ],
    }
    if branch:
        vals['branch_id'] = branch.id
    if extra:
        vals.update(extra)
    return env['account.move'].create(vals)


def new_payment(journal, branch=None, amount=50.0):
    vals = {
        'payment_type': 'inbound',
        'partner_type': 'customer',
        'partner_id': f['partner'].id,
        'amount': amount,
        'journal_id': journal.id,
    }
    if branch:
        vals['branch_id'] = branch.id
    return env['account.payment'].create(vals)


def new_invoice(branch):
    move = env['account.move'].create({
        'move_type': 'out_invoice',
        'partner_id': f['partner'].id,
        'branch_id': branch.id if branch else False,
        'invoice_date': date.today(),
        'invoice_line_ids': [(0, 0, {
            'name': 'T16 invoice line',
            'quantity': 1.0,
            'price_unit': 300.0,
            'account_id': f['income'].id,
        })],
    })
    move.action_post()
    return move


def access_rows():
    path = os.path.join(get_module_path('branch_management'),
                        'security', 'ir.access.csv')
    with open(path, newline='', encoding='utf-8') as handle:
        return list(csv.DictReader(handle))


def domain_of(row_id):
    return next(r['domain'] for r in access_rows() if r['id'] == row_id)


try:
    f = build()

    # -----------------------------------------------------------------
    def t1():
        """The field exists on the journal, is stored and indexed like on
        the entry, checks the company, and is shown by the three views of
        the journal (form, list, search)."""
        field = env['account.journal']._fields['branch_id']
        eq(field.type, 'many2one', 'branch_id of the journal')
        eq(field.comodel_name, 'branch.branch', 'it points at a branch')
        truthy(field.store, 'the branch must be stored')
        truthy(field.index, 'the branch is indexed, as on the entry')
        truthy(field.check_company, 'a journal and its branch share a company')
        for xmlid in ('branch_management.account_journal_form_branch',
                      'branch_management.account_journal_tree_branch',
                      'branch_management.account_journal_search_branch'):
            view = env.ref(xmlid, raise_if_not_found=False)
            truthy(view, '%s is not registered' % xmlid)
            truthy('branch_id' in view.arch, '%s does not carry it' % xmlid)
        # and the form really renders it
        fields_view = env['account.journal'].get_view(
            env.ref('branch_management.account_journal_form_branch').id, 'form')
        truthy('branch_id' in fields_view['arch'], 'the form arch lost it')
    check('T1  the field and its three views', t1)

    # -----------------------------------------------------------------
    def t2():
        """The rule of the journals is the rule of phase 11, word for word:
        global (no group), full crud, and the very same domain as the one
        on the entries."""
        rows = access_rows()
        row = next((r for r in rows
                    if r['id'] == 'access_account_journal_branch_restriction'),
                   None)
        truthy(row, 'the rule of the journals is missing from ir.access.csv')
        eq(row['model_id'], 'account.journal', 'it is on the journals')
        eq(row['operation'], 'crud', 'it covers read, write, create, unlink')
        eq(row['group_id/id'], '',
           'the rule is global: it restricts every user, not a group')
        eq(row['domain'],
           domain_of('access_account_move_branch_restriction'),
           'the journal rule and the entry rule are the same condition')
        truthy('branch_visible_ids' in row['domain'],
               'the condition must be built from the branches of the reader')
        truthy("('branch_id', '=', False)" in row['domain'],
               'a journal without a branch stays visible (rule of phase 11)')
        # loaded by Odoo, not only present in the file
        loaded = env['ir.access'].search(
            [('id', '=', env.ref('branch_management'
                                 '.access_account_journal_branch_restriction').id)])
        eq(len(loaded), 1, 'the row is loaded as an ir.access record')
        truthy(not loaded.group_id, 'and it has no group')
        eq(loaded.kind, 'restriction',
           'so Odoo classifies it as a restriction, not as a permission')
    check('T2  the global rule of the journals', t2)

    # -----------------------------------------------------------------
    def t3():
        """A restricted user sees the journals of his own branches plus the
        journals without a branch, and never the journals of the others."""
        all_ids = {journal.id for journal in f['all_journals'].values()}
        seen1 = set(env['account.journal'].with_user(f['u1']).search([]).ids)
        seen2 = set(env['account.journal'].with_user(f['u2']).search([]).ids)
        seenm = set(env['account.journal'].with_user(f['manager']).search([]).ids)
        seena = set(env['account.journal'].search([]).ids)

        eq(seen1 & all_ids, {f['j1'].id, f['j_shared'].id, f['bank1'].id,
                             f['bank_shared'].id},
           'user 1 sees his journals and the shared ones')
        eq(seen2 & all_ids, {f['j2'].id, f['j_shared'].id, f['bank2'].id,
                             f['bank_shared'].id},
           'user 2 sees his journals and the shared ones')
        eq(seenm & all_ids, all_ids, 'a manager sees every journal')
        eq(seena & all_ids, all_ids, 'and so does the admin')
        truthy(seen1 and seen2, 'both users still have a journal to use')
    check('T3  who sees which journal', t3)

    # -----------------------------------------------------------------
    def t4():
        """A journal of the other branch cannot be read, written nor
        created - and his own journals, and the shared ones, are still
        usable. Two users are used here: a plain branch user, who only has
        the right to read, and a branch user who is also an accountant
        manager, so that the *write* side of the rule is really exercised
        (a plain reader would be refused for having no right to write at
        all, and that would prove nothing about the branches)."""
        Read = env['account.journal'].with_user(f['u1'])
        Write = env['account.journal'].with_user(f['w1'])

        with expect(AccessError):
            Read.browse(f['j2'].id).read(['name'])
        with expect(AccessError):
            Read.browse(f['bank2'].id).read(['name'])
        with expect(AccessError):
            env['account.journal'].with_user(f['u2']).browse(f['j1'].id) \
                .read(['name'])

        with expect(AccessError):
            Write.browse(f['j2'].id).read(['name'])
        with expect(AccessError):
            Write.browse(f['j2'].id).write({'name': 'T16 renamed'})
        with expect(AccessError):
            Write.browse(f['bank2'].id).write({'name': 'T16 renamed'})
        with expect(AccessError):
            Write.create({'name': 'T16 Wrong Branch', 'code': 'T16WB',
                          'type': 'general', 'branch_id': f['b2'].id})

        # his own journals, and the shared ones, are still usable
        Read.browse(f['j1'].id).read(['name'])
        Read.browse(f['j_shared'].id).read(['name'])
        Write.browse(f['j1'].id).write({'name': f['j1'].name})
        Write.browse(f['j_shared'].id).write({'name': f['j_shared'].name})
        own = Write.create({'name': 'T16 Own Journal', 'code': 'T16OJ',
                            'type': 'general', 'branch_id': f['b1'].id})
        eq(own.branch_id, f['b1'],
           'a restricted user still creates a journal of his own branch')
        shared = Write.create({'name': 'T16 Own Shared', 'code': 'T16OS',
                               'type': 'general'})
        truthy(not shared.branch_id, 'and one without a branch too')
    check('T4  the journals of the other branch are off limits', t4)

    # -----------------------------------------------------------------
    def t5():
        """An entry made in the journal of a branch lands on that branch,
        without anyone saying it, and a shared journal imposes nothing."""
        move = new_entry(f['j1'])
        eq(move.branch_id, f['b1'],
           'the branch of the journal is given to the entry')
        eq({line.branch_id for line in move.line_ids}, {f['b1']},
           'and to every one of its journal items')
        shared = new_entry(f['j_shared'])
        truthy(not shared.branch_id, 'a journal without a branch imposes none')
        truthy(all(not line.branch_id for line in shared.line_ids),
               'nor on its journal items')
        # an entry explicitly on a branch, in a shared journal, keeps it
        kept = new_entry(f['j_shared'], branch=f['b2'])
        eq(kept.branch_id, f['b2'],
           'a shared journal leaves the branch of the entry alone')
    check('T5  the journal gives its branch to the entry', t5)

    # -----------------------------------------------------------------
    def t6():
        """Moving an entry to another journal moves it to the branch of that
        journal, and a journal without a branch changes nothing."""
        move = new_entry(f['j_shared'], branch=f['b1'])
        eq(move.branch_id, f['b1'], 'starts on branch 1')
        move.write({'journal_id': f['j2'].id})
        eq(move.branch_id, f['b2'], 'the new journal brings its branch')
        eq({line.branch_id for line in move.line_ids}, {f['b2']},
           'the journal items follow to branch 2')
        move.write({'journal_id': f['j_shared'].id})
        eq(move.branch_id, f['b2'],
           'a journal without a branch imposes nothing')
        move.write({'journal_id': f['j1'].id})
        eq(move.branch_id, f['b1'], 'and back to a journal of branch 1')
    check('T6  changing the journal changes the branch', t6)

    # -----------------------------------------------------------------
    def t7():
        """A branch that disagrees with the journal is refused on creation,
        with a clear error, instead of being corrected quietly."""
        with expect(ValidationError):
            new_entry(f['j1'], branch=f['b2'])
        with expect(ValidationError):
            new_entry(f['j2'], branch=f['b1'])
        # an entry whose branch is left empty is *filled* by the journal
        # instead of being refused: nothing was said, so the journal says it
        filled = new_entry(f['j1'], branch=None, extra={'branch_id': False})
        eq(filled.branch_id, f['b1'], 'the journal fills the empty branch')
        # the same journal with its own branch, or with none, is accepted
        ok = new_entry(f['j1'], branch=f['b1'])
        eq(ok.branch_id, f['b1'], 'the journal with its own branch works')
    check('T7  a wrong branch is refused at creation', t7)

    # -----------------------------------------------------------------
    def t8():
        """And refused on write, whether the branch is written alone, or
        together with a journal that says something else."""
        move = new_entry(f['j1'])
        with expect(ValidationError):
            move.write({'branch_id': f['b2'].id})
        eq(move.branch_id, f['b1'], 'the entry did not move')
        with expect(ValidationError):
            move.write({'journal_id': f['j2'].id, 'branch_id': f['b1'].id})
        env.invalidate_all()
        eq(move.branch_id, f['b1'], 'and neither did the journal')
        # giving the branch of the new journal with it, is accepted
        move.write({'journal_id': f['j2'].id, 'branch_id': f['b2'].id})
        eq(move.branch_id, f['b2'], 'the two values can be written together')
        # the rule applies to every user, the admin included
        with expect(ValidationError):
            move.write({'branch_id': f['b1'].id})
    check('T8  a wrong branch is refused on write', t8)

    # -----------------------------------------------------------------
    def t9():
        """The branch of the journal is proposed as soon as the journal is
        selected, which is what makes the rule invisible in the form."""
        move = env['account.move'].new({'journal_id': f['j_shared'].id})
        move._onchange_journal_branch()
        truthy(not move.branch_id, 'a shared journal proposes nothing')
        move.journal_id = f['j1']
        move._onchange_journal_branch()
        eq(move.branch_id, f['b1'], 'a journal of branch 1 proposes branch 1')
        move.journal_id = f['j2']
        move._onchange_journal_branch()
        eq(move.branch_id, f['b2'], 'and branch 2 proposes branch 2')

        payment = env['account.payment'].new({'journal_id': f['bank1'].id})
        payment._onchange_journal_branch()
        eq(payment.branch_id, f['b1'], 'the same on the payment')
    check('T9  the journal proposes its branch', t9)

    # -----------------------------------------------------------------
    def t10():
        """Every journal item of an entry made in the journal of a branch
        carries the analytic account of that branch."""
        move = new_entry(f['j1'])
        env.flush_all()
        truthy(move.line_ids, 'the entry has journal items')
        for line in move.line_ids:
            distribution = line.analytic_distribution or {}
            truthy(str(f['a1'].id) in distribution,
                   'line %s carries no analytic of branch 1: %r'
                   % (line.name, distribution))
            truthy(str(f['a2'].id) not in distribution,
                   'line %s carries the analytic of branch 2: %r'
                   % (line.name, distribution))
        # moving the entry to the journal of the other branch rebuilds it
        move.write({'journal_id': f['j2'].id})
        env.flush_all()
        for line in move.line_ids:
            distribution = line.analytic_distribution or {}
            truthy(str(f['a2'].id) in distribution,
                   'line %s was not rebuilt for branch 2: %r'
                   % (line.name, distribution))
            truthy(str(f['a1'].id) not in distribution,
                   'line %s kept the analytic of branch 1: %r'
                   % (line.name, distribution))
    check('T10 the journal items carry the analytic of the branch', t10)

    # -----------------------------------------------------------------
    def t11():
        """The payment follows the same rule: the journal gives its branch,
        a wrong branch is refused, and another journal moves the payment."""
        payment = new_payment(f['bank1'])
        eq(payment.branch_id, f['b1'],
           'the branch of the payment journal is given to the payment')
        with expect(ValidationError):
            new_payment(f['bank1'], branch=f['b2'])
        with expect(ValidationError):
            new_payment(f['bank2'], branch=f['b1'])
        shared = new_payment(f['bank_shared'], branch=f['b2'])
        eq(shared.branch_id, f['b2'],
           'a journal without a branch leaves the branch of the payment')
        payment.write({'journal_id': f['bank2'].id})
        eq(payment.branch_id, f['b2'],
           'changing the journal moves the payment to its branch')
        with expect(ValidationError):
            payment.write({'branch_id': f['b1'].id})
        env.invalidate_all()
        eq(payment.branch_id, f['b2'], 'the payment did not move')
    check('T11 the payment follows its journal', t11)

    # -----------------------------------------------------------------
    def t12():
        """End to end: the entry created when the payment is posted carries
        the branch of the journal the payment was made in."""
        payment = new_payment(f['bank1'], amount=75.0)
        payment.action_post()
        truthy(payment.move_id, 'the payment was posted as an entry')
        eq(payment.move_id.journal_id, f['bank1'], 'in its own journal')
        eq(payment.move_id.branch_id, f['b1'],
           'the entry of the payment is on the branch of the journal')
        eq(payment.branch_id, f['b1'], 'and the payment still agrees')
        eq({line.branch_id for line in payment.move_id.line_ids}, {f['b1']},
           'every journal item of the payment carries the branch')
    check('T12 the entry of a posted payment', t12)

    # -----------------------------------------------------------------
    def t13():
        """The wizard that registers a payment proposes the branch of the
        journal of the payment, which wins over the branch of the invoice;
        a payment journal without a branch keeps the branch of the invoice."""
        invoice = new_invoice(f['b1'])
        eq(invoice.branch_id, f['b1'], 'the invoice is on branch 1')
        wizard = env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids,
        ).create({})
        eq(wizard.branch_id, f['b1'],
           'with the default journal, the branch of the invoice is proposed')
        wizard.journal_id = f['bank2']
        eq(wizard.branch_id, f['b2'],
           'a payment journal of branch 2 wins over the invoice')
        wizard.journal_id = f['bank_shared']
        eq(wizard.branch_id, f['b1'],
           'a payment journal without a branch keeps the invoice branch')
        # the payment the wizard really builds follows the journal it chose
        wizard.journal_id = f['bank2']
        eq(wizard.branch_id, f['b2'], 'back to the journal of branch 2')
        payments = wizard._create_payments()
        eq(len(payments), 1, 'the wizard created one payment')
        eq(payments.journal_id, f['bank2'], 'in the journal it was given')
        eq(payments.branch_id, f['b2'],
           'the payment of the wizard is on the branch of its journal')
    check('T13 the payment wizard proposes the branch of its journal', t13)

except Exception:  # noqa: BLE001 - never leave the shell in a broken state
    import traceback
    LINES.append("FATAL " + traceback.format_exc())
    FAIL += 1
finally:
    print("\n".join([""] + LINES))
    print("\n==== PHASE 16: %d PASS / %d FAIL ====" % (PASS, FAIL))
    env.cr.rollback()
