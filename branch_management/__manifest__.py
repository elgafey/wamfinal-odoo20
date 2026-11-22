# -*- coding: utf-8 -*-
{
    'name': 'Branch Management',
    'version': '20.0.1.2.0',
    'category': 'Sales/Sales',
    'summary': 'Branches as master data linked to warehouses, analytic accounts, '
               'sales, inventory and accounting',
    'author': 'Islam Elgafey',
    'description': """
Branch Management
=================

Create a "Branch" master data record and use it as the operational link
between Sales, Inventory, Accounting and Analytic Accounting.

A branch holds:

* Branch Name, Branch Code (unique inside the company), Company
* Analytic Account (optional, can be created automatically)
* Warehouse and the default stock / customer / vendor locations
* Address, contact, manager, notes, active / archived

Main rules:

* One warehouse belongs to one branch (can be relaxed per company).
* One analytic account is never shared by two branches.
* The branch company must be the company of its warehouse and of its
  analytic account.
* Users can be given a list of allowed branches and a default branch.

Integration (each step uses the standard Odoo extension mechanisms only,
no core file is modified):

* Sales Order: branch field, default branch for the user, the warehouse
  of the branch is proposed automatically.
* Delivery / pickings and stock moves inherit the branch of the sales
  order through the procurement values.
* Customer invoices (including down payments) inherit the branch of the
  sales order, credit notes inherit it from the original invoice.
* Journal items carry the branch of the invoice.
* Invoices Analysis (account.invoice.report) carries it too: the branch
  column is added to the report query, with a search facet and a "Branch"
  group by, and a global restriction keeps the lines of the other branches
  away from a branch user.
* On that same report, the four monetary measures that Odoo declares with
  aggregator='sum_currency' (Untaxed Amount, Total, Margin, Inventory
  Value) are re-declared with the Monetary default aggregator='sum'.
  The pivot view of Odoo drops a sum_currency result as soon as a group
  holds a single currency, and since the first spec it asks for is also
  sum_currency no other spec writes the value: those four columns were
  rendered empty. Same columns, same SQL, same labels, and the currency
  conversion is still requested through currency_field, so a group
  spanning several currencies is still converted (README section 13).
* Payments (customer and vendor) carry the branch too: it is proposed on
  the register payment wizard from the invoice, shown on the form and the
  list of the payments, and given to their journal entry.
* Contacts carry the branches they belong to: a "Branches" field accepting
  several branches on the contact form, with a column in the list and a
  search / group by in the contacts search.
* A "Branch User" only sees the contacts of his own branches: a global
  (groupless) restriction row on res.partner hides the contacts of the
  other branches for read, write and unlink, keeps the contacts without a
  branch visible to everybody, and always lets him read his own contact
  and the company contact (the stored helper has_branch is used because
  an ir.access domain cannot say ("branch_ids", "=", False)).
* The analytic account of the branch is applied to the analytic
  distribution of **every journal item of the entry that carries an
  account**: the income line, the receivable line, the tax lines, the
  payment term lines and the bank line alike, and the analytic items are
  built from them (so the analytic entries of a branch all carry it). When
  the branch of an entry is set after it was posted, or changed, or
  removed, the distribution and the analytic items are rebuilt: Odoo only
  recomputes the distribution on its own, and a recomputation never calls
  the core method that creates the analytic items. Entries that already
  existed are covered by the same routine (README section 14).
* Sales Analysis (sale.report) carries the branch of the order: column,
  search facet and a "Branch" group by are added to the standard report.
* The form of the branch shows the counters of its orders, transfers and
  invoices, each of them opening the related list filtered on the branch,
  plus a button that opens the sales analysis limited to the branch.
""",
    'depends': ['sale_stock', 'stock', 'account', 'analytic'],
    'data': [
        'security/branch_security.xml',
        'security/ir.access.csv',
        'views/account_journal_views.xml',
        'data/branch_data.xml',
        'views/branch_views.xml',
        'views/product_pricelist_views.xml',
        'views/res_partner_views.xml',
        'views/res_users_views.xml',
        'views/sale_order_views.xml',
        'views/sale_report_views.xml',
        'views/stock_views.xml',
        'views/account_views.xml',
        'views/account_invoice_report_views.xml',
        'views/account_payment_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
