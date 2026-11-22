# -*- coding: utf-8 -*-
"""Phase 3 runtime tests: security (privilege, groups, ACL, visibility).

Run with:  odoo shell -d balance_mod ... < test_phase3.py
The whole script runs in one transaction and rolls it back at the end.
"""
from contextlib import contextmanager

from odoo.exceptions import AccessError, ValidationError

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


@contextmanager
def expect(exc_types):
    """Assert that the block raises one of ``exc_types``.

    Expected failures are run inside a savepoint (the transaction stays
    usable) and the caches are invalidated afterwards, because an access
    error may leave stale access results in the environment.
    """
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


def visible_ids(user, active_test=False):
    return set(
        Branch.with_user(user).with_context(active_test=active_test).search([]).ids
    )


try:
    Branch = env["branch.branch"]
    Users = env["res.users"]
    Access = env["ir.access"]

    main_company = env.ref("base.main_company")
    g_user = env.ref("base.group_user")
    g_system = env.ref("base.group_system")
    g_portal = env.ref("base.group_portal")
    g_bu = env.ref("branch_management.group_branch_user")
    g_bm = env.ref("branch_management.group_branch_manager")
    g_ba = env.ref("branch_management.group_branch_admin")

    # ------------------------------------------------------------------
    # T0 - users + empty table (the rules must not blow up on an empty set)
    # ------------------------------------------------------------------
    plain = Users.create({
        "name": "Plain Employee", "login": "bm_plain",
        "group_ids": [(6, 0, [g_user.id])],
    })
    empty_restricted = Users.create({
        "name": "Restricted Without Branch", "login": "bm_empty",
        "group_ids": [(6, 0, [g_user.id, g_bu.id])],
    })

    def t0():
        # model level check (no record): must not raise even with 0 branches
        Branch.with_user(plain).browse().check_access("read")
        Branch.with_user(empty_restricted).browse().check_access("read")
        eq(visible_ids(plain), set(), "plain user on empty table")
        eq(visible_ids(empty_restricted), set(), "restricted user on empty table")
        eq(len(Access.search([("model_id.model", "=", "branch.branch")])), 4,
           "ACL rows on branch.branch")
    check("T0 empty table does not raise + 4 ACL rows", t0)

    # ------------------------------------------------------------------
    # T1 - privilege / T2 - groups
    # ------------------------------------------------------------------
    def t1():
        priv = env.ref("branch_management.res_groups_privilege_branch")
        eq(priv.name, "Branches")
        eq(priv.category_id, env.ref("base.module_category_administration"))
    check('T1 res.groups.privilege "Branches" exists', t1)

    def t2():
        eq(g_bu.name, "Branch User")
        eq(g_bm.name, "Branch Manager")
        eq(g_ba.name, "Branch Administrator")
        eq(g_bu.privilege_id, g_bm.privilege_id)
        eq(g_ba.privilege_id, g_bu.privilege_id)
        if g_bu not in g_bm.implied_ids:
            raise AssertionError("Branch Manager does not imply Branch User")
        if g_bm not in g_ba.implied_ids:
            raise AssertionError("Branch Administrator does not imply Branch Manager")
        if g_user not in g_bu.implied_ids:
            raise AssertionError("Branch User does not imply the internal user")
        eq(g_bu.sequence, 10)
        eq(g_bm.sequence, 20)
        eq(g_ba.sequence, 30)
    check("T2 groups, privilege and implied chain", t2)

    # ------------------------------------------------------------------
    # T3 - fields on res.users + the form page
    # ------------------------------------------------------------------
    def t3():
        for fname in ("branch_ids", "default_branch_id", "branch_visible_ids"):
            if fname not in Users._fields:
                raise AssertionError("missing field res.users.%s" % fname)
        eq(Users._fields["branch_ids"].comodel_name, "branch.branch")
        eq(Users._fields["branch_ids"].relation, "res_users_branch_rel")
        eq(Users._fields["default_branch_id"].comodel_name, "branch.branch")
        view = env.ref("branch_management.view_users_form_branches")
        eq(view.inherit_id, env.ref("base.view_users_form"))
        arch = view.arch or view.arch_db or ""
        for token in ("user_branches", "branch_ids", "default_branch_id",
                      "branch_visible_ids"):
            if token not in arch:
                raise AssertionError("token %r missing in the user form" % token)
    check("T3 res.users fields + form page", t3)

    # ------------------------------------------------------------------
    # branches
    # ------------------------------------------------------------------
    company2 = env["res.company"].create({"name": "Branch Test Company 2"})
    b1 = Branch.create({"name": "Riyadh Branch", "code": "RYD",
                        "company_id": main_company.id})
    b2 = Branch.create({"name": "Jeddah Branch", "code": "JED",
                        "company_id": main_company.id})
    b3 = Branch.create({"name": "Dammam Branch", "code": "DMM",
                        "company_id": main_company.id})
    b3.write({"active": False})

    def t4():
        eq(sorted([b1.code, b2.code, b3.code]), ["DMM", "JED", "RYD"])
        eq(len(Branch.search([])), 2, "active branches")
        eq(len(Branch.with_context(active_test=False).search([])), 3,
           "all branches")
    check("T4 branches created, b3 archived", t4)

    # ------------------------------------------------------------------
    # users with branches
    # ------------------------------------------------------------------
    restricted = Users.create({
        "name": "Restricted Employee", "login": "bm_restricted",
        "group_ids": [(6, 0, [g_user.id, g_bu.id])],
        "branch_ids": [(6, 0, [b1.id, b3.id])],
        "default_branch_id": b1.id,
    })
    manager = Users.create({
        "name": "Branch Manager User", "login": "bm_manager",
        "group_ids": [(6, 0, [g_user.id, g_bm.id])],
    })

    def t5():
        af = dict(active_test=False)
        eq(set(restricted.with_context(**af).branch_visible_ids.ids), {b1.id, b3.id},
           "restricted visibility (archived branch included)")
        eq(set(plain.with_context(**af).branch_visible_ids.ids),
           set(Branch.with_context(**af).search([]).ids),
           "unrestricted visibility")
        eq(set(manager.with_context(**af).branch_visible_ids.ids),
           set(Branch.with_context(**af).search([]).ids),
           "manager visibility")
        eq(restricted.default_branch_id, b1)
    check("T5 branch_visible_ids per group", t5)

    # ------------------------------------------------------------------
    # T6 - default branch constraint
    # ------------------------------------------------------------------
    def t6():
        with expect(ValidationError):
            restricted.default_branch_id = b2
        eq(restricted.default_branch_id, b1, "unchanged after the error")
        with expect(ValidationError):
            Users.create({
                "name": "Bad Default", "login": "bm_bad_default",
                "group_ids": [(6, 0, [g_user.id, g_bu.id])],
                "branch_ids": [(6, 0, [b1.id])],
                "default_branch_id": b2.id,
            })
        # an unrestricted user may take any branch as default
        manager.default_branch_id = b2
        eq(manager.default_branch_id, b2)
        manager.default_branch_id = False
        # a restricted user may not drop the branch used as default
        with expect(ValidationError):
            restricted.write({"branch_ids": [(6, 0, [b2.id])]})
        eq(set(restricted.with_context(active_test=False).branch_ids.ids),
           {b1.id, b3.id}, "branch_ids kept")
    check("T6 default branch constraint", t6)

    # ------------------------------------------------------------------
    # T7/T8 - visibility of the records
    # ------------------------------------------------------------------
    def t7():
        eq(visible_ids(restricted, active_test=False), {b1.id, b3.id},
           "restricted, archived included")
        eq(visible_ids(restricted, active_test=True), {b1.id},
           "restricted, active only")
        eq(len(visible_ids(plain, active_test=False)), 3, "plain sees all")
        eq(len(visible_ids(manager, active_test=False)), 3, "manager sees all")
        # a restricted user can read one of their branches
        name = Branch.with_user(restricted).browse(b1.id).read(["name"])[0]["name"]
        eq(name, "Riyadh Branch")
    check("T7 search returns only the visible branches", t7)

    def t8():
        with expect(AccessError):
            Branch.with_user(restricted).browse(b2.id).read(["name"])
    check("T8 restricted user cannot read another branch", t8)

    # ------------------------------------------------------------------
    # T9/T10 - restricted user has no write permission
    # ------------------------------------------------------------------
    def t9():
        with expect(AccessError):
            Branch.with_user(restricted).create(
                {"name": "No Way", "code": "NWY", "company_id": main_company.id})
        with expect(AccessError):
            Branch.with_user(restricted).browse(b1.id).write({"notes": "hack"})
        with expect(AccessError):
            Branch.with_user(restricted).browse(b1.id).unlink()
        eq(Branch.with_context(active_test=False).search_count([]), 3,
           "nothing was created or deleted")
    check("T9 restricted user is read-only (no create/write/delete)", t9)

    # ------------------------------------------------------------------
    # T11 - manager CRUD + cache invalidation of the domains
    # ------------------------------------------------------------------
    def t11():
        # warm the domain cache of the plain user first
        visible_ids(plain, active_test=False)
        new = Branch.with_user(manager).create(
            {"name": "Tabuk Branch", "code": "TBK", "company_id": main_company.id})
        # read it back with no manual cache flush at all
        eq(new.read(["name"])[0]["name"], "Tabuk Branch")
        eq(visible_ids(manager, active_test=False), {b1.id, b2.id, b3.id, new.id},
           "manager sees the new branch")
        eq(visible_ids(plain, active_test=False), {b1.id, b2.id, b3.id, new.id},
           "the cached domains have been invalidated")
        eq(visible_ids(restricted, active_test=False), {b1.id, b3.id},
           "restricted user still does not see it")
    check("T11 manager can create, new branch immediately visible", t11)

    def t12():
        with expect(AccessError):
            Branch.with_user(manager).create(
                {"name": "Other Company", "code": "OTH1",
                 "company_id": company2.id})
    check("T12 manager cannot create a branch of another company", t12)

    def t13():
        Branch.with_user(manager).browse(b1.id).write({"notes": "managed"})
        eq(Branch.with_user(manager).browse(b1.id).notes, "managed")
        tmp = Branch.with_user(manager).create(
            {"name": "Temporary", "code": "TMP1", "company_id": main_company.id})
        tmp.unlink()
        eq(Branch.with_context(active_test=False).search(
            [("id", "=", tmp.id)]).ids, [], "branch deleted")
    check("T13 manager can write and delete", t13)

    # ------------------------------------------------------------------
    # T14 - portal
    # ------------------------------------------------------------------
    def t14():
        portal = Users.create({
            "name": "Portal Branch", "login": "bm_portal", "share": True,
            "group_ids": [(6, 0, [g_portal.id])],
        })
        try:
            seen = Branch.with_user(portal).with_context(
                active_test=False).search([]).ids
        except AccessError:
            seen = "denied"
        if seen not in ([], "denied"):
            raise AssertionError("portal sees branches: %r" % seen)
        with expect(AccessError):
            Branch.with_user(portal).browse(b1.id).read(["name"])
    check("T14 portal user sees nothing", t14)

    # ------------------------------------------------------------------
    # T15 - assigning branches refreshes the visibility
    # ------------------------------------------------------------------
    def t15():
        eq(visible_ids(restricted, active_test=False), {b1.id, b3.id})
        restricted.write({"branch_ids": [(6, 0, [b2.id])],
                          "default_branch_id": b2.id})
        eq(visible_ids(restricted, active_test=False), {b2.id},
           "visibility follows branch_ids")
        restricted.write({"branch_ids": [(6, 0, [b1.id, b3.id])],
                          "default_branch_id": b1.id})
        eq(visible_ids(restricted, active_test=False), {b1.id, b3.id})
    check("T15 branch_ids change refreshes the access domains", t15)

    # ------------------------------------------------------------------
    # T16 - menus
    # ------------------------------------------------------------------
    def t16():
        action = env.ref("branch_management.branch_action")
        for xid in ("menu_branch_sales", "menu_branch_stock",
                    "menu_branch_account", "menu_branch_settings"):
            menu = env.ref("branch_management.%s" % xid)
            eq(menu.action, action, xid)
        eq(env.ref("branch_management.menu_branch_sales").parent_id,
           env.ref("sale.menu_sale_config"))
        eq(env.ref("branch_management.menu_branch_stock").parent_id,
           env.ref("stock.menu_stock_config_settings"))
        eq(env.ref("branch_management.menu_branch_account").parent_id,
           env.ref("account.menu_finance_configuration"))
        settings = env.ref("branch_management.menu_branch_settings")
        eq(settings.parent_id, env.ref("base.menu_administration"))
        if hasattr(settings, "group_ids"):
            groups = set(settings.group_ids.ids)
            if g_system.id not in groups:
                raise AssertionError("settings menu is not restricted")
        else:
            raise AssertionError("ir.ui.menu has no group_ids field")
    check("T16 the 4 menus and their parents", t16)

    # ------------------------------------------------------------------
    # T17 - groups are usable on a real user (the "Roles" checkbox)
    # ------------------------------------------------------------------
    def t17():
        combo = Users.create({
            "name": "Manager With Branches", "login": "bm_combo",
            "group_ids": [(6, 0, [g_user.id, g_bu.id, g_ba.id])],
            "branch_ids": [(6, 0, [b1.id])],
        })
        eq(set(combo.with_context(active_test=False).branch_visible_ids.ids),
           set(Branch.with_context(active_test=False).search([]).ids),
           "administrator sees everything even with branch_ids set")
    check("T17 Branch Administrator overrides the restriction", t17)

except Exception:  # noqa: BLE001 - never leave the shell in a broken state
    import traceback
    LINES.append("FATAL " + traceback.format_exc())
    FAIL += 1
finally:
    print("\n".join([""] + LINES))
    print("\n==== PHASE 3: %d PASS / %d FAIL ====" % (PASS, FAIL))
    env.cr.rollback()
