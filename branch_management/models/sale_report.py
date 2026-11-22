# -*- coding: utf-8 -*-
from odoo import fields, models


class SaleReport(models.Model):
    _inherit = 'sale.report'

    # ``store`` is True by default for a plain (non computed) field, which is
    # what makes the column part of the select list built by
    # ``_select_dict_to_list()``.
    branch_id = fields.Many2one(
        'branch.branch',
        string='Branch',
        readonly=True,
        help='Branch of the sales order this line belongs to.',
    )

    def _select_dict(self, table):
        """Add the branch of the order to the columns of the report.

        Odoo 20 difference: ``sale.report`` is not a database view anymore,
        so there is nothing to drop and recreate.

        * The model builds its SQL through ``_table_sql()``, which is inlined
          in every query (``Query.__init__``), so the new column is usable as
          soon as the module is loaded, with no ``init()`` and no ``-u sale``.
        * The select list is built from the *stored* fields of the model, so
          declaring ``branch_id`` is enough for it to be selected; this method
          only has to give the SQL expression of its value.
        * ``table.order_id.branch_id`` adds the join on ``sale_order`` and
          returns its column. ``_groupby_list()`` already groups by
          ``table.order_id.id`` (primary key of ``sale_order``), so PostgreSQL
          accepts the new column without grouping by it -- this is exactly how
          ``sale_stock`` adds ``warehouse_id``.
        """
        return super()._select_dict(table) | {
            'branch_id': table.order_id.branch_id,
        }
