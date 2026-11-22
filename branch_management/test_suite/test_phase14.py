# -*- coding: utf-8 -*-
"""Phase 14 tests: the branch analytic account on every journal item.

Until this phase only *some* journal items received the analytic account of
the branch: the product lines of an invoice, and outside an invoice the lines
of income and expense.  A journal entry whose branch is known now carries that
account on **every** line that has an account - receivable, payable, taxes,
payment terms, bank - and so does every analytic item made from them.

It also fixes the two gaps that went with that rule:

* an entry posted *before* its branch was set created no analytic item at
  all: Odoo recomputes the distribution when the branch changes, but a
  recomputation does not call ``_inverse_analytic_distribution``, the core
  method that builds the analytic items;
* an entry whose branch was replaced or removed kept the analytic items of
  the previous branch.

Run with:  odoo shell -d balance_mod ... < test_phase14.py
The whole script runs in one transaction and rolls it back at the end.
"""
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


try:
    Branch = env["branch.branch"]
    Move = env["account.move"]
    MoveLine = env["account.move.line"]
    AnalyticLine = env["account.analytic.line"]

    company = env.ref("base.main_company")
    sale_journal = env["account.journal"].search([("type", "=", "sale")], limit=1)
    misc_journal = env["account.journal"].search(
        [("type", "=", "general")], limit=1) or sale_journal
    bank_journal = env["account.journal"].search([("type", "=", "bank")], limit=1)
    income = env["account.account"].search(
        [("account_type", "in", ("income", "income_other"))], limit=1)
    receivable = env["account.account"].search(
        [("account_type", "=", "asset_receivable")], limit=1)
    cash = env["account.account"].search(
        [("account_type", "=", "asset_cash")], limit=1)
    truthy(sale_journal and income and receivable, "missing journal or accounts")
    truthy(bank_journal and cash, "no bank journal: the payment test needs one")

    partner = env["res.partner"].create({"name": "Phase14 Customer"})
    partner.write({"property_account_receivable_id": receivable.id})
    product = env["product.product"].create({
        "name": "Phase14 Product", "list_price": 100.0,
        "invoice_policy": "order", "property_account_income_id": income.id})

    b1 = Branch.create({"name": "Phase14 Branch A", "code": "P14A",
                        "company_id": company.id})
    b2 = Branch.create({"name": "Phase14 Branch B", "code": "P14B",
                        "company_id": company.id})
    b3 = Branch.create({"name": "Phase14 Branch C", "code": "P14C",
                        "company_id": company.id, "auto_create_analytic": False})
    A1, A2 = str(b1.analytic_account_id.id), str(b2.analytic_account_id.id)
    truthy(A1 and A2, "both branches need an analytic account")
    truthy(not b3.analytic_account_id, "b3 must have no analytic account")

    other_plan = env["account.analytic.plan"].create({"name": "P14 Projects"})
    project = env["account.analytic.account"].create(
        {"name": "P14 Project", "plan_id": other_plan.id,
         "company_id": company.id})

    def make_invoice(branch, line_vals=None, section=False):
        line = {"display_type": "product", "name": "Phase14 line",
                "quantity": 1, "price_unit": 100.0,
                "account_id": income.id, "product_id": product.id}
        if line_vals:
            line.update(line_vals)
        commands = [(0, 0, line)]
        if section:
            commands.append((0, 0, {"display_type": "line_section",
                                    "name": "Phase14 Section"}))
        vals = {"move_type": "out_invoice", "partner_id": partner.id,
                "journal_id": sale_journal.id, "line_ids": commands}
        if branch:
            vals["branch_id"] = branch.id
        return Move.create(vals)

    def with_account(move):
        return move.line_ids.filtered(lambda l: l.account_id)

    def items(move):
        return AnalyticLine.search([("move_line_id", "in", move.line_ids.ids)])

    # ------------------------------------------------------------------
    # T1 - every line of a branced invoice carries the branch
    # ------------------------------------------------------------------
    def t1():
        move = make_invoice(b1)
        lines = with_account(move)
        truthy(len(lines) >= 2, "an invoice has at least two lines with an account")
        types = set(lines.mapped("display_type"))
        truthy("product" in types, "the income line is missing")
        truthy("payment_term" in types, "the receivable line is missing")
        for line in lines:
            eq(line.analytic_distribution, {A1: 100.0},
               "line %s (%s)" % (line.id, line.display_type))
    check("T1 every line of the invoice carries the branch", t1)

    # ------------------------------------------------------------------
    # T2 - a line without an account cannot carry anything
    # ------------------------------------------------------------------
    def t2():
        move = make_invoice(b1, section=True)
        sections = move.line_ids.filtered(
            lambda l: l.display_type == "line_section")
        truthy(sections, "the section line was not created")
        for line in sections:
            truthy(not line.account_id, "a section has no account")
            truthy(not line.analytic_distribution,
                   "a line without an account must stay empty")
        for line in with_account(move):
            eq(line.analytic_distribution, {A1: 100.0},
               "the lines with an account are not touched by the section")
    check("T2 a line without an account stays empty", t2)

    # ------------------------------------------------------------------
    # T3 - posting creates one analytic item per line, all with the branch
    # ------------------------------------------------------------------
    def t3():
        move = make_invoice(b1)
        move.action_post()
        lines = with_account(move)
        entries = items(move)
        truthy(entries, "no analytic item was created on post")
        eq({entry.move_line_id.id for entry in entries}, set(lines.ids),
           "one analytic item per line that carries a distribution")
        eq(set(entries.mapped("branch_id").ids), {b1.id},
           "every analytic item keeps the branch")
        for line in lines:
            eq(line.branch_id, b1, "the branch of the journal item")
    check("T3 post creates an analytic item per line, all with the branch", t3)

    # ------------------------------------------------------------------
    # T4 - THE FIX: an entry that receives its branch after being posted
    # ------------------------------------------------------------------
    def t4():
        move = make_invoice(None)
        move.action_post()
        truthy(not items(move), "an entry without branch builds no analytic item")
        for line in with_account(move):
            truthy(not line.analytic_distribution,
                   "no branch: no branch account on the journal items")

        move.write({"branch_id": b1.id})
        env.flush_all()
        lines = with_account(move)
        for line in lines:
            eq(line.analytic_distribution, {A1: 100.0},
               "the distribution of line %s" % line.id)
        entries = items(move)
        truthy(entries, "the analytic items were never built: this was the gap")
        eq({entry.move_line_id.id for entry in entries}, set(lines.ids),
           "one analytic item per line after the branch was given")
        eq(set(entries.mapped("branch_id").ids), {b1.id}, "their branch")
    check("T4 an entry posted first, given a branch later, is completed", t4)

    # ------------------------------------------------------------------
    # T5 - changing the branch rebuilds the analytic items
    # ------------------------------------------------------------------
    def t5():
        move = make_invoice(b1)
        move.action_post()
        move.write({"branch_id": b2.id})
        env.flush_all()
        for line in with_account(move):
            eq(line.analytic_distribution, {A2: 100.0},
               "the account of the previous branch must be gone")
        entries = items(move)
        truthy(entries, "the analytic items disappeared on the branch change")
        eq({entry.move_line_id.id for entry in entries},
           set(with_account(move).ids), "one analytic item per line")
        eq(set(entries.mapped("branch_id").ids), {b2.id},
           "every analytic item moved to the new branch")
        eq(set(entries._get_analytic_accounts().ids),
           {b2.analytic_account_id.id},
           "the analytic items use the account of the new branch")
    check("T5 changing the branch rebuilds the analytic items", t5)

    # ------------------------------------------------------------------
    # T6 - removing the branch removes the account and the analytic items
    # ------------------------------------------------------------------
    def t6():
        move = make_invoice(b1)
        move.action_post()
        truthy(items(move), "the fixture must start with analytic items")
        move.write({"branch_id": False})
        env.flush_all()
        for line in with_account(move):
            truthy(not line.analytic_distribution,
                   "the branch account must be dropped, got %r"
                   % line.analytic_distribution)
        truthy(not items(move),
               "the analytic items of a branchless entry must be gone")
    check("T6 removing the branch drops the account and the analytic items", t6)

    # ------------------------------------------------------------------
    # T7 - a miscellaneous entry: both lines carry it
    # ------------------------------------------------------------------
    def t7():
        move = Move.create({
            "move_type": "entry", "journal_id": misc_journal.id,
            "branch_id": b1.id,
            "line_ids": [
                (0, 0, {"name": "Phase14 income", "account_id": income.id,
                        "credit": 100.0, "debit": 0.0}),
                (0, 0, {"name": "Phase14 cash", "account_id": cash.id,
                        "debit": 100.0, "credit": 0.0}),
            ],
        })
        lines = with_account(move)
        truthy(len(lines) == 2, "the two lines of the entry")
        for line in lines:
            eq(line.analytic_distribution, {A1: 100.0},
               "line %s" % line.account_id.code)
        move.action_post()
        entries = items(move)
        eq({entry.move_line_id.id for entry in entries}, set(lines.ids),
           "the bank line builds an analytic item too")
        eq(set(entries.mapped("branch_id").ids), {b1.id}, "their branch")
    check("T7 a miscellaneous entry carries it on both lines", t7)

    # ------------------------------------------------------------------
    # T8 - the entry of a payment carries it
    # ------------------------------------------------------------------
    def t8():
        payment = env["account.payment"].create({
            "payment_type": "inbound", "partner_type": "customer",
            "partner_id": partner.id, "amount": 100.0,
            "journal_id": bank_journal.id, "branch_id": b1.id})
        payment.action_post()
        move = payment.move_id
        truthy(move, "the payment was not posted")
        eq(move.branch_id, b1, "the entry of the payment keeps the branch")
        lines = with_account(move)
        truthy(len(lines) >= 2, "the entry of a payment has two lines")
        for line in lines:
            eq(line.analytic_distribution, {A1: 100.0},
               "line %s" % line.account_id.code)
        entries = items(move)
        truthy(entries, "the analytic items of the payment were not created")
        eq(set(entries.mapped("branch_id").ids), {b1.id}, "their branch")
    check("T8 the entry of a payment carries it on every line", t8)

    # ------------------------------------------------------------------
    # T9 - the backfill of the entries that already existed
    # ------------------------------------------------------------------
    def t9():
        move = make_invoice(b1)
        move.action_post()
        truthy(items(move), "the fixture must start with analytic items")
        # pretend the entry was written before the branch ever existed
        for line in with_account(move):
            line.write({"analytic_distribution": False})
        env.flush_all()
        for line in with_account(move):
            truthy(not line.analytic_distribution, "the fixture was not stripped")
        truthy(not items(move), "the analytic items must be gone as well")

        MoveLine.search([("id", "in", move.line_ids.ids)])._reapply_branch_analytic()
        env.flush_all()
        lines = with_account(move)
        for line in lines:
            eq(line.analytic_distribution, {A1: 100.0},
               "the backfill restored line %s" % line.id)
        entries = items(move)
        eq({entry.move_line_id.id for entry in entries}, set(lines.ids),
           "the backfill rebuilt one analytic item per line")
        eq(set(entries.mapped("branch_id").ids), {b1.id}, "their branch")
    check("T9 _reapply_branch_analytic() backfills an existing entry", t9)

    # ------------------------------------------------------------------
    # T10 - the three cases where nothing happens
    # ------------------------------------------------------------------
    def t10():
        no_branch = make_invoice(None)
        for line in with_account(no_branch):
            truthy(not line.analytic_distribution, "no branch, no account")

        no_account = make_invoice(b3)
        for line in with_account(no_account):
            truthy(not line.analytic_distribution,
                   "a branch without analytic account gives nothing")

        company.branch_analytic_auto = False
        env.flush_all()
        switched_off = make_invoice(b1)
        for line in with_account(switched_off):
            truthy(not line.analytic_distribution, "the switch is off")
        company.branch_analytic_auto = True
        env.flush_all()
        truthy(company.branch_analytic_auto, "the switch must be back on")
    check("T10 no branch / no analytic account / switch off: nothing", t10)

    # ------------------------------------------------------------------
    # T11 - a branchless entry never keeps a branch account
    # ------------------------------------------------------------------
    def t11():
        move = Move.create({
            "move_type": "entry", "journal_id": misc_journal.id,
            "line_ids": [
                (0, 0, {"name": "Phase14 kept", "account_id": income.id,
                        "credit": 100.0, "debit": 0.0,
                        "analytic_distribution": {A1: 100.0}}),
                (0, 0, {"name": "Phase14 other", "account_id": cash.id,
                        "debit": 100.0, "credit": 0.0}),
            ],
        })
        for line in with_account(move):
            truthy(not line.analytic_distribution,
                   "an entry with no branch must not keep a branch account, "
                   "got %r" % line.analytic_distribution)
        # an account of the branch plan that belongs to no branch is the
        # user's own: it is not ours to remove
        pool = env["account.analytic.account"].create(
            {"name": "P14 Pool", "plan_id": env.ref(
                "branch_management.analytic_plan_branches").id,
             "company_id": company.id})
        move2 = Move.create({
            "move_type": "entry", "journal_id": misc_journal.id,
            "line_ids": [
                (0, 0, {"name": "Phase14 pool", "account_id": income.id,
                        "credit": 100.0, "debit": 0.0,
                        "analytic_distribution": {str(pool.id): 100.0}}),
                (0, 0, {"name": "Phase14 other", "account_id": cash.id,
                        "debit": 100.0, "credit": 0.0}),
            ],
        })
        eq(move2.line_ids.filtered(lambda l: l.account_id == income).analytic_distribution,
           {str(pool.id): 100.0},
           "an analytic account owned by no branch is left alone")
    check("T11 a branchless entry never keeps a branch account", t11)

    # ------------------------------------------------------------------
    # T12 - another plan survives a change of branch
    # ------------------------------------------------------------------
    def t12():
        move = make_invoice(b1, {"analytic_distribution": {str(project.id): 100.0}})
        line = with_account(move).filtered(
            lambda l: l.display_type == "product")
        dist = line.analytic_distribution
        eq(len(dist), 1, "one single key")
        eq({int(v) for v in list(dist)[0].split(",")},
           {project.id, b1.analytic_account_id.id},
           "the branch account was added to the key of the project")

        move.action_post()
        move.write({"branch_id": b2.id})
        env.flush_all()
        dist = line.analytic_distribution
        eq(len(dist), 1, "still one single key after the change")
        eq({int(v) for v in list(dist)[0].split(",")},
           {project.id, b2.analytic_account_id.id},
           "the account of the old branch was replaced by the new one")
        entries = AnalyticLine.search([("move_line_id", "=", line.id)])
        truthy(entries, "the analytic items of the line disappeared")
        used = set(entries._get_analytic_accounts().ids)
        eq(used, {project.id, b2.analytic_account_id.id},
           "the analytic items use the new branch account")
        truthy(b1.analytic_account_id.id not in used,
               "no analytic item may still use the previous branch")
    check("T12 another analytic plan survives a change of branch", t12)

except Exception:  # noqa: BLE001 - never leave the shell in a broken state
    import traceback
    LINES.append("FATAL " + traceback.format_exc())
    FAIL += 1
finally:
    print("\n".join([""] + LINES))
    print("\n==== PHASE 14: %d PASS / %d FAIL ====" % (PASS, FAIL))
    env.cr.rollback()
