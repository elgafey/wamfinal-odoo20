# -*- coding: utf-8 -*-
"""Phase 12 runtime tests: the branch on account.invoice.report
(Invoices Analysis).

Run with:  odoo shell -d balance_mod ... < test_phase12.py
The whole script runs in one transaction and rolls it back at the end.
"""
from contextlib import contextmanager

from odoo.exceptions import AccessError

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


def gid(key):
    """Turn a group by key into a branch id (or False)."""
    if not key:
        return False
    return key.id if hasattr(key, "id") else key


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


try:
    Branch = env["branch.branch"]
    Users = env["res.users"]
    Move = env["account.move"]
    InvoiceReport = env["account.invoice.report"]
    IRA = env["ir.access"]

    main_company = env.ref("base.main_company")
    g_user = env.ref("base.group_user")
    g_bu = env.ref("branch_management.group_branch_user")
    g_salesman = env.ref("sales_team.group_sale_salesman")
    g_invoice = env.ref("account.group_account_invoice")

    journal = env["account.journal"].search([("type", "=", "sale")], limit=1)
    income = env["account.account"].search(
        [("account_type", "in", ("income", "income_other"))], limit=1)
    receivable = env["account.account"].search(
        [("account_type", "=", "asset_receivable")], limit=1)
    truthy(journal, "no sales journal")
    truthy(income, "no income account")
    truthy(receivable, "no receivable account")

    partner = env["res.partner"].create({"name": "Phase12 Customer"})
    partner.write({"property_account_receivable_id": receivable.id})
    product = env["product.product"].create({
        "name": "Phase12 Product", "list_price": 100.0,
        "invoice_policy": "order",
        "property_account_income_id": income.id})

    b1 = Branch.create({"name": "Phase12 Branch A", "code": "P12A",
                        "company_id": main_company.id})
    b2 = Branch.create({"name": "Phase12 Branch B", "code": "P12B",
                        "company_id": main_company.id})

    restricted = Users.create({
        "name": "Phase12 Restricted", "login": "p12_restricted",
        "group_ids": [(6, 0, [g_user.id, g_bu.id, g_salesman.id,
                              g_invoice.id])],
        "branch_ids": [(6, 0, [b1.id])],
        "default_branch_id": b1.id,
    })

    def make_invoice(branch):
        line = {"display_type": "product", "name": "Phase12 line",
                "quantity": 1, "price_unit": 100.0,
                "account_id": income.id, "product_id": product.id}
        return Move.create({"move_type": "out_invoice",
                            "partner_id": partner.id, "journal_id": journal.id,
                            "branch_id": branch.id if branch else False,
                            "line_ids": [(0, 0, line)]})

    m1, m2, m3, m4 = (make_invoice(b1), make_invoice(b2),
                      make_invoice(b2), make_invoice(None))
    OURS = [m1.id, m2.id, m3.id, m4.id]

    def rows_of(move, user=None):
        """The report rows of one invoice, for one user (None = superuser)."""
        recs = InvoiceReport if user is None else InvoiceReport.with_user(user)
        return recs.search([("move_id", "=", move.id)])

    # ------------------------------------------------------------------
    # T1 - the column of the report
    # ------------------------------------------------------------------
    def t1():
        field = InvoiceReport._fields.get("branch_id")
        truthy(field, "account.invoice.report.branch_id missing")
        eq(field.comodel_name, "branch.branch")
        truthy(field.store, "the column must be stored to be selected")
        truthy(not field.compute, "it is a plain column, not a computed field")
        truthy(field.readonly, "a report column is readonly")
        # no physical table: the report is a query model in Odoo 20, so there
        # is no view to drop and recreate and no init() to run
        env.cr.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'account_invoice_report'")
        truthy(not env.cr.fetchone(),
               "account.invoice.report must not have a database view to recreate")
    check("T1 branch column of account.invoice.report", t1)

    # ------------------------------------------------------------------
    # T2 - the branch is really reported
    # ------------------------------------------------------------------
    def t2():
        for move, branch in ((m1, b1), (m2, b2), (m3, b2), (m4, None)):
            row = rows_of(move)
            truthy(row, "no report row for the invoice %s" % move.id)
            eq(len(row), 1, "one product line = one row of the report")
            eq(row.branch_id.id, branch.id if branch else False,
               "branch of the row")
            eq(row.branch_id.id, row.move_id.branch_id.id,
               "the row must carry the branch of its invoice")
        # the branch is a real column of the query: searching on it works
        eq(set(InvoiceReport.search(
            [("move_id", "in", OURS), ("branch_id", "=", b1.id)]).ids),
           set(rows_of(m1).ids), "search on branch_id")
        eq(set(InvoiceReport.search(
            [("move_id", "in", OURS), ("branch_id", "=", b2.id)]).ids),
           set(rows_of(m2).ids) | set(rows_of(m3).ids),
           "the two invoices of b2 are selected together")
        truthy(not rows_of(m4).branch_id,
               "the invoice without branch is reported without branch")
    check("T2 account.invoice.report returns the branch of the invoice", t2)

    # ------------------------------------------------------------------
    # T3 - the restriction row of the csv
    # ------------------------------------------------------------------
    def t3():
        row = IRA.search([
            ("model_id.model", "=", "account.invoice.report"),
            ("group_id", "=", False),
            ("name", "like", "branch")], limit=1)
        truthy(row, "account.invoice.report restriction row missing")
        eq(row.operation, "crud")
        truthy(row.for_read and row.for_write and row.for_create
               and row.for_unlink, "the four operations must be on")
        truthy(row.model_id.model == "account.invoice.report", "wrong model")
        truthy("branch_id" in (row.domain or ""),
               "the domain must filter on branch_id")
        truthy("branch_visible_ids" in (row.domain or ""),
               "the domain must use the visible branches of the user")
        # a many2one leaf: safe, never rewritten like a x2many one
        truthy("('branch_ids', '=', False)" not in (row.domain or ""))
    check("T3 the restriction row of the report exists", t3)

    # ------------------------------------------------------------------
    # T4 - visibility of the report
    # ------------------------------------------------------------------
    def t4():
        # as superuser: the four rows are there
        for move in (m1, m2, m3, m4):
            truthy(rows_of(move), "the row of invoice %s is missing" % move.id)
        # the restricted user keeps the rows of his branch...
        eq(InvoiceReport.with_user(restricted).search_count(
            [("move_id", "=", m1.id)]), 1, "his own branch")
        eq(InvoiceReport.with_user(restricted).search_count(
            [("move_id", "=", m4.id)]), 1,
           "a row without branch stays visible")
        # ... and loses the rows of the other branch
        eq(InvoiceReport.with_user(restricted).search_count(
            [("move_id", "=", m2.id)]), 0, "the other branch")
        eq(InvoiceReport.with_user(restricted).search_count(
            [("move_id", "=", m3.id)]), 0, "the other branch")
        eq(InvoiceReport.with_user(restricted).search_count(
            [("branch_id", "=", b2.id)]), 0, "no row of b2 at all")
        truthy(InvoiceReport.with_user(restricted).search_count(
            [("branch_id", "=", b1.id)]), "he keeps the rows of b1")
        # reading a row of the other branch is refused
        other = rows_of(m2)
        truthy(other, "the row of m2 exists for the superuser")
        with expect(AccessError):
            InvoiceReport.with_user(restricted).browse(
                other.id).read(["branch_id"])
    check("T4 visibility of the invoices analysis", t4)

    # ------------------------------------------------------------------
    # T5 - views: column, search facet, group by, and grouping
    # ------------------------------------------------------------------
    def t5():
        combined = env.ref(
            "account.account_invoice_report_view_tree").get_combined_arch()
        truthy('name="branch_id"' in combined, "column missing in the list")
        combined = env.ref(
            "account.view_account_invoice_report_search").get_combined_arch()
        truthy('name="branch_id"' in combined, "search facet missing")
        truthy("group_by': 'branch_id'" in combined, "group by filter missing")
        truthy(env.ref(
            "branch_management.account_invoice_report_view_tree_branch"),
            "our list view is missing")
        truthy(env.ref(
            "branch_management.view_account_invoice_report_search_branch"),
            "our search view is missing")

        # grouping by branch really works
        data = InvoiceReport._read_group([], ["branch_id"], ["__count"])
        groups = {gid(key): count for key, count in data}
        truthy(b1.id in groups, "no group for branch b1")
        truthy(b2.id in groups, "no group for branch b2")
        eq(groups.get(b1.id),
           InvoiceReport.search_count([("branch_id", "=", b1.id)]),
           "count grouped by branch")
        eq(groups.get(b2.id),
           InvoiceReport.search_count([("branch_id", "=", b2.id)]),
           "count grouped by the other branch")
    check("T5 list, search facet, group by and grouping", t5)

    # ------------------------------------------------------------------
    # T6 - the grouping respects the restriction
    # ------------------------------------------------------------------
    def t6():
        data = InvoiceReport.with_user(restricted)._read_group(
            [], ["branch_id"], ["__count"])
        groups = {gid(key): count for key, count in data}
        truthy(b2.id not in groups,
               "the group of the other branch must not appear")
        truthy(b1.id in groups, "the group of his own branch must appear")
        eq(groups.get(b1.id),
           InvoiceReport.with_user(restricted).search_count(
               [("branch_id", "=", b1.id)]),
           "count grouped by branch, as he sees it")
        # the groups add up to the number of rows he is allowed to read
        eq(sum(groups.values()),
           InvoiceReport.with_user(restricted).search_count([]),
           "the groups must add up to the visible rows")
    check("T6 the group by respects the branch restriction", t6)

    # ------------------------------------------------------------------
    # T7 - the measures still add up
    # ------------------------------------------------------------------
    def t7():
        data = InvoiceReport._read_group(
            [("move_id", "in", OURS)], ["branch_id"], ["quantity:sum"])
        got = {gid(key): value for key, value in data}
        eq(got.get(b1.id), 1.0, "quantity of branch b1")
        eq(got.get(b2.id), 2.0, "quantity of branch b2")
        eq(got.get(False), 1.0, "quantity of the invoice without branch")
        eq(sum(got.values()), 4.0, "the four quantities must add up")
    check("T7 the measures are aggregated per branch", t7)

    # ------------------------------------------------------------------
    # T8 - who is restricted, who is not
    # ------------------------------------------------------------------
    def t8():
        plain = Users.create({
            "name": "Phase12 Plain", "login": "p12_plain",
            "group_ids": [(6, 0, [g_user.id])],
        })
        truthy(not InvoiceReport.with_user(plain).has_access("read"),
               "without an accounting group he has no right on the report")
        # an accountant WITHOUT the branch groups: branch_visible_ids is then
        # every branch, so his view of the report does not change at all
        accountant = Users.create({
            "name": "Phase12 Accountant", "login": "p12_accountant",
            "group_ids": [(6, 0, [g_user.id, g_salesman.id, g_invoice.id])],
        })
        eq(InvoiceReport.with_user(accountant).search_count(
            [("branch_id", "=", b2.id)]),
           InvoiceReport.search_count([("branch_id", "=", b2.id)]),
           "a user without the branch group still sees every branch")
        eq(InvoiceReport.with_user(accountant).search_count([]),
           InvoiceReport.search_count([]),
           "his rows are not filtered either")
    check("T8 only the branch users are restricted", t8)

    # ------------------------------------------------------------------
    # T9 - the core columns of the report still read
    # ------------------------------------------------------------------
    def t9():
        row = rows_of(m1)
        read = row.read(["move_id", "partner_id", "journal_id", "state",
                         "price_subtotal", "quantity", "branch_id"])
        truthy(read, "the row must be readable")
        vals = read[0]
        for name in ("move_id", "partner_id", "journal_id", "state",
                     "price_subtotal", "quantity", "branch_id"):
            truthy(name in vals, "%s missing from the row" % name)
        # read() formats a many2one as (id, display_name)
        pid = vals["branch_id"]
        eq(pid[0] if isinstance(pid, (tuple, list)) else pid, b1.id,
           "the branch of the row")
        eq(vals["move_id"][0], m1.id, "the invoice of the row")
        eq(vals["quantity"], 1.0, "the quantity of the line")
        truthy(vals["price_subtotal"] > 0, "the measure must be positive")
        eq(vals["state"], m1.state, "the state of the invoice")
    check("T9 the columns of the report still read", t9)

    # ------------------------------------------------------------------
    # T10 - the csv of the module as a whole
    # ------------------------------------------------------------------
    def t10():
        my_rows = IRA.search([
            ("id", "in", env["ir.model.data"].search([
                ("module", "=", "branch_management"),
                ("model", "=", "ir.access")]).mapped("res_id"))])
        eq(len(my_rows), 19, "rows of security/ir.access.csv")
        groupless = my_rows.filtered(lambda r: not r.group_id)
        eq(len(groupless), 16, "restriction rows (no group = AND-ed)")
        eq(len(my_rows) - len(groupless), 3, "granted rows (group = OR-ed)")
        for other in groupless:
            truthy("branch_visible_ids" in (other.domain or "")
                   or (other.domain or "").startswith("user._branch_"),
                   "every restriction uses branch_visible_ids or one of the "
                   "phase 18 helpers (row %s)" % other.id)
        models = sorted(groupless.mapped("model_id.model"))
        truthy("account.invoice.report" in models, "the report must be there")
        truthy("sale.report" in models, "the sales report must be there")
        truthy("res.partner" in models, "the contacts must be there")
    check("T10 the whole ir.access.csv of the module", t10)

except Exception:  # noqa: BLE001 - never leave the shell in a broken state
    import traceback
    LINES.append("FATAL " + traceback.format_exc())
    FAIL += 1
finally:
    print("\n".join([""] + LINES))
    print("\n==== PHASE 12: %d PASS / %d FAIL ====" % (PASS, FAIL))
    env.cr.rollback()
