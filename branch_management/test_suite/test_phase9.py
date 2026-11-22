# -*- coding: utf-8 -*-
"""Phase 9 runtime tests: payments (customer and vendor).

Run with:  odoo shell -d balance_mod ... < test_phase9.py
The whole script runs in one transaction and rolls it back at the end.
"""
from contextlib import contextmanager

from odoo import fields
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
    Move = env["account.move"]
    Payment = env["account.payment"]
    Register = env["account.payment.register"]

    main_company = env.ref("base.main_company")
    g_user = env.ref("base.group_user")
    g_bu = env.ref("branch_management.group_branch_user")
    g_invoice = env.ref("account.group_account_invoice")

    sale_journal = env["account.journal"].search([("type", "=", "sale")], limit=1)
    purchase_journal = env["account.journal"].search(
        [("type", "=", "purchase")], limit=1)
    pay_journal = env["account.journal"].search(
        [("type", "in", ("bank", "cash"))], limit=1)
    misc_journal = env["account.journal"].search(
        [("type", "=", "general")], limit=1) or sale_journal
    income = env["account.account"].search(
        [("account_type", "in", ("income", "income_other"))], limit=1)
    expense = env["account.account"].search(
        [("account_type", "in", ("expense", "expense_other"))], limit=1)
    receivable = env["account.account"].search(
        [("account_type", "=", "asset_receivable")], limit=1)
    payable = env["account.account"].search(
        [("account_type", "=", "liability_payable")], limit=1)
    cash = env["account.account"].search(
        [("account_type", "=", "asset_cash")], limit=1)
    truthy(sale_journal, "no sales journal")
    truthy(purchase_journal, "no purchase journal")
    truthy(pay_journal, "no bank/cash journal")
    truthy(income and expense and receivable and payable and cash,
           "missing accounts")

    partner = env["res.partner"].create({"name": "Phase9 Customer"})
    partner.write({"property_account_receivable_id": receivable.id,
                   "property_account_payable_id": payable.id})
    product = env["product.product"].create({
        "name": "Phase9 Product", "list_price": 100.0,
        "invoice_policy": "order", "property_account_income_id": income.id})

    b1 = Branch.create({"name": "Phase9 Branch A", "code": "P9A",
                        "company_id": main_company.id})
    b2 = Branch.create({"name": "Phase9 Branch B", "code": "P9B",
                        "company_id": main_company.id})
    truthy(b1.analytic_account_id, "b1 has no analytic account")
    truthy(b2.analytic_account_id, "b2 has no analytic account")

    restricted = Users.create({
        "name": "Phase9 Restricted", "login": "p9_restricted",
        "group_ids": [(6, 0, [g_user.id, g_bu.id, g_invoice.id])],
        "branch_ids": [(6, 0, [b1.id])],
        "default_branch_id": b1.id,
    })

    # ------------------------------------------------------------------
    # fixtures
    # ------------------------------------------------------------------
    def product_line_vals(account):
        return {"display_type": "product", "name": "Phase9 line",
                "quantity": 1, "price_unit": 100.0,
                "account_id": account.id, "product_id": product.id}

    def make_move(move_type, branch, journal, account):
        """A posted invoice or bill of 100, on ``branch`` when given."""
        vals = {"move_type": move_type, "partner_id": partner.id,
                "journal_id": journal.id,
                "invoice_date": fields.Date.today(),
                "line_ids": [(0, 0, product_line_vals(account))]}
        if branch:
            vals["branch_id"] = branch.id
        move = Move.create(vals)
        move.action_post()
        return move

    def register_payment(move):
        """Run the standard "Register Payment" wizard on ``move``."""
        before = set(Payment.search([]).ids)
        wizard = Register.with_context(
            active_model="account.move", active_ids=[move.id]).create({})
        wizard.action_create_payments()
        created = Payment.search([("id", "not in", list(before))])
        eq(len(created), 1, "one single payment created")
        return wizard, created

    # ------------------------------------------------------------------
    # T1 - the two new fields
    # ------------------------------------------------------------------
    def t1():
        field = Payment._fields.get("branch_id")
        truthy(field, "account.payment.branch_id missing")
        eq(field.comodel_name, "branch.branch")
        truthy(field.store, "the branch of a payment must be stored")
        truthy(not field.readonly, "the branch of a payment must be editable")
        eq(tuple(field.get_depends(Payment)[0]), ("move_id.branch_id",),
           "the payment follows its journal entry")
        truthy(field.index, "the branch must be indexed")
        truthy(field.check_company, "the branch must be company checked")

        wizard_field = Register._fields.get("branch_id")
        truthy(wizard_field, "account.payment.register.branch_id missing")
        eq(wizard_field.comodel_name, "branch.branch")
        truthy("line_ids.branch_id" in wizard_field.get_depends(Register)[0],
               "the wizard follows the invoice")
    check("T1 branch on the payment and on the wizard", t1)

    # ------------------------------------------------------------------
    # T2 - the wizard proposes the branch of a customer invoice
    # ------------------------------------------------------------------
    def t2():
        invoice = make_move("out_invoice", b1, sale_journal, income)
        wizard = Register.with_context(
            active_model="account.move", active_ids=[invoice.id]).create({})
        eq(wizard.branch_id, b1, "branch of the invoice proposed")
    check("T2 the wizard proposes the branch of the invoice", t2)

    # ------------------------------------------------------------------
    # T3 - the wizard proposes the branch of a vendor bill
    # ------------------------------------------------------------------
    def t3():
        bill = make_move("in_invoice", b2, purchase_journal, expense)
        wizard = Register.with_context(
            active_model="account.move", active_ids=[bill.id]).create({})
        eq(wizard.branch_id, b2, "branch of the bill proposed")
    check("T3 the wizard proposes the branch of the bill", t3)

    # ------------------------------------------------------------------
    # T4 - an invoice without branch proposes nothing
    # ------------------------------------------------------------------
    def t4():
        invoice = make_move("out_invoice", None, sale_journal, income)
        wizard = Register.with_context(
            active_model="account.move", active_ids=[invoice.id]).create({})
        truthy(not wizard.branch_id, "no branch to propose")
    check("T4 an invoice without branch proposes no branch", t4)

    # ------------------------------------------------------------------
    # T5 - the payment created by the wizard keeps the branch
    # ------------------------------------------------------------------
    def t5():
        invoice = make_move("out_invoice", b1, sale_journal, income)
        wizard, payment = register_payment(invoice)
        eq(wizard.branch_id, b1, "the wizard kept the branch")
        eq(payment.branch_id, b1, "branch of the payment")
        truthy(payment.move_id, "the payment has no journal entry")
        eq(payment.move_id.branch_id, b1, "branch of the journal entry")
        eq(set(payment.move_id.line_ids.mapped("branch_id").ids), {b1.id},
           "the journal items carry the branch")
    check("T5 the payment and its journal entry keep the branch", t5)

    # ------------------------------------------------------------------
    # T6 - a vendor payment keeps the branch of the bill
    # ------------------------------------------------------------------
    def t6():
        bill = make_move("in_invoice", b2, purchase_journal, expense)
        wizard, payment = register_payment(bill)
        eq(wizard.branch_id, b2, "the wizard proposed the branch of the bill")
        eq(payment.branch_id, b2, "branch of the payment")
        eq(payment.move_id.branch_id, b2, "branch of the journal entry")
        eq(payment.payment_type, "outbound", "a vendor payment")
    check("T6 a vendor payment keeps the branch of the bill", t6)

    # ------------------------------------------------------------------
    # T7 - every line of the entry of a payment carries the branch
    # ------------------------------------------------------------------
    def t7():
        invoice = make_move("out_invoice", b1, sale_journal, income)
        wizard, payment = register_payment(invoice)
        move = payment.move_id
        lines = move.line_ids.filtered(lambda l: l.account_id)
        truthy(len(lines) >= 2, "the entry of a payment has two lines")
        acc = str(b1.analytic_account_id.id)
        for line in lines:
            eq(line.analytic_distribution, {acc: 100.0},
               "line %s (%s)" % (line.id, line.account_id.code))
        entries = env["account.analytic.line"].search(
            [("move_line_id", "in", move.line_ids.ids)])
        truthy(entries, "the analytic items of the payment were not created")
        eq(set(entries.mapped("branch_id").ids), {b1.id},
           "every analytic item of the payment keeps the branch")
    check("T7 every line of the entry of a payment carries the branch", t7)

    # ------------------------------------------------------------------
    # T8 - a payment created directly keeps its branch
    # ------------------------------------------------------------------
    def t8():
        payment = Payment.create({
            "payment_type": "inbound",
            "partner_type": "customer",
            "partner_id": partner.id,
            "amount": 25.0,
            "journal_id": pay_journal.id,
            "branch_id": b1.id,
        })
        eq(payment.branch_id, b1, "branch kept at creation")
        truthy(not payment.move_id, "no journal entry yet")
        payment.action_post()
        truthy(payment.move_id, "the entry has been generated")
        eq(payment.move_id.branch_id, b1, "branch of the generated entry")
        eq(payment.branch_id, b1, "the payment still shows the branch")
    check("T8 a payment created directly gives its branch to the entry", t8)

    # ------------------------------------------------------------------
    # T9 - the payment and its entry never disagree
    # ------------------------------------------------------------------
    def t9():
        invoice = make_move("out_invoice", b1, sale_journal, income)
        wizard, payment = register_payment(invoice)
        payment.write({"branch_id": b2.id})
        eq(payment.branch_id, b2, "the payment changed")
        eq(payment.move_id.branch_id, b2, "the entry follows the payment")
        payment.move_id.write({"branch_id": b1.id})
        env.invalidate_all()
        eq(payment.branch_id, b1, "the payment follows the entry")
        eq(payment.move_id.branch_id, b1, "the entry keeps it")
    check("T9 the payment and its entry always agree", t9)

    # ------------------------------------------------------------------
    # T10 - every line of a miscellaneous entry takes it
    # ------------------------------------------------------------------
    def t10():
        move = Move.create({
            "move_type": "entry", "journal_id": misc_journal.id,
            "branch_id": b1.id,
            "line_ids": [
                (0, 0, {"name": "Phase9 income", "account_id": income.id,
                        "credit": 100.0, "debit": 0.0}),
                (0, 0, {"name": "Phase9 bank", "account_id": cash.id,
                        "debit": 100.0, "credit": 0.0}),
            ],
        })
        income_line = move.line_ids.filtered(lambda l: l.account_id == income)
        bank_line = move.line_ids.filtered(lambda l: l.account_id == cash)
        truthy(income_line and bank_line, "the two lines of the entry")
        acc = str(b1.analytic_account_id.id)
        eq(income_line.analytic_distribution, {acc: 100.0},
           "an income line takes the account of the branch")
        eq(bank_line.analytic_distribution, {acc: 100.0},
           "a bank line takes it too: every line of the entry does")
        move.action_post()
        entries = env["account.analytic.line"].search(
            [("move_line_id", "in", move.line_ids.ids)])
        truthy(len(entries) >= 2, "one analytic item per line on post")
        eq(set(entries.mapped("branch_id").ids), {b1.id}, "their branch")
    check("T10 every line of a miscellaneous entry takes it", t10)

    # ------------------------------------------------------------------
    # T11 - the invoices still take it (phase 6)
    # ------------------------------------------------------------------
    def t11():
        invoice = make_move("out_invoice", b1, sale_journal, income)
        line = invoice.line_ids.filtered(lambda l: l.display_type == "product")
        eq(line.analytic_distribution,
           {str(b1.analytic_account_id.id): 100.0},
           "the product line of the invoice keeps the branch account")
    check("T11 the invoices still take the analytic account", t11)

    # ------------------------------------------------------------------
    # T12 - the four views show the branch
    # ------------------------------------------------------------------
    def t12():
        form = env.ref("account.view_account_payment_form").get_combined_arch()
        truthy('name="branch_id"' in form, "no branch on the payment form")
        truthy('readonly="state != \'draft\'"' in form,
               "the branch follows the rule of the other fields")

        tree = env.ref("account.view_account_payment_tree").get_combined_arch()
        truthy('name="branch_id"' in tree, "no branch column in the list")
        truthy('optional="show"' in tree, "the column must be optional")

        search = env.ref(
            "account.view_account_payment_search").get_combined_arch()
        truthy('groupby_branch' in search, "no branch group by")
        truthy("'group_by': 'branch_id'" in search, "group by the branch")

        wizard = env.ref(
            "account.view_account_payment_register_form").get_combined_arch()
        truthy('name="branch_id"' in wizard, "no branch on the wizard")
    check("T12 form, list, search and wizard show the branch", t12)

    # ------------------------------------------------------------------
    # T13 - a restricted user only sees the payments of their branch
    # ------------------------------------------------------------------
    def t13():
        invoice_b1 = make_move("out_invoice", b1, sale_journal, income)
        invoice_b2 = make_move("out_invoice", b2, sale_journal, income)
        pay_b1 = register_payment(invoice_b1)[1]
        pay_b2 = register_payment(invoice_b2)[1]
        pay_none = Payment.create({
            "payment_type": "inbound", "partner_type": "customer",
            "partner_id": partner.id, "amount": 10.0,
            "journal_id": pay_journal.id,
        })
        truthy(not pay_none.branch_id, "a payment without branch")

        seen = Payment.with_user(restricted).search(
            [("id", "in", [pay_b1.id, pay_b2.id, pay_none.id])])
        eq(set(seen.ids), {pay_b1.id, pay_none.id},
           "the payments of b1 and the one without branch only")
        with expect(AccessError):
            Payment.with_user(restricted).browse(pay_b2.id).read(["id"])
    check("T13 a restricted user only sees the payments of their branch", t13)

    # ------------------------------------------------------------------
    # T14 - the payment entries are not counted as invoices
    # ------------------------------------------------------------------
    def t14():
        invoice = make_move("out_invoice", b1, sale_journal, income)
        register_payment(invoice)
        entries = Move.search([("branch_id", "=", b1.id),
                               ("move_type", "=", "entry")])
        truthy(entries, "the entry of the payment carries the branch")
        eq(b1.invoice_count,
           Move.search_count([("branch_id", "=", b1.id),
                              ("move_type", "!=", "entry")]),
           "the entries of payment are not invoices")
    check("T14 the payment entries are not counted as invoices", t14)

except Exception:  # noqa: BLE001 - never leave the shell in a broken state
    import traceback
    LINES.append("FATAL " + traceback.format_exc())
    FAIL += 1
finally:
    print("\n".join([""] + LINES))
    print("\n==== PHASE 9: %d PASS / %d FAIL ====" % (PASS, FAIL))
    env.cr.rollback()
