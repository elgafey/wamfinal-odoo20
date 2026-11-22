# -*- coding: utf-8 -*-
"""Phase 11 runtime tests: the access rule of the contacts (res.partner).

Run with:  odoo shell -d balance_mod ... < test_phase11.py
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
    Partner = env["res.partner"]
    Order = env["sale.order"]
    IRA = env["ir.access"]

    main_company = env.ref("base.main_company")
    g_user = env.ref("base.group_user")
    g_bu = env.ref("branch_management.group_branch_user")
    g_pm = env.ref("base.group_partner_manager")
    g_sales = env.ref("sales_team.group_sale_salesman")

    b1 = Branch.create({"name": "Phase11 Branch A", "code": "P11A",
                        "company_id": main_company.id})
    b2 = Branch.create({"name": "Phase11 Branch B", "code": "P11B",
                        "company_id": main_company.id})

    p1 = Partner.create({"name": "Phase11 partner of A",
                         "branch_ids": [(6, 0, [b1.id])]})
    p2 = Partner.create({"name": "Phase11 partner of B",
                         "branch_ids": [(6, 0, [b2.id])]})
    p0 = Partner.create({"name": "Phase11 partner without branch"})

    restricted = Users.create({
        "name": "Phase11 Restricted", "login": "p11_restricted",
        "group_ids": [(6, 0, [g_user.id, g_bu.id, g_pm.id, g_sales.id])],
        "branch_ids": [(6, 0, [b1.id])],
        "default_branch_id": b1.id,
    })
    plain = Users.create({
        "name": "Phase11 Plain", "login": "p11_plain",
        "group_ids": [(6, 0, [g_user.id])],
    })

    def as_restricted(model):
        return model.with_user(restricted)

    # ------------------------------------------------------------------
    # T1 - the has_branch helper the rule needs
    # ------------------------------------------------------------------
    def t1():
        field = Partner._fields.get("has_branch")
        truthy(field, "res.partner.has_branch missing")
        eq(field.type, "boolean")
        truthy(field.store, "the rule needs it in SQL")
        truthy(field.readonly, "a computed helper must not be set by hand")
        truthy("branch_ids" in tuple(field.get_depends(Partner)[0]),
               "the helper must follow branch_ids")
        eq(p1.has_branch, True, "a contact with a branch")
        eq(p2.has_branch, True, "another contact with a branch")
        eq(p0.has_branch, False, "a contact without branch")
        eq(Partner.create({"name": "Phase11 late"}).has_branch, False,
           "created without a branch")
        late = Partner.create({"name": "Phase11 late2"})
        late.write({"branch_ids": [(6, 0, [b1.id])]})
        eq(late.has_branch, True, "flips when a branch is set")
        late.write({"branch_ids": [(5, 0, 0)]})
        eq(late.has_branch, False, "flips back when it is removed")
    check("T1 has_branch mirrors branch_ids (stored)", t1)

    # ------------------------------------------------------------------
    # T2 - the restriction row itself
    # ------------------------------------------------------------------
    def t2():
        row = env.ref("branch_management.access_res_partner_branch_restriction")
        eq(row.model_id.model, "res.partner")
        truthy(not row.group_id, "a restriction row has no group")
        eq(row.kind, "restriction", "it must restrict, never grant")
        eq(row.operation, "crud")
        domain = row.domain
        for leaf in ("has_branch", "branch_ids", "branch_visible_ids",
                     "child_of"):
            truthy(leaf in domain, "leaf %r missing in %s" % (leaf, domain))
        # the trap: on a x2many Odoo rewrites ("=", False) into "owns no
        # VISIBLE branch", which would let every other-branch contact through
        truthy("('branch_ids', '=', False)" not in domain,
               "('branch_ids','=',False) must not be used: Odoo rewrites it "
               "into 'owns no VISIBLE branch'")
        # the whole CSV: 3 granted rows + 16 restriction rows
        ours = IRA.search([("id", "in", env["ir.model.data"].search([
            ("module", "=", "branch_management"),
            ("model", "=", "ir.access")]).mapped("res_id"))])
        eq(len(ours), 19, "rows of security/ir.access.csv")
        groupless = ours.filtered(lambda r: not r.group_id)
        eq(len(groupless), 16, "restriction rows (no group = AND-ed)")
        eq(len(ours) - len(groupless), 3, "granted rows (group = OR-ed)")
        for other in groupless:
            # phase 18: the three stock rows ask a helper instead of
            # spelling the domain, so that "unrestricted = no domain" is
            # expressible at all (a plain domain cannot say it).
            truthy("branch_visible_ids" in (other.domain or "")
                   or (other.domain or "").startswith("user._branch_"),
                   "every restriction uses branch_visible_ids or one of the "
                   "phase 18 helpers (row %s)" % other.id)
    check("T2 the restriction row is a global restriction", t2)

    # ------------------------------------------------------------------
    # T3 - what the restricted user sees
    # ------------------------------------------------------------------
    def t3():
        found = as_restricted(Partner).search([])
        truthy(p1 in found, "the contact of his own branch is visible")
        truthy(p2 not in found,
               "the contact of another branch must be invisible")
        truthy(p0 in found, "a contact without branch stays visible")
        eq(sorted(as_restricted(Partner).search(
            [("has_branch", "=", False)]).ids),
           sorted(Partner.search([("has_branch", "=", False)]).ids),
           "every contact without branch, for everybody")
    check("T3 own branch + no branch visible, other branch hidden", t3)

    # ------------------------------------------------------------------
    # T4 - reading / writing the contact of another branch
    # ------------------------------------------------------------------
    def t4():
        with expect(AccessError):
            as_restricted(Partner).browse(p2.id).read(["name"])
        with expect(AccessError):
            as_restricted(Partner).browse(p2.id).write({"comment": "x"})
        with expect(AccessError):
            as_restricted(Partner).browse(p2.id).unlink()
        truthy(as_restricted(Partner).browse(p1.id).read(["name"]),
               "his own branch contact stays readable")
        as_restricted(Partner).browse(p1.id).write({"comment": "ok"})
    check("T4 no read/write/unlink on another branch contact", t4)

    # ------------------------------------------------------------------
    # T5 - a user that is not a "Branch User" is not restricted
    # ------------------------------------------------------------------
    def t5():
        found = Partner.with_user(plain).search([])
        truthy(p1 in found and p2 in found and p0 in found,
               "a user without the branch group sees every contact")
        domain = Partner.with_user(plain)._access_domain("read")
        truthy(not domain.is_false(), "never locked out of the model")
    check("T5 a user without the branch group sees everyone", t5)

    # ------------------------------------------------------------------
    # T6 - the user's own contact and the company contact are protected
    # ------------------------------------------------------------------
    def t6():
        # his own contact, forced onto a foreign branch
        restricted.partner_id.write({"branch_ids": [(6, 0, [b2.id])]})
        me = as_restricted(Partner).browse(restricted.partner_id.id)
        truthy(me.exists(), "a user must always read his own contact")
        eq(me.name, restricted.name)
        # the company contact (no branch) is reachable
        truthy(as_restricted(Partner).browse(
            main_company.partner_id.id).exists(),
            "the company contact stays readable")
        restricted.partner_id.write({"branch_ids": [(5, 0, 0)]})
        truthy(not restricted.partner_id.has_branch, "reset")
    check("T6 own contact and company contact always readable", t6)

    # ------------------------------------------------------------------
    # T7 - reading the names of the users (res.users inherits res.partner)
    # ------------------------------------------------------------------
    def t7():
        names = as_restricted(Users).search([]).mapped("name")
        truthy(restricted.name in names, "he finds himself")
        truthy(any(names), "the search does not raise")
        # attribute access on a colleague stays possible
        colleague = plain.id
        truthy(as_restricted(Users).browse(colleague).name,
               "a colleague's name is readable")
    check("T7 reading the users is not broken", t7)

    # ------------------------------------------------------------------
    # T8 - creating contacts keeps working
    # ------------------------------------------------------------------
    def t8():
        created = as_restricted(Partner).create({
            "name": "Phase11 created by the restricted user",
            "branch_ids": [(6, 0, [b1.id])],
        })
        eq(created.has_branch, True)
        truthy(created in as_restricted(Partner).search([]),
               "he sees what he created")
        plain_created = as_restricted(Partner).create(
            {"name": "Phase11 created without branch"})
        truthy(plain_created in as_restricted(Partner).search([]),
               "a contact without branch is immediately visible")
    check("T8 the restricted user still creates contacts", t8)

    # ------------------------------------------------------------------
    # T9 - documents of his branch still show their partner
    # ------------------------------------------------------------------
    def t9():
        product = env["product.product"].create({
            "name": "Phase11 product", "type": "consu",
            "is_storable": True,
        })
        order = Order.create({
            "partner_id": p1.id, "branch_id": b1.id, "user_id": False,
            "order_line": [(0, 0, {"product_id": product.id,
                                   "price_unit": 10})],
        })
        got = as_restricted(Order).browse(order.id).read(["partner_id"])
        truthy(got, "he can read his own order")
        # read() formats a many2one as (id, display_name)
        pid = got[0]["partner_id"]
        eq(pid[0] if isinstance(pid, (tuple, list)) else pid, p1.id,
           "his contact resolves")
        eq(as_restricted(Order).browse(order.id).partner_id.name, p1.name,
           "the partner of his order resolves")
        # a document of HIS branch that points at a contact of another branch
        # is a data inconsistency: the order stays visible, but its contact is
        # not readable anymore (see T4) -- so never put a foreign branch on a
        # contact that a document of his branch already points at.
        bad = Order.create({
            "partner_id": p2.id, "branch_id": b1.id, "user_id": False,
            "order_line": [(0, 0, {"product_id": product.id,
                                   "price_unit": 10})],
        })
        truthy(as_restricted(Order).browse(bad.id).exists(),
               "the order itself stays visible")
        # the document rule is independent from the contact rule: the order
        # still returns the id of the contact, but reading the contact itself
        # is refused (T4)
        got_bad = as_restricted(Order).browse(bad.id).read(["partner_id"])
        pid = got_bad[0]["partner_id"]
        eq(pid[0] if isinstance(pid, (tuple, list)) else pid, p2.id,
           "the id of the contact is still there")
        with expect(AccessError):
            as_restricted(Partner).browse(p2.id).read(["name"])
    check("T9 his documents still resolve their partner", t9)

    # ------------------------------------------------------------------
    # T10 - the many2one restriction of the 13 other models is untouched
    # ------------------------------------------------------------------
    def t10():
        # user_id=False is the convention of the other phases: it satisfies
        # core "Personal Orders" rule so that only branch_id is under test
        o0 = Order.create({"partner_id": p0.id, "branch_id": False,
                           "user_id": False})
        o1 = Order.create({"partner_id": p0.id, "branch_id": b1.id,
                           "user_id": False})
        o2 = Order.create({"partner_id": p0.id, "branch_id": b2.id,
                           "user_id": False})
        ids = set(as_restricted(Order).search([]).ids)
        truthy(o0.id in ids, "an order without branch stays visible")
        truthy(o1.id in ids, "an order of his branch is visible")
        truthy(o2.id not in ids, "an order of another branch is hidden")
    check("T10 the many2one rule still behaves (no branch / mine / theirs)",
          t10)

except Exception:  # noqa: BLE001 - never leave the shell in a broken state
    import traceback
    LINES.append("FATAL " + traceback.format_exc())
    FAIL += 1
finally:
    print("\n".join([""] + LINES))
    print("\n==== PHASE 11: %d PASS / %d FAIL ====" % (PASS, FAIL))
    env.cr.rollback()
