# -*- coding: utf-8 -*-
"""Phase 15 runtime tests: the Partner Ledger and the Aging reports stay
inside the branch of the user.

The accounting reports read the journal items with
``_search(domain, bypass_access=True)`` (the core comment says it out loud:
"The bypass below will ignore access rules"), which is exactly how the
global ``ir.access`` rule of this module gets skipped.  Phase 15 puts the
condition back inside the query, through the single choke point both reports
go through: ``account.report._get_options_domain()``.

Every total is asserted as *the value read before the fixtures were created
+ the value the fixtures are worth*, so the harness works on a scratch
database that already contains data.

Run with:  odoo shell -d balance_mod ... < test_phase15.py
The whole script runs in one transaction and rolls it back at the end.
"""
import ast
import csv
import os
from datetime import date

from odoo.modules.module import get_module_path
from odoo.tools.safe_eval import safe_eval

PASS = FAIL = SKIP = 0
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


def skip(label, msg=""):
    """The report engine (``account_reports``) is optional: without it there
    is no report to restrict, so those tests are reported as skipped."""
    global SKIP
    SKIP += 1
    LINES.append("SKIP  %s :: %s" % (label, msg))


# ---------------------------------------------------------------------------
# The three reports, and the guard used by every report test
# ---------------------------------------------------------------------------
REPORTS = ('account_reports.partner_ledger_report',
           'account_reports.aged_receivable_report',
           'account_reports.aged_payable_report')
ENGINE = env.ref(REPORTS[0], raise_if_not_found=False) is not None
REASON = 'account_reports is not installed on this database'


# ---------------------------------------------------------------------------
# Helpers on the report engine
# ---------------------------------------------------------------------------
def report_top(report, user):
    """``(first line, {expression_label: no_format})``; ``(None, {})`` when
    the report has nothing to show at all."""
    r = report.with_user(user)
    info = r.get_report_information(r.get_options({}))
    lines = info.get('lines') or []
    if not lines:
        return None, {}
    top = lines[0]
    return top, {c.expression_label: c.no_format for c in (top.columns or [])}


def report_line(report, user, index=0):
    line, values = report_top(report, user)
    truthy(line, "%s returned no line at all" % report.name)
    truthy(index == 0, 'only the total line of the report is read here')
    return line, values


def report_total(report, user, column):
    line, values = report_line(report, user)
    truthy(column in values,
           "%s has no column %r (got %r)" % (report.name, column, sorted(values)))
    return values[column]


def report_names(report, user):
    r = report.with_user(user)
    info = r.get_report_information(r.get_options({}))
    return [str(l.name) for l in (info.get('lines') or [])]


def options_domain(report, user, scope='strict_range'):
    """The domain the core builds for ``report`` as ``user`` - Phase 15 is
    only allowed to add its condition to it, never to rewrite it."""
    r = report.with_user(user)
    return r._get_options_domain(r.get_options({}), scope)


def branch_leaves(domain):
    """Every ``(branch_id, ...)`` leaf of a domain, in order."""
    return [item for item in list(domain)
            if isinstance(item, tuple) and item[0] == 'branch_id']


def branch_domain(report, user, scope='strict_range'):
    """The branch leaves of the domain, as ``repr`` so that the two of them
    (the second one holds a list) can be compared in a set."""
    return {repr(item)
            for item in branch_leaves(options_domain(report, user, scope))}


def expected_branch(branch):
    """The two leaves the CSV rule and the report rule must both produce."""
    return {
        repr(('branch_id', '=', False)),
        repr(('branch_id', 'in', [branch.id])),
    }


