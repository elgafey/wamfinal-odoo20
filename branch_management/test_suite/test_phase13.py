# -*- coding: utf-8 -*-
"""Phase 13 tests: the pivot measures of account.invoice.report.

Odoo declares four monetary measures of this report with
``aggregator='sum_currency'``.  ``pivot_model.js`` discards a ``sum_currency``
result as soon as a group holds a single currency, and because the *first*
spec it pushes is also ``sum_currency`` nothing else writes the value, so
``Total``, ``Untaxed Amount``, ``Margin`` and ``Inventory Value`` are rendered
as an empty cell.  The module re-declares them with the ``Monetary`` default
``aggregator='sum'`` (README section 13).

Run with:  odoo shell -d balance_mod ... < test_phase13.py
The whole script runs in one transaction and rolls it back at the end.
"""
PASS = FAIL = 0
LINES = []

# The measures of the pivot of "Invoices Analysis", in the order they are read.
ACTIVE = [
    "price_subtotal_currency", "price_total_currency", "quantity",
    "price_margin", "inventory_value", "price_average",
    "price_total", "price_subtotal",
]
# The four measures Odoo declares with aggregator='sum_currency'.
FIXED = ["price_subtotal", "price_total", "price_margin", "inventory_value"]


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


# ---------------------------------------------------------------------------
# A faithful copy of the two methods of web/.../pivot/pivot_model.js that
# decide whether a measure reaches the cell.  Any change there must be
# mirrored here.
# ---------------------------------------------------------------------------
def pivot_specs(measures, flds):
    """``PivotModel._getMeasureSpecs()`` (lines 1079-1097)."""
    specs = []
    for measure in measures:
        if measure == "__count":
            specs.append(measure)
            continue
        field = flds[measure]
        if field.get("aggregator") is None:
            raise AssertionError("no aggregator for the measure %r" % measure)
        specs.append("%s:%s" % (measure, field["aggregator"]))
        if field.get("currency_field"):
            specs.append("%s:array_agg_distinct" % field["currency_field"])
            specs.append("%s:sum_currency" % measure)
    return specs


def pivot_cells(group, specs, flds):
    """``PivotModel._getMeasurements()`` (lines 990-1010)."""
    cells = {}
    for measure_name in specs:
        measurement = group.get(measure_name)
        field_name, _, aggregator = measure_name.partition(":")
        if aggregator == "array_agg_distinct":
            continue
        if aggregator == "sum_currency":
            currencies = group.get(
                flds[field_name]["currency_field"] + ":array_agg_distinct")
            truthy(currencies is not None,
                   "the currency spec %r was never requested"
                   % (flds[field_name]["currency_field"] + ":array_agg_distinct",))
            if len(currencies) == 1:
                continue        # this is where Odoo drops the value
        cells[field_name] = measurement
    return cells


def read_group_dict(model, domain, groupbys, specs):
    """``read_group`` returns tuples in Odoo 20: map them back to their spec."""
    rows = model.read_group(domain, groupbys, specs)
    keys = list(groupbys) + list(specs)
    mapped = []
    for row in rows:
        group = dict(zip(keys, row))
        for extra, name in zip(row[len(keys):], ("__count", "__domain")):
            group[name] = extra
        mapped.append(group)
    return mapped


