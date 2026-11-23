# -*- coding: utf-8 -*-
{
    'name': 'Branch Request',
    'version': '20.0.2.0.0',
    'category': 'Supply Chain',
    'summary': 'Branch employees submit requests for goods to the procurement team',
    'description': """
Branch Request
==============
Branch employees submit requests for goods; the procurement team reviews
them and approves, rejects or completes them.

Branch Transfers
----------------
A branch can also ask goods from another branch: the supplying branch
approves and sends them to a global transit location, and the requesting
branch receives them from there.  Store keepers define, per internal
location, which users are responsible for it.

Prices are deliberately out of scope: employees never enter nor see prices.
Pricing is handled by the procurement team outside this application.
""",
    'author': 'Islam Elgafey',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'product', 'purchase', 'stock'],
    'data': [
        'security/branch_request_security.xml',
        'security/ir.access.csv',
        'data/ir_sequence_data.xml',
        'data/branch_transfer_data.xml',
        'wizard/branch_request_create_po_wizard_views.xml',
        'views/branch_request_views.xml',
        'wizard/branch_low_stock_views.xml',
        'views/branch_store_keeper_views.xml',
        'views/branch_transfer_views.xml',
        'wizard/branch_transfer_wizard_views.xml',
        'report/branch_request_report.xml',
        'report/branch_request_report_templates.xml',
    ],
    'installable': True,
    'application': False,
}
