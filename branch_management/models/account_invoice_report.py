# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.models import TableSQL
from odoo.tools import SQL


class AccountInvoiceReport(models.Model):
    _inherit = 'account.invoice.report'

    # The report has ``_auto = False`` and builds its SQL through the property
    # ``_table_sql``; the column list is built by ``_select_list()``, so the
    # field has to be declared here and given a SQL expression there.
    # ``store`` is True by default on a plain (non computed) many2one, which is
    # what makes the field selectable and groupable by the ORM.
    branch_id = fields.Many2one(
        'branch.branch',
        string='Branch',
        readonly=True,
        help='Branch of the invoice this line comes from.',
    )

    # -------------------------------------------------------------------------
    # Fix for an Odoo 20 defect of the *pivot* view of this very report
    # (README section 13).  This is a fix of the web client behaviour, not a
    # change of the data: same columns, same SQL, same labels.
    #
    # Odoo declares four of the measures of ``account.invoice.report`` with an
    # explicit ``aggregator='sum_currency'`` while ``Monetary.aggregator``
    # defaults to ``'sum'`` (``odoo/orm/fields_numeric.py``) -- which is why the
    # sibling measures ``price_subtotal_currency`` / ``price_total_currency``
    # show a number and these four show an empty cell.
    #
    # ``web/static/src/views/pivot/pivot_model.js`` builds, for every active
    # monetary measure, the specs::
    #
    #     _getMeasureSpecs():  push "<measure>:<field.aggregator>"
    #                          push "<currency_field>:array_agg_distinct"
    #                          push "<measure>:sum_currency"
    #
    # and then, in ``_getMeasurements()``::
    #
    #     if (aggregator === "sum_currency") {
    #         const currencies = group[...currency_field + ":array_agg_distinct"];
    #         if (currencies.length === 1) { return measurements; }   // dropped
    #     }
    #
    # With ``aggregator='sum_currency'`` the *first* spec is dropped too, so
    # ``measurements[name]`` is never assigned, ``value === undefined`` and the
    # cell is rendered blank.  Every group holding a single currency -- the
    # normal case -- is affected, so ``Total``, ``Untaxed Amount``, ``Margin``
    # and ``Inventory Value`` are all empty in the pivot.
    #
    # Declaring them with ``aggregator='sum'`` restores the behaviour the graph
    # view already implements: a plain sum, replaced by the currency-converted
    # value only when the group spans several currencies.  The conversion spec
    # is still requested, because ``currency_field`` is still set, so
    # ``_getMeasureSpecs()`` keeps pushing ``"<measure>:sum_currency"`` and it
    # keeps overriding the plain sum exactly when it must.
    #
    # ``aggregator`` is not stored anywhere (not a column, not in
    # ``ir.model.fields``): it is read by ``fields_get()`` from the field
    # object, so a plain ``-u branch_management`` is enough.
    # -------------------------------------------------------------------------
    price_subtotal = fields.Monetary(
        string='Untaxed Amount',
        readonly=True,
        currency_field='company_currency_id',
        aggregator='sum',
    )
    price_total = fields.Monetary(
        string='Total',
        readonly=True,
        currency_field='company_currency_id',
        aggregator='sum',
    )
    price_margin = fields.Monetary(
        string='Margin',
        readonly=True,
        currency_field='company_currency_id',
        aggregator='sum',
    )
    inventory_value = fields.Monetary(
        string='Inventory Value',
        readonly=True,
        currency_field='company_currency_id',
        aggregator='sum',
    )

    def _select_list(self, table: TableSQL):
        """Add the branch of the invoice to the columns of the report.

        Odoo 20 difference: ``account.invoice.report`` is not a database view
        anymore (the same is true of ``sale.report``).  Its ``_table_sql`` is a
        property returning the query, which is inlined in every select, so the
        new column is usable as soon as the module is loaded -- no ``init()``,
        no ``DROP VIEW``/``CREATE VIEW`` and no ``-u account``.

        * ``table`` is the ``account_move_line`` alias of the report query, and
          ``account.move.line.branch_id`` is a *stored related* field of
          ``move_id.branch_id``: its value is exactly the branch of the
          invoice, read with no extra join.
        * The expression must be aliased ``AS branch_id``: the report is a
          subselect, and both the columns and the group by are resolved
          against the name of that output column
          (``FROM (<subselect>) AS "account_invoice_report"``).
        """
        return super()._select_list(table) + [
            SQL("%s AS branch_id", table.branch_id),
        ]
