# -*- coding: utf-8 -*-
"""Phase 7 runtime tests: sale.report integration and smart buttons.

Run with:  odoo shell -d balance_mod ... < test_phase7.py
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


def has_leaf(domain, leaf):
    """True when ``leaf`` appears somewhere inside ``domain`` (any nesting)."""
    if isinstance(domain, (list, tuple)):
        if tuple(domain) == tuple(leaf):
            return True
        return any(has_leaf(item, leaf) for item in domain)
    return False


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
    Order = env["sale.order"]
    Users = env["res.users"]
    Move = env["account.move"]
    Picking = env["stock.picking"]
    SaleReport = env["sale.report"]

    main_company = env.ref("base.main_company")
    g_user = env.ref("base.group_user")
    g_bu = env.ref("branch_management.group_branch_user")
    g_salesman = env.ref("sales_team.group_sale_salesman")
    g_invoice = env.ref("account.group_account_invoice")

    journal = env["account.journal"].search([("type", "=", "sale")], limit=1)
    misc_journal = env["account.journal"].search(
        [("type", "=", "general")], limit=1)
    income = env["account.account"].search(
        [("account_type", "in", ("income", "income_other"))], limit=1)
    expense = env["account.account"].search(
        [("account_type", "=", "expense")], limit=1)
    receivable = env["account.account"].search(
        [("account_type", "=", "asset_receivable")], limit=1)
    truthy(journal, "no sales journal")
    truthy(misc_journal, "no miscellaneous journal")
    truthy(income, "no income account")
    truthy(expense, "no expense account")
    truthy(receivable, "no receivable account")

    wh0 = env.ref("stock.warehouse0")
    picking_type = env["stock.picking.type"].search(
        [("company_id", "=", main_company.id)], limit=1)
    truthy(picking_type, "an operation type must exist")
    src = picking_type.default_location_src_id or wh0.view_location_id
    dst = picking_type.default_location_dest_id or wh0.view_location_id

    partner = env["res.partner"].create({"name": "Phase7 Customer"})
    partner.write({"property_account_receivable_id": receivable.id})
    product = env["product.product"].create({
        "name": "Phase7 Product", "list_price": 100.0,
        "invoice_policy": "order",
        "property_account_income_id": income.id})

    b1 = Branch.create({"name": "Phase7 Branch A", "code": "P7A",
                        "company_id": main_company.id})
    b2 = Branch.create({"name": "Phase7 Branch B", "code": "P7B",
                        "company_id": main_company.id})

    restricted = Users.create({
        "name": "Phase7 Restricted", "login": "p7_restricted",
        "group_ids": [(6, 0, [g_user.id, g_bu.id, g_salesman.id,
                              g_invoice.id])],
        "branch_ids": [(6, 0, [b1.id])],
        "default_branch_id": b1.id,
    })

    def order_line(qty=1):
        return [(0, 0, {"product_id": product.id,
                        "product_uom_qty": qty, "price_unit": 100.0})]

    def make_order(branch):
        return Order.create({"partner_id": partner.id, "user_id": False,
                             "branch_id": branch.id if branch else False,
                             "order_line": order_line(1)})

    def make_invoice(branch):
        line = {"display_type": "product", "name": "Phase7 line",
                "quantity": 1, "price_unit": 100.0,
                "account_id": income.id, "product_id": product.id}
        return Move.create({"move_type": "out_invoice",
                            "partner_id": partner.id, "journal_id": journal.id,
                            "branch_id": branch.id if branch else False,
                            "line_ids": [(0, 0, line)]})

    def make_picking(branch):
        return Picking.create({"picking_type_id": picking_type.id,
                               "location_id": src.id,
                               "location_dest_id": dst.id,
                               "branch_id": branch.id if branch else False})

    # one order of b1, two of b2, one without branch
    o1, o2, o2b, o3 = (make_order(b1), make_order(b2), make_order(b2),
                       make_order(None))
    # invoices: one of b1, two of b2, one without branch
    m1, m2, m3, m4 = (make_invoice(b1), make_invoice(b2), make_invoice(b2),
                      make_invoice(None))
    # a journal entry carrying the branch of b1: not an invoice
    entry = Move.create({
        "move_type": "entry", "journal_id": misc_journal.id,
        "branch_id": b1.id,
        "line_ids": [
            (0, 0, {"name": "Phase7 debit", "account_id": expense.id,
                    "debit": 10.0, "credit": 0.0}),
            (0, 0, {"name": "Phase7 credit", "account_id": income.id,
                    "debit": 0.0, "credit": 10.0}),
        ],
    })
    eq(entry.branch_id, b1, "the journal entry must carry the branch")
    # transfers: two of b1, one of b2, one without branch
    p1, p1b, p2, p3 = (make_picking(b1), make_picking(b1), make_picking(b2),
                       make_picking(None))

    # ------------------------------------------------------------------
    # T1 - the column of the report
    # ------------------------------------------------------------------
    def t1():
        field = SaleReport._fields.get("branch_id")
        truthy(field, "sale.report.branch_id missing")
        eq(field.comodel_name, "branch.branch")
        truthy(field.store, "the column must be stored to be selected")
        truthy(not field.compute, "it is a plain column, not a computed field")
        # no physical table: the report is a query model in Odoo 20
        env.cr.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'sale_report'")
        truthy(not env.cr.fetchone(),
               "sale.report must not have a database view to recreate")
    check("T1 branch column of sale.report", t1)

    # ------------------------------------------------------------------
    # T2 - the branch is really reported
    # ------------------------------------------------------------------
    def t2():
        rows = SaleReport.search([])
        truthy(rows, "the report returns no row at all")
        eq({row.branch_id.id for row in rows if row.branch_id},
           {b1.id, b2.id}, "the two branches must be reported")
        truthy({row.id for row in rows if row.branch_id == b1},
               "no row of branch b1")
        truthy({row.id for row in rows if not row.branch_id},
               "an order without branch is reported without branch")
        # every row points at the branch of the order it comes from
        for row in rows:
            eq(row.branch_id, row.order_reference.branch_id,
               "the row must carry the branch of its order")
        eq(set(SaleReport.search([("branch_id", "=", b1.id)]).ids),
           {row.id for row in rows if row.branch_id == b1},
           "search on branch_id")
    check("T2 sale.report returns the branch of the order", t2)

    # ------------------------------------------------------------------
    # T3 - the restriction row of the csv
    # ------------------------------------------------------------------
    def t3():
        row = env["ir.access"].search([
            ("model_id.model", "=", "sale.report"),
            ("group_id", "=", False),
            ("name", "like", "branch")], limit=1)
        truthy(row, "sale.report restriction row missing")
        truthy(row.operation == "crud", "operation must be crud, got %r"
               % row.operation)
        truthy(row.for_read and row.for_write and row.for_create
               and row.for_unlink, "the four operations must be on")
        truthy("branch_id" in (row.domain or ""),
               "the domain must filter on branch_id")
        truthy(row.model_id.model == "sale.report", "wrong model")
    check("T3 the restriction row of sale.report exists", t3)

    # ------------------------------------------------------------------
    # T4 - visibility of the report
    # ------------------------------------------------------------------
    def t4():
        rows = SaleReport.search([])
        # the standard personal rule of the salesman is applied as well
        expected = {row.id for row in rows
                    if (not row.branch_id or row.branch_id == b1)
                    and (not row.user_id or row.user_id == restricted)}
        truthy(expected, "the restricted user would see nothing")
        eq(set(SaleReport.with_user(restricted).search([]).ids), expected,
           "rows visible to the restricted user")
        truthy(not SaleReport.with_user(restricted).search(
            [("branch_id", "=", b2.id)]), "rows of b2 must stay hidden")
        # he keeps reading the rows of his branch
        own = SaleReport.with_user(restricted).search(
            [("branch_id", "=", b1.id)], limit=1)
        truthy(own, "he must read the rows of his own branch")
        truthy(own.read(["branch_id"]), "he reads the column")
        # ... and is refused the rows of the other branch
        other = SaleReport.search([("branch_id", "=", b2.id)], limit=1)
        truthy(other, "no row of b2 in the fixtures")
        with expect(AccessError):
            SaleReport.with_user(restricted).browse(
                other.id).read(["branch_id"])
    check("T4 visibility of the sales analysis", t4)

    # ------------------------------------------------------------------
    # T5 - views: column, search facet, group by
    # ------------------------------------------------------------------
    def t5():
        combined = env.ref("sale.sale_report_view_tree").get_combined_arch()
        truthy('name="branch_id"' in combined, "column missing in the list")
        combined = env.ref("sale.view_order_product_search").get_combined_arch()
        truthy('name="branch_id"' in combined, "search facet missing")
        truthy("group_by': 'branch_id'" in combined, "group by filter missing")
        truthy(env.ref("branch_management.sale_report_view_tree_branch"),
               "our list view is missing")
        truthy(env.ref("branch_management.view_order_product_search_branch"),
               "our search view is missing")

        # grouping by branch really works
        data = SaleReport._read_group([], ["branch_id"], ["__count"])

        def gid(key):
            if not key:
                return False
            return key.id if hasattr(key, "id") else key

        groups = {gid(key): count for key, count in data}
        eq(groups.get(b1.id),
           SaleReport.search_count([("branch_id", "=", b1.id)]),
           "count grouped by branch")
        truthy(b1.id in groups, "no group for branch b1")
        truthy(b2.id in groups, "no group for branch b2")
    check("T5 list, search facet, group by and grouping", t5)

    # ------------------------------------------------------------------
    # T6 - the counters of the form
    # ------------------------------------------------------------------
    def t6():
        eq(b1.sale_count, Order.search_count([("branch_id", "=", b1.id)]),
           "orders of b1")
        eq(b2.sale_count, Order.search_count([("branch_id", "=", b2.id)]),
           "orders of b2")
        truthy(b2.sale_count > b1.sale_count,
               "the counters must be scoped to the branch")
        eq(b1.picking_count,
           Picking.search_count([("branch_id", "=", b1.id)]),
           "transfers of b1")
        truthy(b1.picking_count == 2, "two transfers of b1")
        eq(b1.invoice_count,
           Move.search_count([("branch_id", "=", b1.id),
                              ("move_type", "!=", "entry")]),
           "invoices of b1")
        truthy(b1.invoice_count == 1, "one invoice of b1, not the entry")
        eq(Move.search_count([("branch_id", "=", b1.id)]), 2,
           "b1 owns one invoice and one journal entry")
        eq(b2.invoice_count, 2, "two invoices of b2")
        truthy(not b3_count(), "no branch: nothing to count")

    def b3_count():
        """A branch without document returns 0 for the three counters."""
        b3 = Branch.create({"name": "Phase7 Empty", "code": "P7E",
                            "company_id": main_company.id})
        return (b3.sale_count, b3.picking_count, b3.invoice_count) != (0, 0, 0)

    check("T6 the three counters of the branch", t6)

    # ------------------------------------------------------------------
    # T7 - the three document actions
    # ------------------------------------------------------------------
    def t7():
        act = b1.action_view_sale_orders()
        eq(act["type"], "ir.actions.act_window")
        eq(act["res_model"], "sale.order")
        eq(act["view_mode"], "list,form")
        eq(act["domain"], [("branch_id", "=", b1.id)])
        eq(act["context"].get("default_branch_id"), b1.id)
        seen = set(Order.search(act["domain"]).ids)
        truthy(seen, "no order in the list of b1")
        truthy(o1.id in seen, "the order of b1 is missing")
        truthy(not (seen & {o2.id, o2b.id}), "orders of b2 must not be there")
        truthy(o3.id not in seen, "the order without branch must not be there")

        act = b1.action_view_pickings()
        eq(act["res_model"], "stock.picking")
        eq(act["domain"], [("branch_id", "=", b1.id)])
        seen = set(Picking.search(act["domain"]).ids)
        truthy({p1.id, p1b.id} <= seen, "the transfers of b1 are missing")
        truthy(p2.id not in seen, "the transfer of b2 must not be there")
        truthy(p3.id not in seen,
               "the transfer without branch must not be there")

        act = b1.action_view_invoices()
        eq(act["res_model"], "account.move")
        eq(act["domain"], [("branch_id", "=", b1.id),
                           ("move_type", "!=", "entry")])
        seen = set(Move.search(act["domain"]).ids)
        truthy(m1.id in seen, "the invoice of b1 is missing")
        truthy(entry.id not in seen, "a journal entry is not an invoice")
        truthy(m2.id not in seen, "the invoice of b2 must not be there")
        truthy(m4.id not in seen,
               "the invoice without branch must not be there")
    check("T7 the three document actions", t7)

    # ------------------------------------------------------------------
    # T8 - the analysis action
    # ------------------------------------------------------------------
    def t8():
        act = b1.action_view_sale_analysis()
        eq(act["type"], "ir.actions.act_window")
        eq(act["res_model"], "sale.report")
        truthy(has_leaf(act["domain"], ("branch_id", "=", b1.id)),
               "the branch must be added to the domain: %r" % act["domain"])
        truthy(has_leaf(act["domain"], ("state", "!=", "cancel")),
               "the domain of the standard action must be kept: %r"
               % act["domain"])
        # what the action really shows
        seen = set(SaleReport.search(act["domain"]).ids)
        expected = {row.id for row in SaleReport.search([])
                    if row.branch_id == b1 and row.state != "cancel"}
        truthy(expected, "the report of b1 would be empty")
        eq(seen, expected, "rows opened by the button")
        truthy(not (seen & {row.id for row in SaleReport.search(
            [("branch_id", "=", b2.id)])}), "rows of b2 must not be there")
    check("T8 the analysis action keeps the standard domain", t8)

    # ------------------------------------------------------------------
    # T9 - a user without any right on the three models
    # ------------------------------------------------------------------
    def t9():
        plain = Users.create({
            "name": "Phase7 Plain", "login": "p7_plain",
            "group_ids": [(6, 0, [g_user.id])],
        })
        # no sales / stock / accounting group: the counters are 0 instead of
        # an AccessError, so that the form of the branch stays readable
        eq(b1.with_user(plain).sale_count, 0, "no sale.order right")
        eq(b1.with_user(plain).picking_count, 0, "no stock.picking right")
        eq(b1.with_user(plain).invoice_count, 0, "no account.move right")
        read = b1.with_user(plain).read(
            ["sale_count", "picking_count", "invoice_count"])
        truthy(read, "the form of the branch must stay readable")
        eq(read[0]["sale_count"], 0, "counters read as 0")
    check("T9 a user without rights gets 0, not an AccessError", t9)

    # ------------------------------------------------------------------
    # T10 - the buttons of the form
    # ------------------------------------------------------------------
    def t10():
        combined = env.ref("branch_management.branch_view_form").get_combined_arch()
        truthy('name="button_box"' in combined, "no button box")
        truthy('invisible="sale_count == 0"' in combined,
               "the counter of the orders must be hidden at 0")
        truthy('invisible="picking_count == 0"' in combined,
               "the counter of the transfers must be hidden at 0")
        truthy('invisible="invoice_count == 0"' in combined,
               "the counter of the invoices must be hidden at 0")
        truthy('groups="sales_team.group_sale_salesman"' in combined,
               "the analysis button needs the salesman group")
        for method in ("action_view_sale_orders", "action_view_pickings",
                       "action_view_invoices", "action_view_sale_analysis"):
            truthy(method in combined, "%s is not called by the form" % method)
        # the four methods exist and are not deprecated names
        for method in ("action_view_sale_orders", "action_view_pickings",
                       "action_view_invoices", "action_view_sale_analysis"):
            truthy(callable(getattr(Branch, method)), "%s missing" % method)
    check("T10 the four buttons of the form", t10)

except Exception:  # noqa: BLE001 - never leave the shell in a broken state
    import traceback
    LINES.append("FATAL " + traceback.format_exc())
    FAIL += 1
finally:
    print("\n".join([""] + LINES))
    print("\n==== PHASE 7: %d PASS / %d FAIL ====" % (PASS, FAIL))
    env.cr.rollback()
