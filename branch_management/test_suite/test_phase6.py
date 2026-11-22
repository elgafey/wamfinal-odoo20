# -*- coding: utf-8 -*-
"""Phase 6 runtime tests: accounting, analytic distribution, settings.

Run with:  odoo shell -d balance_mod ... < test_phase6.py
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
    Order = env["sale.order"]
    Users = env["res.users"]
    Move = env["account.move"]
    MoveLine = env["account.move.line"]
    AnalyticLine = env["account.analytic.line"]
    Settings = env["res.config.settings"]

    main_company = env.ref("base.main_company")
    g_user = env.ref("base.group_user")
    g_bu = env.ref("branch_management.group_branch_user")
    g_salesman = env.ref("sales_team.group_sale_salesman")
    g_invoice = env.ref("account.group_account_invoice")
    g_analytic = env.ref("analytic.group_analytic_accounting")
    branches_plan = env.ref("branch_management.analytic_plan_branches")

    journal = env["account.journal"].search([("type", "=", "sale")], limit=1)
    income = env["account.account"].search(
        [("account_type", "in", ("income", "income_other"))], limit=1)
    receivable = env["account.account"].search(
        [("account_type", "=", "asset_receivable")], limit=1)
    truthy(journal, "no sales journal")
    truthy(income, "no income account")
    truthy(receivable, "no receivable account")

    # ------------------------------------------------------------------
    # fixtures
    # ------------------------------------------------------------------
    other_plan = env["account.analytic.plan"].create({"name": "P6 Projects"})
    project_account = env["account.analytic.account"].create(
        {"name": "P6 Project", "plan_id": other_plan.id,
         "company_id": main_company.id})
    pool_account = env["account.analytic.account"].create(
        {"name": "P6 Pool", "plan_id": branches_plan.id,
         "company_id": main_company.id})

    partner = env["res.partner"].create({"name": "Phase6 Customer"})
    partner.write({"property_account_receivable_id": receivable.id})
    product = env["product.product"].create({
        "name": "Phase6 Product", "list_price": 100.0,
        "invoice_policy": "order",
        "property_account_income_id": income.id})

    b1 = Branch.create({"name": "Phase6 Branch A", "code": "P6A",
                        "company_id": main_company.id})
    b2 = Branch.create({"name": "Phase6 Branch B", "code": "P6B",
                        "company_id": main_company.id})
    b3 = Branch.create({"name": "Phase6 Branch C", "code": "P6C",
                        "company_id": main_company.id,
                        "auto_create_analytic": False})
    truthy(b1.analytic_account_id, "b1 has no analytic account")
    truthy(b2.analytic_account_id, "b2 has no analytic account")
    truthy(not b3.analytic_account_id, "b3 must have no analytic account")

    restricted = Users.create({
        "name": "Phase6 Restricted", "login": "p6_restricted",
        "group_ids": [(6, 0, [g_user.id, g_bu.id, g_salesman.id,
                              g_invoice.id, g_analytic.id])],
        "branch_ids": [(6, 0, [b1.id])],
        "default_branch_id": b1.id,
    })

    def product_line(move):
        return move.line_ids.filtered(lambda l: l.display_type == "product")[:1]

    def make_move(branch=None, line_vals=None):
        line = {"display_type": "product", "name": "Phase6 line",
                "quantity": 1, "price_unit": 100.0,
                "account_id": income.id, "product_id": product.id}
        if line_vals:
            line.update(line_vals)
        vals = {"move_type": "out_invoice", "partner_id": partner.id,
                "journal_id": journal.id, "line_ids": [(0, 0, line)]}
        if branch:
            vals["branch_id"] = branch.id
        return Move.create(vals)

    def order_line(qty=1):
        return [(0, 0, {"product_id": product.id,
                        "product_uom_qty": qty, "price_unit": 100.0})]

    # ------------------------------------------------------------------
    # T1 - the three fields
    # ------------------------------------------------------------------
    def t1():
        move_field = Move._fields.get("branch_id")
        truthy(move_field, "account.move.branch_id missing")
        eq(move_field.comodel_name, "branch.branch")
        truthy(move_field.index, "branch_id must be indexed")
        truthy(move_field.check_company, "branch_id must be company checked")
        truthy(move_field.tracking, "branch_id must be tracked")
        truthy(move_field.copy, "the credit note must keep the branch")

        line_field = MoveLine._fields.get("branch_id")
        truthy(line_field, "account.move.line.branch_id missing")
        eq(line_field.related, "move_id.branch_id", "line follows the entry")
        truthy(line_field.store, "the branch of the line must be stored")
        truthy(line_field.readonly, "the branch of the line must be readonly")

        al_field = AnalyticLine._fields.get("branch_id")
        truthy(al_field, "account.analytic.line.branch_id missing")
        eq(al_field.related, "move_line_id.branch_id", "analytic line follows")
        truthy(al_field.store and al_field.readonly, "stored and readonly")
    check("T1 branch on entry, journal item and analytic entry", t1)

    # ------------------------------------------------------------------
    # T2 - invoice created from the order
    # ------------------------------------------------------------------
    def t2():
        so = Order.create({"partner_id": partner.id, "branch_id": b1.id,
                           "user_id": False, "order_line": order_line(2)})
        so.action_confirm()
        invoices = so._create_invoices()
        truthy(invoices, "no invoice created")
        eq(set(invoices.mapped("branch_id").ids), {b1.id}, "invoice branch")
    check("T2 invoice from the order keeps the branch", t2)

    # ------------------------------------------------------------------
    # T3 - down payment
    # ------------------------------------------------------------------
    def t3():
        so = Order.create({"partner_id": partner.id, "branch_id": b1.id,
                           "user_id": False, "order_line": order_line(1)})
        so.action_confirm()
        before = set(Move.search([]).ids)
        wiz = env["sale.advance.payment.inv"].create({
            "advance_payment_method": "fixed",
            "fixed_amount": 50.0,
            "sale_order_ids": [(6, 0, [so.id])],
        })
        wiz.create_invoices()
        new_moves = Move.search([("id", "not in", list(before))])
        truthy(new_moves, "no down payment invoice created")
        eq(set(new_moves.mapped("branch_id").ids), {b1.id},
           "down payment branch")
    check("T3 down payment keeps the branch", t3)

    # ------------------------------------------------------------------
    # T4 - credit note
    # ------------------------------------------------------------------
    def t4():
        move = make_move(b1)
        move.action_post()
        refund = move._reverse_moves()
        truthy(refund, "no credit note created")
        eq(set(refund.mapped("branch_id").ids), {b1.id}, "credit note branch")
    check("T4 credit note keeps the branch", t4)

    # ------------------------------------------------------------------
    # T5 - the journal items follow the entry
    # ------------------------------------------------------------------
    def t5():
        move = make_move(b1)
        line = product_line(move)
        eq(line.branch_id, b1, "line branch from the entry")
        move.write({"branch_id": b2.id})
        eq(line.branch_id, b2, "line branch follows the entry")
        move.write({"branch_id": b1.id})
        eq(line.branch_id, b1, "line branch follows back")
    check("T5 journal items follow the branch of the entry", t5)

    # ------------------------------------------------------------------
    # T6 - analytic entries
    # ------------------------------------------------------------------
    def t6():
        move = make_move(b1)
        move.action_post()
        entries = AnalyticLine.search(
            [("move_line_id", "in", move.line_ids.ids)])
        truthy(entries, "no analytic entry created on post")
        eq(set(entries.mapped("branch_id").ids), {b1.id},
           "analytic entry branch")
    check("T6 analytic entries keep the branch", t6)

    # ------------------------------------------------------------------
    # T7a - empty distribution
    # ------------------------------------------------------------------
    def t7a():
        move = make_move(b1)
        eq(product_line(move).analytic_distribution,
           {str(b1.analytic_account_id.id): 100.0},
           "the account of the branch at 100%")
    check("T7a the branch account is applied to an empty distribution", t7a)

    # ------------------------------------------------------------------
    # T7b - merged with another plan
    # ------------------------------------------------------------------
    def t7b():
        move = make_move(b1, {"analytic_distribution":
                              {str(project_account.id): 100.0}})
        dist = product_line(move).analytic_distribution
        eq(len(dist), 1, "one single key")
        key = list(dist)[0]
        eq({int(v) for v in key.split(",")},
           {project_account.id, b1.analytic_account_id.id},
           "both accounts in the key")
        eq(dist[key], 100.0, "percentage unchanged")
    check("T7b the branch account is merged with another plan", t7b)

    # ------------------------------------------------------------------
    # T7c - switch of the company
    # ------------------------------------------------------------------
    def t7c():
        main_company.branch_analytic_auto = False
        try:
            move = make_move(b1, {"analytic_distribution":
                                  {str(project_account.id): 100.0}})
            eq(product_line(move).analytic_distribution,
               {str(project_account.id): 100.0},
               "distribution untouched while the switch is off")
            move2 = make_move(b1)
            truthy(not product_line(move2).analytic_distribution,
                   "no branch account while the switch is off")
        finally:
            main_company.branch_analytic_auto = True
    check("T7c the switch of the company stops the merge", t7c)

    # ------------------------------------------------------------------
    # T7d - branch without analytic account
    # ------------------------------------------------------------------
    def t7d():
        move = make_move(b3)
        truthy(not product_line(move).analytic_distribution,
               "b3 has no analytic account: nothing applied")
        move2 = make_move(b3, {"analytic_distribution":
                               {str(project_account.id): 100.0}})
        eq(product_line(move2).analytic_distribution,
           {str(project_account.id): 100.0},
           "distribution untouched")
    check("T7d a branch without analytic account changes nothing", t7d)

    # ------------------------------------------------------------------
    # T7e - entry without branch
    # ------------------------------------------------------------------
    def t7e():
        move = make_move(None)
        truthy(not product_line(move).analytic_distribution,
               "no branch, no analytic account")
    check("T7e an entry without branch is untouched", t7e)

    # ------------------------------------------------------------------
    # T7f - every line that carries an account
    # ------------------------------------------------------------------
    def t7f():
        move = make_move(b1)
        acc = str(b1.analytic_account_id.id)
        terms = move.line_ids.filtered(
            lambda l: l.display_type == "payment_term")
        truthy(terms, "payment term line missing")
        with_account = move.line_ids.filtered(lambda l: l.account_id)
        truthy(with_account, "no line of the entry carries an account")
        for line in with_account:
            eq(line.analytic_distribution, {acc: 100.0},
               "line %s (%s) must carry the branch" % (line.id, line.display_type))
        # the lines without an account (section, note) cannot carry anything
        for line in move.line_ids - with_account:
            truthy(not line.analytic_distribution,
                   "line %s has no account: it must stay empty" % line.id)
    check("T7f every line with an account carries the branch", t7f)

    # ------------------------------------------------------------------
    # T7g - already merged
    # ------------------------------------------------------------------
    def t7g():
        move = make_move(b1, {"analytic_distribution":
                              {str(b1.analytic_account_id.id): 100.0}})
        eq(product_line(move).analytic_distribution,
           {str(b1.analytic_account_id.id): 100.0},
           "already merged: untouched")
    check("T7g an already merged distribution is left alone", t7g)

    # ------------------------------------------------------------------
    # T7h - the account of another branch
    # ------------------------------------------------------------------
    def t7h():
        move = make_move(b1, {"analytic_distribution":
                              {str(b2.analytic_account_id.id): 100.0}})
        eq(product_line(move).analytic_distribution,
           {str(b1.analytic_account_id.id): 100.0},
           "the account of b2 is replaced by the account of b1")
    check("T7h the account of another branch is replaced", t7h)

    # ------------------------------------------------------------------
    # T7i - another account of the same plan
    # ------------------------------------------------------------------
    def t7i():
        move = make_move(b1, {"analytic_distribution":
                              {str(pool_account.id): 100.0}})
        eq(product_line(move).analytic_distribution,
           {str(pool_account.id): 100.0},
           "an account that belongs to no branch is left alone")
    check("T7i an account of the plan that belongs to no branch is left alone",
          t7i)

    # ------------------------------------------------------------------
    # T8 - the three rows of the csv
    # ------------------------------------------------------------------
    def t8():
        for model_name in ("account.move", "account.move.line",
                           "account.analytic.line"):
            row = env["ir.access"].search([
                ("model_id.model", "=", model_name),
                ("group_id", "=", False),
                ("name", "like", "branch")], limit=1)
            truthy(row, "%s: restriction row missing" % model_name)
            truthy(row.operation == "crud",
                   "%s: the row must allow every operation, got %r"
                   % (model_name, row.operation))
            truthy(row.for_read and row.for_write and row.for_create
                   and row.for_unlink,
                   "%s: the four operations must be on" % model_name)
            truthy("branch_id" in (row.domain or ""),
                   "%s: the domain must filter on branch_id" % model_name)
    check("T8 the three restriction rows exist", t8)

    # ------------------------------------------------------------------
    # T9 - visibility
    # ------------------------------------------------------------------
    def t9():
        own = make_move(b1)
        other = make_move(b2)
        legacy = make_move(None)

        expected = {m.id for m in Move.search([])
                    if not m.branch_id or m.branch_id == b1}
        eq(set(Move.with_user(restricted).search([]).ids), expected,
           "moves visible to the restricted user")
        with expect(AccessError):
            Move.with_user(restricted).browse(other.id).read(["name"])
        truthy(Move.with_user(restricted).browse(own.id).read(["name"]),
               "he reads his own entry")
        truthy(Move.with_user(restricted).browse(legacy.id).read(["name"]),
               "he reads the entries without branch")

        expected_lines = {l.id for l in MoveLine.search([])
                          if not l.branch_id or l.branch_id == b1}
        eq(set(MoveLine.with_user(restricted).search([]).ids),
           expected_lines, "journal items visible to the restricted user")
        with expect(AccessError):
            MoveLine.with_user(restricted).browse(
                other.line_ids[0].id).read(["id"])
        truthy(MoveLine.with_user(restricted).browse(
            own.line_ids[0].id).read(["id"]), "he reads his own journal item")

        # analytic entries
        for move in (own, other):
            move.action_post()
        legacy_entry = AnalyticLine.create({
            "name": "Phase6 legacy analytic", "amount": 10.0,
            "account_id": project_account.id})
        truthy(not legacy_entry.branch_id,
               "an analytic entry without journal item has no branch")

        expected_entries = {al.id for al in AnalyticLine.search([])
                            if not al.branch_id or al.branch_id == b1}
        eq(set(AnalyticLine.with_user(restricted).search([]).ids),
           expected_entries, "analytic entries visible to the restricted user")
        other_entry = AnalyticLine.search(
            [("move_line_id", "in", other.line_ids.ids)], limit=1)
        truthy(other_entry, "no analytic entry for the other branch")
        with expect(AccessError):
            AnalyticLine.with_user(restricted).browse(
                other_entry.id).read(["name"])
        truthy(AnalyticLine.with_user(restricted).browse(
            legacy_entry.id).read(["name"]),
            "he reads the analytic entries without branch")
    check("T9 visibility of entries, items and analytic entries", t9)

    # ------------------------------------------------------------------
    # T10 - the restricted user creates an invoice
    # ------------------------------------------------------------------
    def t10():
        with expect(AccessError):
            Move.with_user(restricted).create({
                "move_type": "out_invoice", "partner_id": partner.id,
                "journal_id": journal.id, "branch_id": b2.id})
        created = Move.with_user(restricted).create({
            "move_type": "out_invoice", "partner_id": partner.id,
            "journal_id": journal.id, "branch_id": b1.id})
        eq(created.branch_id, b1, "his own branch is accepted")
        eq(created.branch_id.company_id, main_company)
    check("T10 the restricted user creates an invoice of his branch", t10)

    # ------------------------------------------------------------------
    # T11 - settings
    # ------------------------------------------------------------------
    def t11():
        truthy("branch_analytic_auto" in Settings._fields,
               "branch_analytic_auto missing on res.config.settings")
        truthy("branch_warehouse_exclusive" in Settings._fields,
               "branch_warehouse_exclusive missing on res.config.settings")
        combined = env.ref("base.res_config_settings_view_form").get_combined_arch()
        truthy('name="branch_analytic_auto"' in combined, "settings view 1")
        truthy('name="branch_warehouse_exclusive"' in combined, "settings view 2")
        Settings.create({"branch_analytic_auto": False,
                         "branch_warehouse_exclusive": False})
        truthy(not main_company.branch_analytic_auto,
               "the first switch is written to the company")
        truthy(not main_company.branch_warehouse_exclusive,
               "the second switch is written to the company")
        Settings.create({"branch_analytic_auto": True,
                         "branch_warehouse_exclusive": True})
        truthy(main_company.branch_analytic_auto, "the first switch restored")
        truthy(main_company.branch_warehouse_exclusive,
               "the second switch restored")
    check("T11 settings page and its two switches", t11)

    # ------------------------------------------------------------------
    # T12 - views
    # ------------------------------------------------------------------
    def t12():
        combined = env.ref("account.view_move_form").get_combined_arch()
        truthy('name="branch_id"' in combined, "invoice form")
        combined = env.ref("account.view_move_tree").get_combined_arch()
        truthy('name="branch_id"' in combined, "journal entries list")
        truthy(env.ref("branch_management.account_move_form_branch"),
               "our form view is missing")
        truthy(env.ref("branch_management.account_move_tree_branch"),
               "our list view is missing")
    check("T12 invoice form and journal entries list", t12)

except Exception:  # noqa: BLE001 - never leave the shell in a broken state
    import traceback
    LINES.append("FATAL " + traceback.format_exc())
    FAIL += 1
finally:
    print("\n".join([""] + LINES))
    print("\n==== PHASE 6: %d PASS / %d FAIL ====" % (PASS, FAIL))
    env.cr.rollback()
