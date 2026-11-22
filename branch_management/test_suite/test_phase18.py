# -*- coding: utf-8 -*-
"""Phase 18 runtime tests: a branch user sees only what belongs to his branches
inside the Inventory application (warehouses, operation types, locations).

Three decisions shape this phase (they were asked and answered explicitly):

* a warehouse with **no branch** is hidden from a restricted user too — that
  is the whole point of the phase: "no branch" does not mean "mine",
* the screen of the Inventory application is built from the operation types
  (``stock.picking.type``), not from the warehouses, so the operation types
  and the stock locations follow the branch of their warehouse,
* a user that is **not** restricted (an administrator, a branch manager)
  gets **no domain at all** — otherwise ``stock.warehouse0`` would vanish in
  front of the administrator, because "every branch" does not contain "no
  branch".

Run with:  odoo shell -d balance_mod ... < test_phase18.py
The whole script runs in one transaction and rolls it back at the end.
"""
from contextlib import contextmanager

from odoo.exceptions import AccessError
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


try:
    Branch = env["branch.branch"]
    Users = env["res.users"]
    Warehouse = env["stock.warehouse"]
    Location = env["stock.location"]
    PickingType = env["stock.picking.type"]
    IRA = env["ir.access"]

    main_company = env.ref("base.main_company")
    g_user = env.ref("base.group_user")
    g_bu = env.ref("branch_management.group_branch_user")
    g_bm = env.ref("branch_management.group_branch_manager")
    g_su = env.ref("stock.group_stock_user")

    # ------------------------------------------------------------------
    # fixtures: two branches with a warehouse each + one warehouse with no
    # branch (the shape that made the user ask for this phase)
    # ------------------------------------------------------------------
    b1 = Branch.create({"name": "Phase18 Alpha", "code": "P18A",
                        "company_id": main_company.id})
    b2 = Branch.create({"name": "Phase18 Beta", "code": "P18B",
                        "company_id": main_company.id})

    w1 = Warehouse.create({"name": "P18 Alpha WH", "code": "P18A"})
    w2 = Warehouse.create({"name": "P18 Beta WH", "code": "P18B"})
    w0 = Warehouse.create({"name": "P18 Shared WH", "code": "P18S"})
    b1.write({"warehouse_id": w1.id})
    b2.write({"warehouse_id": w2.id})
    env.invalidate_all()

    restricted = Users.create({
        "name": "Phase18 Restricted", "login": "p18_restricted",
        "group_ids": [(6, 0, [g_user.id, g_su.id, g_bu.id])],
        "branch_ids": [(6, 0, [b1.id])],
        "default_branch_id": b1.id,
    })
    plain = Users.create({
        "name": "Phase18 Plain", "login": "p18_plain",
        "group_ids": [(6, 0, [g_user.id, g_su.id])],
    })
    manager = Users.create({
        "name": "Phase18 Manager", "login": "p18_manager",
        "group_ids": [(6, 0, [g_user.id, g_su.id, g_bu.id, g_bm.id])],
    })

    def as_restricted(model):
        return model.with_user(restricted).with_context(active_test=False)

    # ------------------------------------------------------------------
    # T1 - the three rows of the csv
    # ------------------------------------------------------------------
    def t1():
        w_row = env.ref("branch_management.access_stock_warehouse_branch_restriction")
        t_row = env.ref("branch_management.access_stock_picking_type_branch_restriction")
        l_row = env.ref("branch_management.access_stock_location_branch_restriction")
        for row, model in ((w_row, "stock.warehouse"),
                           (t_row, "stock.picking.type"),
                           (l_row, "stock.location")):
            eq(row.model_id.model, model, "model of %s" % row.id)
            truthy(not row.group_id, "a restriction row has no group (%s)" % row.id)
            eq(row.kind, "restriction", "it must restrict, never grant")
            eq(row.operation, "crud")
        eq(w_row.domain, "user._branch_strict_domain('branch_id')")
        eq(t_row.domain, "user._branch_through_warehouse_domain()")
        eq(l_row.domain, "user._branch_through_warehouse_domain()")
        # the whole csv: 3 granted rows + 16 restriction rows
        ours = IRA.search([("id", "in", env["ir.model.data"].search([
            ("module", "=", "branch_management"),
            ("model", "=", "ir.access")]).mapped("res_id"))])
        eq(len(ours), 19, "rows of security/ir.access.csv")
        groupless = ours.filtered(lambda r: not r.group_id)
        eq(len(groupless), 16, "restriction rows (no group = AND-ed)")
        eq(len(ours) - len(groupless), 3, "granted rows (group = OR-ed)")
    check("T1 the three stock rows + the counters of the csv", t1)

    # ------------------------------------------------------------------
    # T2 - what the two helpers return, for the three kinds of user
    # ------------------------------------------------------------------
    def t2():
        eq(restricted._branch_strict_domain("branch_id"),
           [("branch_id", "in", [b1.id])],
           "restricted: only his branches, and no branch-less record")
        eq(plain._branch_strict_domain("branch_id"), [],
           "not restricted: no domain at all")
        eq(manager._branch_strict_domain("branch_id"), [],
           "a branch manager manages every branch")
        eq(restricted._branch_through_warehouse_domain(),
           ["|", ("warehouse_id", "=", False),
            ("warehouse_id.branch_id", "in", [b1.id])],
           "restricted: no warehouse = shared, else follow the warehouse")
        eq(restricted._branch_through_warehouse_domain("warehouse_id"),
           ["|", ("warehouse_id", "=", False),
            ("warehouse_id.branch_id", "in", [b1.id])],
           "locations: shared only, everything else follows its warehouse")
        eq(plain._branch_through_warehouse_domain(), [],
           "not restricted: no domain at all")
    check("T2 the two helpers return exactly the decided domain", t2)

    # ------------------------------------------------------------------
    # T3 - the text of the csv is what Odoo evaluates (no typo, no missing
    #      method: the very machinery of _access_domain does the eval)
    # ------------------------------------------------------------------
    def t3():
        row = env.ref("branch_management.access_stock_warehouse_branch_restriction")
        for user, expected in ((restricted, [("branch_id", "in", [b1.id])]),
                               (plain, []),
                               (manager, [])):
            ctx = IRA.with_user(user)._eval_context()
            eq(safe_eval(row.domain, ctx), expected,
               "evaluated by Odoo for %s" % user.login)
        t_row = env.ref("branch_management.access_stock_picking_type_branch_restriction")
        eq(safe_eval(t_row.domain,
                     IRA.with_user(restricted)._eval_context()),
           ["|", ("warehouse_id", "=", False),
            ("warehouse_id.branch_id", "in", [b1.id])])
        l_row = env.ref("branch_management.access_stock_location_branch_restriction")
        eq(safe_eval(l_row.domain,
                     IRA.with_user(restricted)._eval_context()),
           ["|", ("warehouse_id", "=", False),
            ("warehouse_id.branch_id", "in", [b1.id])])
    check("T3 the csv text evaluates through Odoo's own machinery", t3)

    # ------------------------------------------------------------------
    # T4 - the warehouse search of a restricted user
    # ------------------------------------------------------------------
    def t4():
        seen = as_restricted(Warehouse).search([])
        eq(seen.ids, [w1.id],
           "only the warehouse of his branch: neither the other branch's "
           "nor the one without a branch")
    check("T4 a branch user sees only the warehouses of his branches", t4)

    # ------------------------------------------------------------------
    # T5 - reading directly is refused, not filtered silently
    # ------------------------------------------------------------------
    def t5():
        with expect(AccessError):
            as_restricted(Warehouse).browse(w2.id).read(["name"])
        with expect(AccessError):
            as_restricted(Warehouse).browse(w0.id).read(["name"])
        truthy(as_restricted(Warehouse).browse(w1.id).read(["name"]),
               "his own warehouse stays readable")
    check("T5 another branch's warehouse raises AccessError", t5)

    # ------------------------------------------------------------------
    # T6 - nobody that is not restricted loses a warehouse (the trap of
    #      "every branch" not containing "no branch")
    # ------------------------------------------------------------------
    def t6():
        wanted = {w1.id, w2.id, w0.id}
        for user, label in ((plain, "a user that is not a branch user"),
                            (manager, "a branch manager")):
            seen = Warehouse.with_user(user).with_context(
                active_test=False).search([])
            truthy(wanted <= set(seen.ids),
                   "%s must see every warehouse (%r)" % (label, seen.ids))
    check("T6 no warehouse is lost for a user that is not restricted", t6)

    # ------------------------------------------------------------------
    # T7 - the operation types: only the ones of his warehouse (this is
    #      what the screen of the Inventory application shows)
    # ------------------------------------------------------------------
    def t7():
        mine = PickingType.sudo().with_context(active_test=False).search(
            [("warehouse_id", "=", w1.id)])
        truthy(len(mine) >= 1, "the warehouse has operation types")
        seen = as_restricted(PickingType).search([])
        eq(sorted(seen.ids), sorted(mine.ids),
           "the application screen shows only his branch's operations")
    check("T7 the application screen only shows his branch's operations", t7)

    # ------------------------------------------------------------------
    # T8 - the stock locations: his warehouse's + the shared ones, nothing
    #      else. The search and the direct read are both checked: the
    #      dotted path alone does not match a location with no warehouse.
    # ------------------------------------------------------------------
    def t8():
        shared = Location.sudo().with_context(active_test=False).search(
            [("warehouse_id", "=", False)])
        mine = Location.sudo().with_context(active_test=False).search(
            [("warehouse_id", "=", w1.id)])
        truthy(len(shared) >= 3, "there are shared stock locations")
        truthy(len(mine) >= 1, "the warehouse has stock locations")
        seen = as_restricted(Location).search([])
        eq(sorted(seen.ids), sorted((shared | mine).ids),
           "shared locations + his warehouse's locations, nothing else")
        for hidden in (w2, w0):
            locs = Location.sudo().with_context(active_test=False).search(
                [("warehouse_id", "=", hidden.id)], limit=1)
            truthy(locs, "%s has locations" % hidden.code)
            truthy(not (set(seen.ids) & set(locs.ids)),
                   "the locations of %s are gone" % hidden.code)
    check("T8 stock locations follow the branch of their warehouse", t8)

    # ------------------------------------------------------------------
    # T9 - the shared locations are still directly readable (they belong
    #      to no branch: hiding them would break every delivery)
    # ------------------------------------------------------------------
    def t9():
        for xmlid in ("stock.stock_location_customers",
                      "stock.stock_location_suppliers"):
            loc = env.ref(xmlid)
            truthy(not loc.warehouse_id, "%s must belong to no warehouse" % xmlid)
            eq(as_restricted(Location).browse(loc.id).read(["name"])[0]["name"],
               loc.name, "%s stays readable" % xmlid)
    check("T9 the shared stock locations stay readable", t9)

    # ------------------------------------------------------------------
    # T10 - the locations of the other branch and of the branch-less
    #       warehouse are refused
    # ------------------------------------------------------------------
    def t10():
        other = (Location.sudo().with_context(active_test=False).search(
            [("warehouse_id", "=", w2.id)], limit=1))
        truthy(other, "the other branch has locations")
        for loc in other:
            with expect(AccessError):
                as_restricted(Location).browse(loc.id).read(["name"])
        truthy(not (set(as_restricted(Location).search([]).ids)
                    & set(other.ids)),
               "they are not even found by a search")
        # the locations of the warehouse that no branch owns yet are
        # refused too: this is the precondition of the phase
        unassigned = Location.sudo().with_context(active_test=False).search(
            [("warehouse_id", "=", w0.id)], limit=1)
        truthy(unassigned, "the unassigned warehouse has locations")
        with expect(AccessError):
            as_restricted(Location).browse(unassigned.id).read(["name"])
    check("T10 the other and the unassigned locations are refused", t10)

    # ------------------------------------------------------------------
    # T11 - the same user without the branch group loses nothing
    # ------------------------------------------------------------------
    def t11():
        everything = Location.sudo().with_context(active_test=False).search([])
        seen = Location.with_user(plain).with_context(
            active_test=False).search([])
        truthy(set(everything.ids) <= set(seen.ids),
               "a user that is not restricted sees every location")
        types = PickingType.sudo().with_context(active_test=False).search([])
        seen_types = PickingType.with_user(plain).with_context(
            active_test=False).search([])
        truthy(set(types.ids) <= set(seen_types.ids),
               "a user that is not restricted sees every operation type")
    check("T11 a user that is not restricted loses nothing", t11)

    # ------------------------------------------------------------------
    # T12 - the phase changed the security only: no field, no model
    # ------------------------------------------------------------------
    def t12():
        truthy("branch_id" not in PickingType._fields,
               "stock.picking.type keeps no new field")
        truthy("branch_id" not in Location._fields,
               "stock.location keeps no new field")
        eq(len(PickingType._inherits), 0, "no new inherited model either")
    check("T12 the phase is ACL only: no schema change", t12)

    # ------------------------------------------------------------------
    # T13 - the other stock rows are untouched (phase 18 touched three)
    # ------------------------------------------------------------------
    def t13():
        for xmlid in ("branch_management.access_stock_picking_branch_restriction",
                      "branch_management.access_stock_move_branch_restriction"):
            row = env.ref(xmlid)
            truthy("('branch_id', '=', False)" in (row.domain or ""),
                   "%s still keeps the records without a branch visible"
                   % xmlid)
            truthy("branch_visible_ids" in (row.domain or ""),
                   "%s still spells the domain literally" % xmlid)
    check("T13 the picking and move rows are untouched", t13)

    # ------------------------------------------------------------------
    # T14 - the rule follows the data: handing the branch-less warehouse
    #       to a branch makes it visible, with no restart and no cache to
    #       clear by hand
    # ------------------------------------------------------------------
    def t14():
        eq(len(as_restricted(Warehouse).search([])), 1, "before the change")
        b3 = Branch.create({"name": "Phase18 Gamma", "code": "P18G",
                            "company_id": main_company.id,
                            "warehouse_id": w0.id})
        env.invalidate_all()
        restricted.write({"branch_ids": [(4, b3.id)]})
        seen = as_restricted(Warehouse).search([])
        truthy({w1.id, w0.id} <= set(seen.ids),
               "the warehouse he was given is visible (%r)" % seen.ids)
        truthy(w2.id not in seen.ids, "the other branch stays hidden")
        truthy(as_restricted(Warehouse).browse(w0.id).read(["name"]),
               "and directly readable now")
    check("T14 the rule follows the data — no restart needed", t14)

except Exception:  # noqa: BLE001 - never leave the shell in a broken state
    import traceback
    LINES.append("FATAL " + traceback.format_exc())
    FAIL += 1
finally:
    print("\n".join([""] + LINES))
    print("\n==== PHASE 18: %d PASS / %d FAIL ====" % (PASS, FAIL))
    env.cr.rollback()
