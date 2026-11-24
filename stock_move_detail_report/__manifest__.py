# -*- coding: utf-8 -*-
{
    'name': 'Stock Move Detail Report',
    'version': '20.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Detailed moves of a location with opening balance and running balance',
    'author': 'Custom Development',
    'description': """
Stock Move Detail Report
========================

Pick an internal location, a period and (optionally) a product, and get one
line per stock move instead of one line per product:

* Date
* Move (document / reference of the move)
* Product and unit of measure
* IN: quantity entering the location during the period
* OUT: quantity leaving the location during the period
* Counterpart location: the location on the other side of the move
* Balance: stock of the location *after* that move

The opening balance of every product (stock of the location before the From
date) is displayed as the first line of the product, so the balance column
always reconciles: opening + IN - OUT = balance of the last line.

Notes:

* The location must be an internal location. Its sub-locations are included:
  a move is IN when it enters the location from outside and OUT when it
  leaves it. Transfers staying inside the location are not shown.
* Only done moves are taken into account and quantities are converted to
  the unit of measure of the product.
* Only the products that have at least one move inside the period are listed.
* The data is read with a SQL query directly on ``stock.move``, the table
  behind Inventory > Reporting > Moves Analysis.

Outputs:

* The screen view, with the totals of the period.
* An Excel / CSV export through Odoo's standard "Export" (Open as List).
* A PDF print (A4 landscape), available from the "Print PDF" button and
  from the Print menu.
""",
    'depends': ['stock'],
    'data': [
        'security/ir.access.csv',
        'wizard/stock_move_detail_report_views.xml',
        'report/stock_move_detail_report_templates.xml',
        'views/stock_move_detail_report_menu.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
