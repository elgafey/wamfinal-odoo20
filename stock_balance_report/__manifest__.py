# -*- coding: utf-8 -*-
{
    'name': 'Stock Balance Report',
    'version': '20.0.2.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Opening balance, IN, OUT and closing balance for a chosen period',
    'author': 'Islam Elgafey',
    'description': """
Stock Balance Report
====================

Choose a period (From / To) and get, for every product that has a stock trace:

* Opening Balance: quantity on hand before the From date
* IN: incoming quantities inside the period
* OUT: outgoing quantities inside the period
* Closing Balance: Opening + IN - OUT

Each of the four figures is displayed as two columns side by side: the
quantity and its value.

Notes:

* Internal transfers between the locations of the same company are ignored,
  because the report is computed on the whole company.
* The data is read with a SQL query directly on ``stock.move``, the table
  behind Inventory > Reporting > Moves Analysis.
* Only done moves are taken into account and quantities are converted to
  the unit of measure of the product.
* The value columns come from the ``value`` field of ``stock.move``
  (WMS Accounting) and follow exactly the same rules as the quantities:
  same moves, same period, same in / out split. A product with no valued
  move shows a value of 0.

Outputs:

* The screen view, with the totals of the period.
* An Excel / CSV export through Odoo's standard "Export" (Open as List).
* A PDF print (A4 landscape) with the key figures, the table and the
  totals, available from the "Print PDF" button and from the Print menu.
""",
    'depends': ['stock'],
    'data': [
        'security/ir.access.csv',
        'wizard/stock_balance_report_views.xml',
        'report/stock_balance_report_templates.xml',
        'views/stock_balance_report_menu.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
