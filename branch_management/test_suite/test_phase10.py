# -*- coding: utf-8 -*-
"""Phase 10 runtime tests: branches on the contacts (res.partner).

Run with:  odoo shell -d balance_mod ... < test_phase10.py
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

    main_company = env.ref("base.main_company")
    g_user = env.ref("base.group_user")
    g_bu = env.ref("branch_management.group_branch_user")
    g_partner_manager = env.ref("base.group_partner_manager")

    b1 = Branch.create({"name": "Phase10 Branch A", "code": "P10A",
                        "company_id": main_company.id})
    b2 = Branch.create({"name": "Phase10 Branch B", "code": "P10B",
                        "company_id": main_company.id})
    b3 = Branch.create({"name": "Phase10 Branch C", "code": "P10C",
                        "company_id": main_company.id})

    restricted = Users.create({
        "name": "Phase10 Restricted", "login": "p10_restricted",
        "group_ids": [(6, 0, [g_user.id, g_bu.id])],
        "branch_ids": [(6, 0, [b1.id])],
        "default_branch_id": b1.id,
    })

    contact = Partner.create({"name": "Phase10 Contact"})

    # ------------------------------------------------------------------
    # T1 - the field itself
    # ------------------------------------------------------------------
    def t1():
        field = Partner._fields.get("branch_ids")
        truthy(field, "res.partner.branch_ids missing")
        eq(field.type, "many2many")
        eq(field.comodel_name, "branch.branch")
        eq(field.relation, "res_partner_branch_rel")
        eq(field.column1, "partner_id")
        eq(field.column2, "branch_id")
        truthy(not field.readonly, "the field must be editable")
        truthy(not field.required, "the field must stay optional")
        truthy(callable(field.domain), "the domain follows the user")
    check("T1 branch_ids on the contact", t1)

    # ------------------------------------------------------------------
    # T2 - several branches on the same contact
    # ------------------------------------------------------------------
    def t2():
        contact.write({"branch_ids": [(6, 0, [b1.id, b2.id])]})
        eq(set(contact.branch_ids.ids), {b1.id, b2.id}, "two branches kept")
        # the field is a real many2many: adding and removing changes nothing
        # else on the contact
        contact.write({"branch_ids": [(6, 0, [b1.id, b3.id])]})
        eq(set(contact.branch_ids.ids), {b1.id, b3.id}, "replaced by two others")
        contact.write({"branch_ids": [(5, 0, 0)]})
        truthy(not contact.branch_ids, "the branches can be removed")
    check("T2 a contact can hold several branches", t2)

    # ------------------------------------------------------------------
    # T3 - the domain only offers the branches of the user
    # ------------------------------------------------------------------
    def t3():
        field = Partner._fields["branch_ids"]
        domain = field._description_domain(env)
        truthy(domain, "no domain returned")
        # the domain is a list of leaves; find the ('id', 'in', ...) one
        ids = [leaf[2] for leaf in domain
               if isinstance(leaf, (list, tuple)) and len(leaf) == 3
               and leaf[0] == "id" and leaf[1] == "in"]
        eq(len(ids), 1, "one ('id', 'in', ...) leaf")
        eq(sorted(ids[0]), sorted(
            env.user.with_context(active_test=False).branch_visible_ids.ids),
           "the branches of the current user")
        truthy({b1.id, b2.id, b3.id} <= set(ids[0]),
               "a user that is not restricted gets every branch")
        # a Branch User only gets their own branch in the dropdown
        domain_restricted = field._description_domain(
            Partner.with_user(restricted).with_context(active_test=False).env)
        ids_restricted = [leaf[2] for leaf in domain_restricted
                          if isinstance(leaf, (list, tuple)) and len(leaf) == 3
                          and leaf[0] == "id" and leaf[1] == "in"]
        eq(sorted(ids_restricted[0]), [b1.id],
           "a restricted user only gets their branch")
    check("T3 the dropdown only shows the visible branches", t3)

    # ------------------------------------------------------------------
    # T4 - the contact form
    # ------------------------------------------------------------------
    def t4():
        form = env.ref("base.view_partner_form").get_combined_arch()
        truthy('name="branch_ids"' in form, "no branch on the contact form")
        truthy('widget="many2many_tags"' in form,
               "the branches must be selectable as tags")
        # placed after the Tags field, in the same column
        pos_tag = form.index('name="category_id"')
        pos_branch = form.index('name="branch_ids"')
        truthy(pos_branch > pos_tag, "the branches come after the tags")
    check("T4 the contact form shows the branches", t4)

    # ------------------------------------------------------------------
    # T5 - the contacts list
    # ------------------------------------------------------------------
    def t5():
        tree = env.ref("base.view_partner_tree").get_combined_arch()
        truthy('name="branch_ids"' in tree, "no branch column in the list")
        truthy('optional="hide"' in tree, "the column must be optional")
    check("T5 the contacts list has an optional branch column", t5)

    # ------------------------------------------------------------------
    # T6 - the contacts search
    # ------------------------------------------------------------------
    def t6():
        search = env.ref("base.view_res_partner_filter").get_combined_arch()
        truthy('name="branch_ids"' in search, "no branch in the search")
        truthy('groupby_branches' in search, "no branch group by")
        truthy("'group_by': 'branch_ids'" in search, "group by the branches")
    check("T6 the contacts search filters and groups by branch", t6)

    # ------------------------------------------------------------------
    # T7 - the permission field of the users is untouched
    # ------------------------------------------------------------------
    def t7():
        # res.users inherits res.partner, but a field redefined locally wins:
        # the "Branches" of a user must stay their allowed branches.
        field = Users._fields["branch_ids"]
        truthy(not field.inherited,
               "res.users.branch_ids must be the local field, not the contact one")
        eq(field.relation, "res_users_branch_rel")
        eq(field.column1, "user_id")
        eq(set(restricted.branch_ids.ids), {b1.id},
           "the restricted user keeps only their branch")
        eq(sorted(restricted.branch_visible_ids.ids), [b1.id],
           "the visibility of the branches is unchanged")
    check("T7 the branches of a user are still their permissions", t7)

    # ------------------------------------------------------------------
    # T8 - a contact of a company keeps its own branches
    # ------------------------------------------------------------------
    def t8():
        company = Partner.create({"name": "Phase10 Company", "is_company": True,
                                  "branch_ids": [(6, 0, [b1.id, b2.id])]})
        child = Partner.create({"name": "Phase10 Contact of the company",
                                "parent_id": company.id,
                                "type": "contact",
                                "branch_ids": [(6, 0, [b3.id])]})
        eq(set(company.branch_ids.ids), {b1.id, b2.id}, "branches of the company")
        eq(set(child.branch_ids.ids), {b3.id}, "own branches of the contact")
        # reading them back after the fact, as the UI does
        read = Partner.browse(child.id).read(["branch_ids"])[0]
        eq(set(read["branch_ids"]), {b3.id}, "read back the branches")
    check("T8 a company and its contact keep their own branches", t8)

    # ------------------------------------------------------------------
    # T9 - a user that is not a "Branch User" can use the field too
    # ------------------------------------------------------------------
    def t9():
        plain = Users.create({
            "name": "Phase10 Plain", "login": "p10_plain",
            "group_ids": [(6, 0, [g_user.id, g_partner_manager.id])],
        })
        field = Partner._fields["branch_ids"]
        domain = field._description_domain(
            Partner.with_user(plain).with_context(active_test=False).env)
        ids = [leaf[2] for leaf in domain
               if isinstance(leaf, (list, tuple)) and len(leaf) == 3
               and leaf[0] == "id" and leaf[1] == "in"]
        truthy({b1.id, b2.id, b3.id} <= set(ids[0]),
               "a user that is not restricted gets every branch")
        # and such a user really edits the branches of a contact
        Partner.with_user(plain).browse(contact.id).write(
            {"branch_ids": [(6, 0, [b2.id, b3.id])]})
        eq(set(Partner.browse(contact.id).branch_ids.ids), {b2.id, b3.id},
           "a plain user can edit the branches of a contact")
    check("T9 a user that is not a Branch User can use the field", t9)

except Exception:  # noqa: BLE001 - never leave the shell in a broken state
    import traceback
    LINES.append("FATAL " + traceback.format_exc())
    FAIL += 1
finally:
    print("\n".join([""] + LINES))
    print("\n==== PHASE 10: %d PASS / %d FAIL ====" % (PASS, FAIL))
    env.cr.rollback()