try:
    Branch = env["branch.branch"]
    Move = env["account.move"]
    R = env["account.invoice.report"]

    main_company = env.ref("base.main_company")
    journal = env["account.journal"].search([("type", "=", "sale")], limit=1)
    income = env["account.account"].search(
        [("account_type", "in", ("income", "income_other"))], limit=1)
    receivable = env["account.account"].search(
        [("account_type", "=", "asset_receivable")], limit=1)
    truthy(journal, "no sales journal")
    truthy(income, "no income account")
    truthy(receivable, "no receivable account")

    partner = env["res.partner"].create({"name": "Phase13 Customer"})
    partner.write({"property_account_receivable_id": receivable.id})
    product = env["product.product"].create({
        "name": "Phase13 Product", "list_price": 100.0,
        "standard_price": 40.0,
        "invoice_policy": "order",
        "property_account_income_id": income.id})

    b1 = Branch.create({"name": "Phase13 Branch A", "code": "P13A",
                        "company_id": main_company.id})

    def make_invoice(branch):
        line = {"display_type": "product", "name": "Phase13 line",
                "quantity": 2, "price_unit": 100.0,
                "account_id": income.id, "product_id": product.id}
        return Move.create({"move_type": "out_invoice",
                            "partner_id": partner.id, "journal_id": journal.id,
                            "branch_id": branch.id if branch else False,
                            "line_ids": [(0, 0, line)]})

    m1, m2 = make_invoice(b1), make_invoice(None)
    OURS = [m1.id, m2.id]
    DOM = [("move_id", "in", OURS)]
    # Read the amounts from the invoices themselves: the fixtures may inherit
    # a default sales tax from the chart of accounts, and the test must not
    # depend on that configuration.
    UNTAXED = round(sum(m.amount_untaxed for m in (m1, m2)), 2)
    TAXED = round(sum(m.amount_total for m in (m1, m2)), 2)
    QTY = 4.0                       # 2 invoices x 2 units, same UoM

    fields = {name: spec for name, spec in R.fields_get(
        ACTIVE + ["company_currency_id", "currency_id"]).items()}

    # ------------------------------------------------------------------
    # T1 - the four measures are declared with the Monetary default
    # ------------------------------------------------------------------
    def t1():
        for name in FIXED:
            spec = fields[name]
            eq(spec.get("type"), "monetary", name)
            eq(spec.get("aggregator"), "sum",
               "the aggregator of %s must be the Monetary default" % name)
    check("T1 aggregator of the four measures is 'sum'", t1)

    # ------------------------------------------------------------------
    # T2 - everything else about those four fields is unchanged
    # ------------------------------------------------------------------
    def t2():
        expect_label = {
            "price_subtotal": "Untaxed Amount",
            "price_total": "Total",
            "price_margin": "Margin",
            "inventory_value": "Inventory Value",
        }
        for name, label in expect_label.items():
            spec = fields[name]
            eq(spec.get("string"), label, "the label of %s" % name)
            # still set: this is what keeps the currency-converted spec
            # "<measure>:sum_currency" requested by _getMeasureSpecs()
            eq(spec.get("currency_field"), "company_currency_id", name)
    check("T2 labels and currency_field are untouched", t2)

    # ------------------------------------------------------------------
    # T3 - the measures Odoo did not declare as sum_currency are untouched
    # ------------------------------------------------------------------
    def t3():
        eq(fields["price_average"].get("aggregator"), "avg_currency",
           "Average Price must keep its own aggregator")
        eq(fields["price_subtotal_currency"].get("aggregator"), "sum")
        eq(fields["price_total_currency"].get("aggregator"), "sum")
        eq(fields["quantity"].get("aggregator"), "sum")
        eq(fields["price_subtotal_currency"].get("currency_field"), "currency_id")
        eq(fields["price_total_currency"].get("currency_field"), "currency_id")
        truthy(not fields["quantity"].get("currency_field"),
               "a float has no currency")
    check("T3 the other measures are untouched", t3)

    # ------------------------------------------------------------------
    # T4 - the server answers the new spec with real numbers
    # ------------------------------------------------------------------
    def t4():
        cost = product.standard_price
        truthy(cost, "the fixture product must carry a cost (got %r)" % cost)
        specs = ["%s:sum" % name for name in FIXED]
        rows = read_group_dict(R, DOM, [], specs)
        truthy(rows, "the report has no row for the fixtures")
        group = rows[0]
        for name in FIXED:
            value = group["%s:sum" % name]
            truthy(value is not None, "%s:sum returned NULL" % name)
        qty = QTY
        # out_invoice -> sign = +1, rate = 1, so both aggregations are the
        # plain sums of the untaxed / taxed amounts of the invoices
        eq(round(group["price_subtotal:sum"], 2), UNTAXED, "untaxed amount")
        eq(round(group["price_total:sum"], 2), TAXED, "taxed total")
        eq(round(group["inventory_value:sum"], 2), round(-qty * cost, 2),
           "-quantity x sign x cost")
        eq(round(group["price_margin:sum"], 2), round(UNTAXED - qty * cost, 2),
           "margin = untaxed - quantity x cost")
        # the two measures Odoo cannot show today must not be zero either,
        # otherwise "fixed" would be indistinguishable from "still blank"
        truthy(group["price_margin:sum"] != 0, "margin must not be zero")
        truthy(group["inventory_value:sum"] != 0, "inventory must not be zero")
    check("T4 read_group answers '<measure>:sum' with real values", t4)

    # ------------------------------------------------------------------
    # T5 - THE FIX: a cell of the pivot is filled for every measure
    # ------------------------------------------------------------------
    def t5():
        specs = pivot_specs(ACTIVE, fields)
        rows = read_group_dict(R, DOM, [], specs)
        truthy(rows, "the report has no row for the fixtures")
        cells = pivot_cells(rows[0], specs, fields)
        for name in ACTIVE:
            truthy(name in cells,
                   "%r is missing from the pivot cells (blank cell)" % name)
            truthy(cells[name] is not None,
                   "%r renders a NULL cell" % name)
        for name in FIXED:
            truthy(cells[name] != 0, "%r renders an empty-looking 0" % name)
    check("T5 every measure reaches the pivot cell (no blank column)", t5)

    # ------------------------------------------------------------------
    # T6 - the four measures that used to work still do
    # ------------------------------------------------------------------
    def t6():
        specs = pivot_specs(ACTIVE, fields)
        rows = read_group_dict(R, DOM, [], specs)
        cells = pivot_cells(rows[0], specs, fields)
        eq(round(cells["price_subtotal_currency"], 2), UNTAXED)
        eq(round(cells["price_total_currency"], 2), TAXED)
        eq(round(cells["quantity"], 2), QTY)
        truthy(cells["price_average"] > 0, "Average Price")
    check("T6 the measures that worked before still work", t6)

    # ------------------------------------------------------------------
    # T7 - the currency-converted spec is still answered by the server:
    #      several currencies in one group must still be convertible
    # ------------------------------------------------------------------
    def t7():
        specs = ["%s:sum_currency" % name for name in FIXED]
        rows = read_group_dict(R, DOM, [], specs)
        group = rows[0]
        for name in FIXED:
            value = group["%s:sum_currency" % name]
            truthy(value is not None, "%s:sum_currency returned NULL" % name)
        eq(round(group["price_total:sum_currency"], 2), TAXED,
           "a single currency means a rate of 1, so both specs agree")
    check("T7 '<measure>:sum_currency' still answers (multi-currency path)",
          t7)

    # ------------------------------------------------------------------
    # T8 - the currency spec the JS relies on is still requestable
    # ------------------------------------------------------------------
    def t8():
        specs = ["company_currency_id:array_agg_distinct",
                 "currency_id:array_agg_distinct"]
        rows = read_group_dict(R, DOM, [], specs)
        group = rows[0]
        truthy(len(group["company_currency_id:array_agg_distinct"]) >= 1,
               "the company currency must be reported as a list")
        truthy(len(group["currency_id:array_agg_distinct"]) >= 1,
               "the invoice currency must be reported as a list")
    check("T8 'array_agg_distinct' of both currencies still answers", t8)

    # ------------------------------------------------------------------
    # T9 - regression: grouping by the branch still returns the measures
    # ------------------------------------------------------------------
    def t9():
        specs = pivot_specs(ACTIVE, fields)
        rows = read_group_dict(R, DOM, ["branch_id"], specs)
        eq(len(rows), 2, "one group per branch, one for the branch-less")
        by_branch = {}
        for row in rows:
            key = row["branch_id"]
            key = key.id if hasattr(key, "id") else key
            by_branch[key or False] = row
        truthy(b1.id in by_branch, "the branch group is missing")
        truthy(False in by_branch, "the branch-less group is missing")
        for row in rows:
            cells = pivot_cells(row, specs, fields)
            for name in ACTIVE:
                truthy(name in cells and cells[name] is not None,
                       "blank %r in the branch group" % name)
        truthy(by_branch[b1.id]["price_total:sum"] > 0, "branch total")
        truthy(by_branch[False]["price_total:sum"] > 0, "branch-less total")
    check("T9 grouping by branch + the new specs returns every measure", t9)

    # ------------------------------------------------------------------
    # T10 - the custom average of Odoo (price_average) is untouched
    # ------------------------------------------------------------------
    def t10():
        rows = read_group_dict(R, DOM, [], ["price_average:avg_currency"])
        value = rows[0]["price_average:avg_currency"]
        truthy(value is not None, "avg_currency returned NULL")
        truthy(value > 0, "avg_currency returned %r" % value)
        # Odoo overrides _read_group_select() on this model for that single
        # spec; the module must not shadow it.
        truthy("_read_group_select" not in type(R).__dict__,
               "the module must not override _read_group_select")
    check("T10 price_average keeps its custom aggregator", t10)

except Exception:  # noqa: BLE001 - never leave the shell in a broken state
    import traceback
    LINES.append("FATAL " + traceback.format_exc())
    FAIL += 1
finally:
    print("\n".join([""] + LINES))
    print("\n==== PHASE 13: %d PASS / %d FAIL ====" % (PASS, FAIL))
    env.cr.rollback()
