# -*- coding: utf-8 -*-
{
    'name': 'Branch Request',
    'version': '20.0.1.0.0',
    'category': 'Supply Chain',
    'summary': 'Branch employees submit requests for goods to the procurement team',
    'description': """
Branch Request
==============
Branch employees submit requests for goods; the procurement team reviews
them and approves, rejects or completes them.

Prices are deliberately out of scope: employees never enter nor see prices.
Pricing is handled by the procurement team outside this application.
""",
    'author': 'Custom Development',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'hr', 'product'],
    'data': [
        'security/branch_request_security.xml',
        'security/ir.access.csv',
        'data/ir_sequence_data.xml',
        'views/branch_request_views.xml',
        'report/branch_request_report.xml',
        'report/branch_request_report_templates.xml',
    ],
    'installable': True,
    'application': False,
}
