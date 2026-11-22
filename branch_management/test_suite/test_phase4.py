# -*- coding: utf-8 -*-
"""Phase 4 runtime tests: Sales integration (branch on sale.order).

Run with:  odoo shell -d balance_mod ... < test_phase4.py
The whole script runs in one transaction and rolls it back at the end.
"""
from contextlib import contextmanager

from odoo.exceptions import AccessError, UserError, ValidationError

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


try:
    Branch = env["branch.branch"]
    Order = env["sale.order"]
    Users = env["res.users"]
    main_company = env.ref("base.main_company")
    g_user = env.ref("base.group_user")
    g_bu = env.ref("branch_management.group_branch_user")
    g_salesman = env.ref("sales_team.group_sale_salesman")

    # ------------------------------------------------------------------
    # fixtures
    # ------------------------------------------------------------------
    wh0 = env.ref("stock.warehouse0")
    wh_branch = env["stock.warehouse"].create(
        {"name": "Branch Warehouse", "code": "BRW"})
    partner = env["res.partner"].create({"name": "Phase4 Customer"})
    product = env["product.product"].create(
        {"name": "Phase4 Product", "list_price": 100.0})

    b1 = Branch.create({"name": "Sales Branch A", "code": "SBA",
                        "company_id": main_company.id,
                        "warehouse_id": wh_branch.id})
    b2 = Branch.create({"name": "Sales Branch B", "code": "SBB",
                        "company_id": main_company.id})

    restricted = Users.create({
        "name": "Restricted Salesman", "login": "p4_restricted",
        "group_ids": [(6, 0, [g_user.id, g_bu.id, g_salesman.id])],
        "branch_ids": [(6, 0, [b1.id])],
        "default_branch_id": b1.id,
    })

    def line(qty=1):
        return [(0, 0, {"product_id": product.id,
                        "product_uom_qty": qty,
                        "price_unit": 100.0})]

    # ------------------------------------------------------------------
    # T1 - the field and its options
    # ------------------------------------------------------------------
    def t1():
        field = Order._fields.get("branch_id")
        truthy(field, "sale.order.branch_id missing")
        eq(field.comodel_name, "branch.branch")
        truthy(field.index, "branch_id must be indexed")
        truthy(field.check_company, "branch_id must be company checked")
        truthy("branch_id" not in env["sale.order.line"]._fields,
               "sale.order.line must not get a branch_id")
        truthy(env["sale.order"]._fields["branch_id"].default,
               "branch_id must have a default")
    check("T1 sale.order.branch_id defined, line untouched", t1)

    # ------------------------------------------------------------------
    # T2 - default branch of the user
    # ------------------------------------------------------------------
    def t2():
        values = Order.with_user(restricted).default_get(["branch_id"])
        eq(values.get("branch_id"), b1.id, "default from default_branch_id")
        values = Order.default_get(["branch_id"])
        truthy(not values.get("branch_id") or values.get("branch_id") == b1.id,
               "root has no default branch")
    check("T2 default branch comes from the user", t2)

    # ------------------------------------------------------------------
    # T3 - warehouse of the branch
    # ------------------------------------------------------------------
    def t3():
        so = Order.create({"partner_id": partner.id, "branch_id": b1.id,
                           "user_id": False, "order_line": line()})
        eq(so.warehouse_id, wh_branch, "warehouse taken from the branch")
        other = Order.create({"partner_id": partner.id, "user_id": False,
                              "order_line": line()})
        truthy(other.warehouse_id != wh_branch, "no branch, other warehouse")
        other.write({"branch_id": b1.id})
        eq(other.warehouse_id, wh_branch, "warehouse follows the branch")
        other.write({"branch_id": b2.id})
        truthy(other.warehouse_id != wh_branch,
               "b2 has no warehouse: falls back to the default warehouse")
    check("T3 warehouse follows the branch (draft)", t3)

    # ------------------------------------------------------------------
    # T4 - confirmation
    # ------------------------------------------------------------------
    def t4():
        so = Order.create({"partner_id": partner.id, "branch_id": b1.id,
                           "user_id": False, "order_line": line(2)})
        truthy(not so._confirmation_error_message(), "no error with a branch")
        eq(so.action_confirm(), True)
        eq(so.state, "sale", "order confirmed")
        eq(so.warehouse_id, wh_branch, "warehouse kept after confirmation")
        # a confirmed order keeps its warehouse when the branch changes
        so.write({"branch_id": b2.id})
        eq(so.warehouse_id, wh_branch, "warehouse untouched on a confirmed SO")
        eq(so.branch_id, b2)
    check("T4 confirm works with a branch, warehouse is stable", t4)

    # ------------------------------------------------------------------
    # T5 - confirmation is refused without a branch
    # ------------------------------------------------------------------
    def t5():
        so = Order.create({"partner_id": partner.id, "user_id": False})
        truthy(not so.branch_id, "no branch on this order")
        message = so._confirmation_error_message()
        truthy(message, "_confirmation_error_message must return a message")
        truthy("branch" in message.lower(), "message talks about the branch")
        with expect(UserError):
            so.action_confirm()
        eq(so.state, "draft", "still a draft")
    check("T5 order without branch cannot be confirmed", t5)

    # ------------------------------------------------------------------
    # T6 - the invoice gets the branch of the order
    # ------------------------------------------------------------------
    def t6():
        so = Order.create({"partner_id": partner.id, "branch_id": b1.id,
                           "user_id": False, "order_line": line()})
        values = so._prepare_invoice()
        eq(values.get("branch_id"), b1.id, "branch on the invoice values")
        so.write({"branch_id": b2.id})
        eq(so._prepare_invoice().get("branch_id"), b2.id)
    check("T6 _prepare_invoice carries the branch", t6)

    # ------------------------------------------------------------------
    # T7 - visibility of the orders for a restricted salesman
    # ------------------------------------------------------------------
    so_own = Order.create({"partner_id": partner.id, "branch_id": b1.id,
                           "user_id": False, "order_line": line()})
    so_other = Order.create({"partner_id": partner.id, "branch_id": b2.id,
                             "user_id": False, "order_line": line()})
    so_legacy = Order.create({"partner_id": partner.id, "branch_id": False,
                              "user_id": False, "order_line": line()})

    def t7():
        all_orders = Order.search([])
        expected = {
            order.id for order in all_orders
            if (not order.branch_id or order.branch_id == b1)
            and (not order.user_id or order.user_id == restricted)
        }
        eq(set(Order.with_user(restricted).search([]).ids), expected,
           "restricted salesman sees his branch, the unassigned branch "
           "orders and the orders without branch")
        with expect(AccessError):
            Order.with_user(restricted).browse(so_other.id).read(["name"])
        # reading his own order works
        eq(Order.with_user(restricted).browse(so_own.id).read(["name"])[0]["name"],
           so_own.name)
        eq(Order.with_user(restricted).browse(so_legacy.id).read(["name"])[0]["name"],
           so_legacy.name)
    check("T7 restricted salesman sees only his orders", t7)

    # ------------------------------------------------------------------
    # T8 - the order lines follow the order
    # ------------------------------------------------------------------
    def t8():
        with expect(AccessError):
            line_id = so_other.order_line[:1].id
            env["sale.order.line"].with_user(restricted).browse(line_id).read(["name"])
        own_line = so_own.order_line[:1].id
        read = env["sale.order.line"].with_user(restricted).browse(own_line).read(
            ["id", "name"])
        eq(read[0]["id"], own_line, "his own line is readable")
    check("T8 order lines are restricted with their order", t8)

    # ------------------------------------------------------------------
    # T9 - creating an order with another branch is refused
    # ------------------------------------------------------------------
    def t9():
        with expect(AccessError):
            Order.with_user(restricted).create(
                {"partner_id": partner.id, "branch_id": b2.id,
                 "order_line": line()})
        # the default branch of the user is accepted
        created = Order.with_user(restricted).create(
            {"partner_id": partner.id, "order_line": line()})
        eq(created.branch_id, b1, "default branch used at create")
        eq(created.warehouse_id, wh_branch, "warehouse from the default branch")
    check("T9 create with the default branch works, another branch refused", t9)

    # ------------------------------------------------------------------
    # T10 - the field domain of a restricted user
    # ------------------------------------------------------------------
    def t10():
        info = Order.with_user(restricted).fields_get(["branch_id"])["branch_id"]
        domain = str(info["domain"])
        truthy("('id', 'in', [%d])" % b1.id in domain,
               "restricted domain must contain his branch: %s" % domain)
        truthy("'%d'" % b2.id not in domain and "[%d]" % b2.id not in domain,
               "restricted domain must hide the other branch: %s" % domain)
        info = Order.fields_get(["branch_id"])["branch_id"]
        domain = str(info["domain"])
        for bid in (b1.id, b2.id):
            truthy(str(bid) in domain, "unrestricted user sees branch %s: %s"
                   % (bid, domain))
    check("T10 branch_id domain follows the visibility", t10)

    # ------------------------------------------------------------------
    # T11 - views
    # ------------------------------------------------------------------
    def t11():
        form = env.ref("branch_management.view_order_form_branch")
        arch = form.arch or ""
        truthy("branch_id" in arch, "form view")
        truthy("required" in arch and "readonly" in arch, "required/readonly")
        combined = env.ref("sale.view_order_form").get_combined_arch()
        truthy('name="branch_id"' in combined, "branch in the combined form")
        combined_list = env.ref("sale.sale_order_tree").get_combined_arch()
        truthy('name="branch_id"' in combined_list, "branch in the list view")
        combined_search = env.ref("sale.view_sales_order_filter").get_combined_arch()
        truthy("group_by" in combined_search and 'name="branch_id"' in combined_search,
               "branch in the search view")
    check("T11 form / list / search views", t11)

    # ------------------------------------------------------------------
    # T12 - ACL rows
    # ------------------------------------------------------------------
    def t12():
        rows = env["ir.access"].browse([
            env.ref("branch_management.access_sale_order_branch_restriction").id,
            env.ref("branch_management.access_sale_order_line_branch_restriction").id,
        ])
        eq(len(rows), 2, "one restriction row per model")
        for row in rows:
            truthy(not row.group_id, "the row must be a global restriction")
            eq(row.operation, "crud")
            truthy("branch_visible_ids" in row.domain, row.domain)
    check("T12 two global restriction rows (sale.order + line)", t12)

except Exception:  # noqa: BLE001 - never leave the shell in a broken state
    import traceback
    LINES.append("FATAL " + traceback.format_exc())
    FAIL += 1
finally:
    print("\n".join([""] + LINES))
    print("\n==== PHASE 4: %d PASS / %d FAIL ====" % (PASS, FAIL))
    env.cr.rollback()