# ---------------------------------------------------------------------------
# Fixtures: two branches, three kinds of users, invoices and vendor bills
# ---------------------------------------------------------------------------
def build():
    Branch = env['branch.branch']
    b1 = Branch.create({'name': 'T15 Branch One', 'code': 'T15-1'})
    b2 = Branch.create({'name': 'T15 Branch Two', 'code': 'T15-2'})

    group_user = env.ref('base.group_user')
    group_branch = env.ref('branch_management.group_branch_user')
    group_manager = env.ref('branch_management.group_branch_manager')
    group_account = env.ref('account.group_account_readonly')

    def new_user(login, branch, extra_groups):
        return env['res.users'].create({
            'name': login,
            'login': login,
            'password': 't15',
            'group_ids': [(6, 0, [group_user.id, group_account.id]
                           + list(extra_groups))],
            'branch_ids': [(6, 0, [branch.id] if branch else [])],
            'default_branch_id': branch.id if branch else False,
        })

    u1 = new_user('t15_branch_one', b1, [group_branch.id])
    u2 = new_user('t15_branch_two', b2, [group_branch.id])
    # The manager group implies "Branch User", but a manager is not restricted
    # (same rule as the access domains, README section 3).
    manager = new_user('t15_manager', b1, [group_manager.id])

    income = env['account.account'].search(
        [('account_type', '=', 'income'),
         ('company_ids', 'in', [env.company.id])], limit=1)
    expense = env['account.account'].search(
        [('account_type', '=', 'expense'),
         ('company_ids', 'in', [env.company.id])], limit=1)
    truthy(income and expense,
           'the chart of accounts needs an income and an expense account')

    data = {
        'b1': b1, 'b2': b2, 'u1': u1, 'u2': u2, 'manager': manager,
        'pl': env.ref(REPORTS[0], raise_if_not_found=False),
        'aged_receivable': env.ref(REPORTS[1], raise_if_not_found=False),
        'aged_payable': env.ref(REPORTS[2], raise_if_not_found=False),
        'general_ledger': env['account.report'].search(
            [('name', '=', 'General Ledger')], limit=1),
        'users': {'admin': env.user, 'u1': u1,
                  'u2': u2, 'manager': manager},
    }

    # ---------------------------------------------------------- baseline --
    # What every user reads *before* the fixtures exist.  The assertions of
    # this phase are "baseline + what the fixtures are worth", which keeps
    # the harness valid on a scratch database that already holds data.
    data['base'] = {}
    if ENGINE:
        for key in ('pl', 'aged_receivable', 'aged_payable'):
            for user_key, user in data['users'].items():
                line, values = report_top(data[key], user)
                for column in ('debit', 'credit', 'total'):
                    data['base'][(key, user_key, column)] = \
                        values.get(column) or 0.0

    # ---------------------------------------------------------- documents --
    def new_partner(name):
        return env['res.partner'].create({'name': name})

    def new_doc(move_type, name, partner, branch, amount, account):
        move = env['account.move'].create({
            'move_type': move_type,
            'partner_id': partner.id,
            'branch_id': branch.id if branch else False,
            'invoice_date': date.today(),
            'invoice_line_ids': [(0, 0, {
                'name': name,
                'quantity': 1.0,
                'price_unit': amount,
                'account_id': account.id,
            })],
        })
        move.action_post()
        return move

    out1 = new_doc('out_invoice', 'T15 out alpha', new_partner('T15 Cust Alpha'), b1, 1000.0, income)
    out2 = new_doc('out_invoice', 'T15 out beta', new_partner('T15 Cust Beta'), b2, 2000.0, income)
    out3 = new_doc('out_invoice', 'T15 out none', new_partner('T15 Cust None'), None, 400.0, income)
    in1 = new_doc('in_invoice', 'T15 in alpha', new_partner('T15 Vend Alpha'), b1, 700.0, expense)
    in2 = new_doc('in_invoice', 'T15 in beta', new_partner('T15 Vend Beta'), b2, 800.0, expense)
    in3 = new_doc('in_invoice', 'T15 in none', new_partner('T15 Vend None'), None, 100.0, expense)

    env.flush_all()
    moves = out1 + out2 + out3 + in1 + in2 + in3
    data['moves'] = moves
    data['lines'] = moves.line_ids
    return data


def grew(report_key, user_key, column, added, msg):
    """The column must now read *what it read before the fixtures* + ``added``."""
    line, values = report_line(f[report_key], f['users'][user_key])
    truthy(column in values,
           "%s has no column %r (got %r)"
           % (f[report_key].name, column, sorted(values)))
    actual = values[column] or 0.0
    want = f['base'][(report_key, user_key, column)] + added
    eq(round(actual, 2), round(want, 2), msg)


