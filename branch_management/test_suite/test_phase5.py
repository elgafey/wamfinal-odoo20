# -*- coding: utf-8 -*-
"""Phase 5 runtime tests: inventory (warehouse / picking / move).

Run with:  odoo shell -d balance_mod ... < test_phase5.py
The whole script runs in one transaction and rolls it back at the end.
"""
from contextlib import contextmanager

from odoo.exceptions import AccessError, UserError

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
    g_stock = env.ref("stock.group_stock_user")

    # ------------------------------------------------------------------
    # fixtures
    # ------------------------------------------------------------------
    wh0 = env.ref("stock.warehouse0")
    wh_branch = env["stock.warehouse"].create(
        {"name": "Branch Warehouse", "code": "BRW"})
    partner = env["res.partner"].create({"name": "Phase5 Customer"})
    product = env["product.product"].create(
        {"name": "Phase5 Product", "list_price": 100.0})

    b1 = Branch.create({"name": "Stock Branch A", "code": "KSA",
                        "company_id": main_company.id,
                        "warehouse_id": wh_branch.id})
    b2 = Branch.create({"name": "Stock Branch B", "code": "KSB",
                        "company_id": main_company.id})

    restricted = Users.create({
        "name": "Restricted Stock User", "login": "p5_restricted",
        "group_ids": [(6, 0, [g_user.id, g_bu.id, g_salesman.id, g_stock.id])],
        "branch_ids": [(6, 0, [b1.id])],
        "default_branch_id": b1.id,
    })

    # phase 18: a restricted user works with the operation types of the
    # warehouse of his branch. The ones of a warehouse that no branch owns
    # (``stock.warehouse0``) are hidden from him, so they cannot be used to
    # exercise a create made by that user.
    picking_type = env["stock.picking.type"].search(
        [("warehouse_id", "=", wh_branch.id)], limit=1)
    if not picking_type:
        picking_type = env["stock.picking.type"].search(
            [("company_id", "=", main_company.id)], limit=1)
    truthy(picking_type, "an operation type must exist")
    src = picking_type.default_location_src_id or wh0.view_location_id
    dst = picking_type.default_location_dest_id or wh0.view_location_id

    def mk_picking(branch):
        return env["stock.picking"].create({
            "picking_type_id": picking_type.id,
            "location_id": src.id,
            "location_dest_id": dst.id,
            "branch_id": branch.id if branch else False,
        })

    def mk_move(branch=False, picking=False):
        vals = {"product_id": product.id, "product_uom_qty": 1,
                "location_id": src.id, "location_dest_id": dst.id}
        if picking:
            vals["picking_id"] = picking.id
        if branch:
            vals["branch_id"] = branch.id
        return env["stock.move"].create(vals)

    def line(qty=1):
        return [(0, 0, {"product_id": product.id,
                        "product_uom_qty": qty,
                        "price_unit": 100.0})]

    # ------------------------------------------------------------------
    # T1 - branch_id on the warehouse follows the branch
    # ------------------------------------------------------------------
    def t1():
        eq(wh_branch.branch_id, b1, "warehouse taken by the branch")
        wh_new = env["stock.warehouse"].create(
            {"name": "Warehouse of branch B", "code": "WBB"})
        truthy(not wh_new.branch_id, "warehouse without branch")
        b2.write({"warehouse_id": wh_new.id})
        eq(wh_new.branch_id, b2, "set from the branch form")
        b2.write({"warehouse_id": False})
        truthy(not wh_new.branch_id, "cleared from the branch form")
        b2.write({"warehouse_id": wh_new.id})
        eq(wh_new.branch_id, b2, "set again")
        truthy(not wh0.branch_id, "the default warehouse has no branch")
    check("T1 warehouse.branch_id follows branch.warehouse_id", t1)

    wh_other = b2.warehouse_id  # hidden warehouse of branch B

    # ------------------------------------------------------------------
    # T2 - the procurement values carry the branch
    # ------------------------------------------------------------------
    def t2():
        so = Order.create({"partner_id": partner.id, "branch_id": b1.id,
                           "user_id": False, "order_line": line()})
        values = so.order_line._prepare_procurement_values()
        eq(values.get("branch_id"), b1.id, "branch in the procurement values")
        so.write({"branch_id": b2.id})
        eq(so.order_line._prepare_procurement_values().get("branch_id"),
           b2.id, "branch follows the order")
    check("T2 _prepare_procurement_values carries the branch", t2)

    # ------------------------------------------------------------------
    # T3 - the custom move fields
    # ------------------------------------------------------------------
    def t3():
        names = env["stock.rule"]._get_custom_move_fields()
        truthy("branch_id" in names, "branch_id in %s" % names)
    check("T3 _get_custom_move_fields contains branch_id", t3)

    # ------------------------------------------------------------------
    # T4 - a confirmed order gives the branch to its moves and transfer
    # ------------------------------------------------------------------
    def t4():
        so = Order.create({"partner_id": partner.id, "branch_id": b1.id,
                           "user_id": False, "order_line": line(2)})
        so.action_confirm()
        eq(so.state, "sale")
        moves = so.order_line.move_ids
        truthy(moves, "the delivery moves are created")
        for move in moves:
            eq(move.branch_id, b1, "move branch")
        pickings = moves.mapped("picking_id")
        truthy(pickings, "the delivery transfer is created")
        for picking in pickings:
            eq(picking.branch_id, b1, "transfer branch")
    check("T4 confirmed order -> moves and transfer carry the branch", t4)

    # ------------------------------------------------------------------
    # T5 - a move created inside a transfer takes its branch
    # ------------------------------------------------------------------
    def t5():
        picking = mk_picking(b1)
        # 1) the transfer comes from the context (as in the form)
        move = env["stock.move"].with_context(
            default_picking_id=picking.id).create({
                "product_id": product.id, "product_uom_qty": 1,
                "location_id": src.id, "location_dest_id": dst.id})
        eq(move.picking_id, picking, "the move is in the transfer")
        eq(move.branch_id, b1, "branch taken from the context")
        # 2) the transfer is given in the values
        move2 = mk_move(picking=picking)
        eq(move2.branch_id, b1, "branch taken from picking_id")
        # 3) a returned move takes the branch of the move it returns
        returned = mk_move(branch=b1)
        back2 = env["stock.move"].create({
            "product_id": product.id, "product_uom_qty": 1,
            "location_id": src.id, "location_dest_id": dst.id,
            "origin_returned_move_id": returned.id})
        eq(back2.branch_id, b1, "branch taken from the returned move")
    check("T5 move inherits the branch of its transfer / returned move", t5)

    # ------------------------------------------------------------------
    # T6 - changing the branch of a transfer updates its moves
    # ------------------------------------------------------------------
    def t6():
        picking = mk_picking(b1)
        m1 = mk_move(picking=picking)
        m2 = mk_move(picking=picking)
        eq(m1.branch_id, b1)
        picking.write({"branch_id": b2.id})
        for move in picking.move_ids:
            eq(move.branch_id, b2, "moves follow the transfer")
        picking.write({"branch_id": False})
        for move in picking.move_ids:
            truthy(not move.branch_id, "moves follow the transfer")
        picking.write({"branch_id": b1.id})
        for move in picking.move_ids:
            eq(move.branch_id, b1, "moves follow the transfer")
    check("T6 transfer branch propagates to its moves", t6)

    # ------------------------------------------------------------------
    # T7 - a new transfer is created on the branch of its moves
    # ------------------------------------------------------------------
    def t7():
        move_a = mk_move(branch=b1)
        eq(move_a._get_new_picking_values().get("branch_id"), b1.id,
           "single branch")
        move_b = mk_move(branch=b2)
        truthy(not (move_a + move_b)._get_new_picking_values().get("branch_id"),
               "two branches: no branch on the transfer")
        move_none = mk_move()
        truthy(not (move_a + move_none)._get_new_picking_values().get("branch_id"),
               "a move without branch: no branch on the transfer")
        truthy(not (move_none + mk_move())._get_new_picking_values().get(
            "branch_id"), "no branch at all")
    check("T7 _get_new_picking_values takes the branch of the moves", t7)

    # ------------------------------------------------------------------
    # T8 - moves of two branches never share a transfer
    # ------------------------------------------------------------------
    def t8():
        # same locations, same type, same priority: only the branch differs
        keys = [m._key_assign_picking()
                for m in (mk_move(branch=b1), mk_move(branch=b2), mk_move())]
        eq(len({str(key) for key in keys}), 3,
           "three branches, three different transfer keys")
    check("T8 _key_assign_picking contains the branch", t8)

    # ------------------------------------------------------------------
    # T9 - the three restriction rows
    # ------------------------------------------------------------------
    def t9():
        for xmlid in ("access_stock_warehouse_branch_restriction",
                      "access_stock_picking_branch_restriction",
                      "access_stock_move_branch_restriction"):
            row = env.ref("branch_management." + xmlid)
            truthy(not row.group_id, "%s must be a global row" % xmlid)
            eq(row.operation, "crud", xmlid)
        # phase 18: the warehouse row delegates to the helper, because a
        # plain domain cannot say "unrestricted user = no domain at all"
        w_row = env.ref(
            "branch_management.access_stock_warehouse_branch_restriction")
        eq(w_row.domain, "user._branch_strict_domain('branch_id')")
        for xmlid in ("access_stock_picking_branch_restriction",
                      "access_stock_move_branch_restriction"):
            row = env.ref("branch_management." + xmlid)
            truthy("branch_visible_ids" in row.domain, row.domain)
    check("T9 three global restriction rows (warehouse/picking/move)", t9)

    # ------------------------------------------------------------------
    # fixtures for the restriction tests
    # ------------------------------------------------------------------
    p_own = mk_picking(b1)
    p_other = mk_picking(b2)
    p_legacy = mk_picking(False)
    m_own = mk_move(picking=p_own)
    m_other = mk_move(picking=p_other)
    m_legacy = mk_move(picking=p_legacy)

    # ------------------------------------------------------------------
    # T10 - what a restricted user can see
    # ------------------------------------------------------------------
    def t10():
        # warehouses
        # phase 18: a warehouse with no branch is hidden too — "no branch"
        # is not "mine"
        expected = {w.id for w in env["stock.warehouse"].search([])
                    if w.branch_id == b1}
        eq(set(env["stock.warehouse"].with_user(restricted).search([]).ids),
           expected, "visible warehouses")
        truthy(wh_branch.id in expected, "the warehouse of his branch")
        truthy(wh0.id not in expected,
               "the warehouse without a branch is hidden (phase 18)")
        truthy(wh_other.id not in expected, "warehouse of branch B hidden")
        for hidden, label in ((wh_other, "warehouse of branch B"),
                              (wh0, "warehouse without a branch")):
            with expect(AccessError):
                env["stock.warehouse"].with_user(restricted).browse(
                    hidden.id).read(["name"])
            truthy(not (set(env["stock.warehouse"].with_user(
                restricted).search([]).ids) & {hidden.id}),
                "%s not even found by a search" % label)
        # transfers
        expected = {pk.id for pk in env["stock.picking"].search([])
                    if not pk.branch_id or pk.branch_id == b1}
        eq(set(env["stock.picking"].with_user(restricted).search([]).ids),
           expected, "visible transfers")
        truthy(p_own.id in expected, "his transfer is visible")
        truthy(p_legacy.id in expected, "transfer without branch visible")
        truthy(p_other.id not in expected, "transfer of branch B hidden")
        with expect(AccessError):
            env["stock.picking"].with_user(restricted).browse(
                p_other.id).read(["name"])
        # moves
        expected = {mv.id for mv in env["stock.move"].search([])
                    if not mv.branch_id or mv.branch_id == b1}
        eq(set(env["stock.move"].with_user(restricted).search([]).ids),
           expected, "visible moves")
        with expect(AccessError):
            env["stock.move"].with_user(restricted).browse(
                m_other.id).read(["id"])
        # a move without branch is still readable
        truthy(env["stock.move"].with_user(restricted).browse(
            m_legacy.id).read(["id"])[0]["id"] == m_legacy.id)
    check("T10 restricted user: warehouses / transfers / moves", t10)

    # ------------------------------------------------------------------
    # T11 - a restricted user cannot create outside of his branches
    # ------------------------------------------------------------------
    def t11():
        with expect(AccessError):
            mk_picking_for_user = env["stock.picking"].with_user(restricted)
            mk_picking_for_user.create({
                "picking_type_id": picking_type.id,
                "location_id": src.id, "location_dest_id": dst.id,
                "branch_id": b2.id})
        ok = env["stock.picking"].with_user(restricted).create({
            "picking_type_id": picking_type.id,
            "location_id": src.id, "location_dest_id": dst.id,
            "branch_id": b1.id})
        eq(ok.branch_id, b1, "his own branch is accepted")
        with expect(AccessError):
            env["stock.move"].with_user(restricted).create({
                "product_id": product.id, "product_uom_qty": 1,
                "location_id": src.id, "location_dest_id": dst.id,
                "branch_id": b2.id})
        move = env["stock.move"].with_user(restricted).create({
            "product_id": product.id, "product_uom_qty": 1,
            "location_id": src.id, "location_dest_id": dst.id,
            "branch_id": b1.id})
        eq(move.branch_id, b1, "his own branch is accepted")
        # his default branch is used when he does not choose one
        no_branch = env["stock.move"].with_user(restricted).create({
            "product_id": product.id, "product_uom_qty": 1,
            "location_id": src.id, "location_dest_id": dst.id})
        truthy(not no_branch.branch_id, "no default branch on a move")
    check("T11 create restricted to the visible branches", t11)

    # ------------------------------------------------------------------
    # T12 - a restricted user confirms one of his orders
    # ------------------------------------------------------------------
    def t12():
        so = env["sale.order"].with_user(restricted).create({
            "partner_id": partner.id, "order_line": line(2)})
        eq(so.branch_id, b1, "default branch of the user")
        eq(so.warehouse_id, wh_branch, "warehouse of his branch")
        so.action_confirm()
        eq(so.state, "sale", "the order is confirmed")
        moves = so.order_line.move_ids
        truthy(moves, "moves created")
        for move in moves:
            eq(move.branch_id, b1, "move branch")
            truthy(env["stock.move"].with_user(restricted).browse(
                move.id).read(["id"]), "he can read his own move")
        pickings = moves.mapped("picking_id")
        truthy(pickings, "transfer created")
        for picking in pickings:
            eq(picking.branch_id, b1, "transfer branch")
    check("T12 restricted user confirms his order without any error", t12)

    # ------------------------------------------------------------------
    # T13 - views
    # ------------------------------------------------------------------
    def t13():
        combined = env.ref("stock.view_picking_form").get_combined_arch()
        truthy('name="branch_id"' in combined, "transfer form")
        combined = env.ref("stock.vpicktree").get_combined_arch()
        truthy('name="branch_id"' in combined, "transfer list")
        combined = env.ref("stock.view_warehouse").get_combined_arch()
        truthy('name="branch_id"' in combined, "warehouse form")
        combined = env.ref("stock.view_move_tree").get_combined_arch()
        truthy('name="branch_id"' in combined, "move list")
    check("T13 transfer form/list, warehouse form, move list", t13)

except Exception:  # noqa: BLE001 - never leave the shell in a broken state
    import traceback
    LINES.append("FATAL " + traceback.format_exc())
    FAIL += 1
finally:
    print("\n".join([""] + LINES))
    print("\n==== PHASE 5: %d PASS / %d FAIL ====" % (PASS, FAIL))
    env.cr.rollback()