try:
    f = build()

    # -----------------------------------------------------------------
    def t1():
        """Exactly three reports are flagged - and the sibling reports that
        share the partner ledger handler lineage are not (they have their
        own handler, and their own ``_name``)."""
        truthy(ENGINE, REASON)
        all_reports = env['account.report'].search([])
        flagged = {r.name for r in all_reports if r._is_branch_restricted_report()}
        eq(flagged, {'Partner Ledger', 'Aged Receivable', 'Aged Payable'},
           'the flagged reports')
        for other in ('General Ledger', 'Trial Balance', 'Balance Sheet',
                      'Customer Statement', 'Open Items'):
            report = env['account.report'].search([('name', '=', other)], limit=1)
            if report:
                eq(report._is_branch_restricted_report(), False,
                   '%s must stay untouched' % other)
    if ENGINE:
        check('T1  only the three requested reports are flagged', t1)
    else:
        skip('T1  only the three requested reports are flagged', REASON)

    # -----------------------------------------------------------------
    def t2():
        """``branch_restricted`` says who is limited, and it never disagrees
        with ``branch_visible_ids`` (they share one compute method)."""
        all_branches = env['branch.branch'].with_context(active_test=False).search([])
        eq(f['u1'].branch_restricted, True, 'a Branch User is restricted')
        eq(set(f['u1'].branch_visible_ids.ids), {f['b1'].id},
           'a Branch User sees only its own branches')
        eq(f['u2'].branch_restricted, True, 'the second Branch User too')
        eq(set(f['u2'].branch_visible_ids.ids), {f['b2'].id}, 'its own branch')
        eq(env.user.branch_restricted, False, 'the admin is not restricted')
        eq(set(env.user.branch_visible_ids.ids), set(all_branches.ids),
           'an unrestricted user keeps every branch')
        eq(f['manager'].branch_restricted, False,
           'a Branch Manager is never restricted')
        eq(set(f['manager'].branch_visible_ids.ids), set(all_branches.ids),
           'even when branches are assigned to it')
    check('T2  who is branch restricted', t2)

    # -----------------------------------------------------------------
    def t3():
        """A restricted user gets the condition on the three reports, and it
        is the very same condition as the global access rule."""
        truthy(ENGINE, REASON)
        for key in ('pl', 'aged_receivable', 'aged_payable'):
            eq(branch_domain(f[key], f['u1']), expected_branch(f['b1']),
               '%s condition for the first user' % f[key].name)
        eq(branch_domain(f['pl'], f['u2']), expected_branch(f['b2']),
           'the second user gets its own branch')
    if ENGINE:
        check('T3  the condition is injected for a restricted user', t3)
    else:
        skip('T3  the condition is injected for a restricted user', REASON)

    # -----------------------------------------------------------------
    def t4():
        """Scope: nothing is added for an unrestricted user, and nothing for
        another report even when the user *is* restricted."""
        truthy(ENGINE, REASON)
        for key in ('pl', 'aged_receivable', 'aged_payable'):
            eq(branch_domain(f[key], env.user), set(),
               'an unrestricted user keeps the core domain untouched')
            eq(branch_domain(f[key], f['manager']), set(),
               'a manager keeps the core domain untouched')
        eq(branch_domain(f['general_ledger'], f['u1']), set(),
           'the General Ledger of a restricted user is not filtered')
        eq(branch_domain(f['general_ledger'], env.user), set(),
           'the General Ledger of the admin is not filtered')
    if ENGINE:
        check('T4  the other reports and the other users are untouched', t4)
    else:
        skip('T4  the other reports and the other users are untouched', REASON)

    # -----------------------------------------------------------------
    def t5():
        """The condition reported by the module and the one written in
        ``security/ir.access.csv`` must select the very same journal items:
        the report and the list it opens may not disagree."""
        path = os.path.join(get_module_path('branch_management'),
                            'security', 'ir.access.csv')
        with open(path, newline='', encoding='utf-8') as handle:
            rows = list(csv.DictReader(handle))
        row = next(r for r in rows
                   if r['id'] == 'access_account_move_line_branch_restriction')
        aml = env['account.move.line']
        # the condition has to be built in the environment of the reader:
        # it depends on the branches of the user that runs the report.
        for user in (f['u1'], f['u2'], env.user):
            from_csv = safe_eval(
                row['domain'], {'user': user.with_context(active_test=False)})
            from_method = env['account.report'].with_user(
                user)._branch_visibility_domain()
            eq(set(aml.sudo().search(from_csv).ids),
               set(aml.sudo().search(from_method).ids),
               'the CSV rule and the report rule select the same items')
        # and the condition itself is the one that hides the other branch
        visible = aml.sudo().search(
            env['account.report'].with_user(f['u1'])
            ._branch_visibility_domain())
        truthy(not any(l.branch_id == f['b2'] for l in visible),
               'the rule of user 1 must drop the items of branch 2')
        truthy(any(l.branch_id == f['b1'] for l in visible),
               'and keep the items of branch 1')
        truthy(any(not l.branch_id for l in visible),
               'items without a branch stay visible (rule of phase 11)')
    check('T5  the report rule and the ir.access rule agree', t5)

    # -----------------------------------------------------------------
    def t6():
        """Partner Ledger: ``debit`` is what the invoices are worth, ``credit``
        what the vendor bills are worth, for every kind of user."""
        truthy(ENGINE, REASON)
        grew('pl', 'admin', 'debit', 3400.0, 'admin debit = 1000+2000+400')
        grew('pl', 'admin', 'credit', 1600.0, 'admin credit = 700+800+100')
        grew('pl', 'u1', 'debit', 1400.0, 'user 1 debit = 1000+400')
        grew('pl', 'u1', 'credit', 800.0, 'user 1 credit = 700+100')
        grew('pl', 'u2', 'debit', 2400.0, 'user 2 debit = 2000+400')
        grew('pl', 'u2', 'credit', 900.0, 'user 2 credit = 800+100')
        grew('pl', 'manager', 'debit', 3400.0, 'manager debit = everything')
        grew('pl', 'manager', 'credit', 1600.0, 'manager credit = everything')
    if ENGINE:
        check('T6  Partner Ledger totals per user', t6)
    else:
        skip('T6  Partner Ledger totals per user', REASON)

    # -----------------------------------------------------------------
    def t7():
        """Aged Receivable: only the customer invoices, split by branch."""
        truthy(ENGINE, REASON)
        grew('aged_receivable', 'admin', 'total', 3400.0, 'admin')
        grew('aged_receivable', 'u1', 'total', 1400.0, 'user 1 = 1000+400')
        grew('aged_receivable', 'u2', 'total', 2400.0, 'user 2 = 2000+400')
        grew('aged_receivable', 'manager', 'total', 3400.0, 'manager')
    if ENGINE:
        check('T7  Aged Receivable totals per user', t7)
    else:
        skip('T7  Aged Receivable totals per user', REASON)

    # -----------------------------------------------------------------
    def t8():
        """Aged Payable: only the vendor bills, split by branch."""
        truthy(ENGINE, REASON)
        grew('aged_payable', 'admin', 'total', 1600.0, 'admin = 700+800+100')
        grew('aged_payable', 'u1', 'total', 800.0, 'user 1 = 700+100')
        grew('aged_payable', 'u2', 'total', 900.0, 'user 2 = 800+100')
        grew('aged_payable', 'manager', 'total', 1600.0, 'manager')
    if ENGINE:
        check('T8  Aged Payable totals per user', t8)
    else:
        skip('T8  Aged Payable totals per user', REASON)

    # -----------------------------------------------------------------
    def t9():
        """Line by line: the partner of the other branch never appears, the
        partner without a branch always does."""
        truthy(ENGINE, REASON)
        names = report_names(f['pl'], f['u1'])
        for wanted in ('T15 Cust Alpha', 'T15 Cust None',
                       'T15 Vend Alpha', 'T15 Vend None'):
            truthy(wanted in names, '%r missing for user 1: %r' % (wanted, names))
        for unwanted in ('T15 Cust Beta', 'T15 Vend Beta'):
            truthy(unwanted not in names,
                   '%r leaked to user 1: %r' % (unwanted, names))
        admin_names = report_names(f['pl'], env.user)
        for wanted in ('T15 Cust Alpha', 'T15 Cust Beta', 'T15 Cust None'):
            truthy(wanted in admin_names,
                   '%r missing for the admin: %r' % (wanted, admin_names))
        # the manager, who is not restricted, sees the whole ledger
        eq(set(report_names(f['pl'], f['manager'])), set(admin_names),
           'the manager sees exactly what the admin sees')
    if ENGINE:
        check('T9  the partners of the other branch never appear', t9)
    else:
        skip('T9  the partners of the other branch never appear', REASON)

    # -----------------------------------------------------------------
    def t10():
        """The drill-down needs no override of its own: the action it opens
        is a plain list of journal items, and a plain search already runs
        through the global ``ir.access`` rule of this module."""
        truthy(ENGINE, REASON)
        report = f['pl'].with_user(f['u1'])
        options = report.get_options({})
        info = report.get_report_information(options)
        line_id = next(ln.id for ln in info['lines']
                       if '~res.partner~' in str(ln.id).split('|')[-1])
        action = report.open_journal_items(options, {
            'line_id': line_id,
            'view_ref': 'account.view_move_line_tree_grouped_partner',
        })
        eq(action['type'], 'ir.actions.act_window', 'the drill-down opens a list')
        eq(action['res_model'], 'account.move.line', 'of the journal items')

        opened = env['account.move.line'].with_user(f['u1']).search(action['domain'])
        truthy(not any(l.branch_id == f['b2'] for l in opened),
               'the list opened by the drill-down leaked branch 2')
        fixture_ids = set(f['lines'].ids)
        expected = {l.id for l in f['lines'] if l.branch_id != f['b2']}
        eq(set(opened.ids) & fixture_ids, expected,
           'the list shows the items of branch 1 and the ones without a branch')

        plain = env['account.move.line'].with_user(f['u1']).search([])
        truthy(not any(l.branch_id == f['b2'] for l in plain),
               'the journal items list is restricted on its own')
        truthy(any(l.branch_id == f['b1'] for l in plain),
               'and still shows the items of branch 1')
    if ENGINE:
        check('T10 the drill-down stays inside the branch', t10)
    else:
        skip('T10 the drill-down stays inside the branch', REASON)

    # -----------------------------------------------------------------
    def t11():
        """A report must not change the shape of what it is given: the
        condition is ANDed to the core domain, never written over it, and
        the options dict is left alone."""
        truthy(ENGINE, REASON)
        r = f['pl'].with_user(f['u1'])
        options = r.get_options({})
        before = {k: repr(v) for k, v in options.items()}
        domain = r._get_options_domain(options, 'strict_range')
        after = {k: repr(v) for k, v in options.items()}
        eq(before, after, 'the options dict was modified')
        core_names = [item[0] for item in list(domain) if isinstance(item, tuple)]
        for expected_field in ('display_type', 'company_id', 'parent_state'):
            truthy(expected_field in core_names,
                   'the core condition %r was lost' % expected_field)
        eq(len(branch_leaves(domain)), 2,
           'exactly two branch leaves (an OR), got %r' % branch_leaves(domain))
        eq(set(repr(i) for i in branch_leaves(domain)),
           expected_branch(f['b1']), 'and they are the ones of branch 1')
    if ENGINE:
        check('T11 the core domain is kept, only ANDed', t11)
    else:
        skip('T11 the core domain is kept, only ANDed', REASON)

    # -----------------------------------------------------------------
    def t12():
        """Phase 15 must not make ``branch_management`` depend on the
        accounting reports: the model ``account.report`` comes from
        ``account``, so the extension loads on a database without them."""
        path = os.path.join(get_module_path('branch_management'),
                            '__manifest__.py')
        with open(path, encoding='utf-8') as handle:
            manifest = ast.literal_eval(handle.read())
        depends = list(manifest['depends'])
        for required in ('account', 'sale_stock', 'stock', 'analytic'):
            truthy(required in depends, '%r must stay a dependency' % required)
        for forbidden in ('account_reports', 'account_accountant'):
            truthy(forbidden not in depends,
                   '%r must NOT become a dependency' % forbidden)
        truthy('account.report' in env,
               'the model account.report must be registered by account')
        cls = type(env['account.report'])
        truthy(hasattr(cls, '_is_branch_restricted_report'),
               'the report override of phase 15 is not registered')
        truthy(hasattr(cls, '_branch_visibility_domain'),
               'the branch condition of phase 15 is not registered')
    check('T12 no new dependency was added', t12)

except Exception:  # noqa: BLE001 - never leave the shell in a broken state
    import traceback
    LINES.append("FATAL " + traceback.format_exc())
    FAIL += 1
finally:
    print("\n".join([""] + LINES))
    print("\n==== PHASE 15: %d PASS / %d FAIL / %d SKIP ===="
          % (PASS, FAIL, SKIP))
    env.cr.rollback()
