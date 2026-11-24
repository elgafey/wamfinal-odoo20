# -*- coding: utf-8 -*-
{
    'name': 'Bank Fees Allocation',
    'version': '20.0.1.0.0',
    'category': 'Accounting/Accounting',
    'sequence': 40,
    'summary': 'Split the bank fees of an aggregated card settlement over the '
               'original sales journal items.',
    'description': """
Bank Fees Allocation
====================

Salespeople record card (Visa) sales, e.g. 100.00.  The bank settles the
card transactions of the day in **one single aggregated line**, net of the
fees (95.00 deposited, 5.00 of fees).  The accountant has to group the
original sales journal items, type the amount the bank really deposited
and post **one** entry that splits the fee and reconciles everything.

What the module does
---------------------

* A dedicated view (*Accounting > Bank Fees Allocation*) lists the journal
  items of the configured allocation accounts: posted entries only, not
  fully reconciled, restricted to the company of the user.  The list is
  grouped by account (the group header shows the balance sum) and can be
  grouped by date, partner, journal, analytic distribution or entry.
* The *Bank Fees Allocation* button of the list header opens a wizard on
  the selected lines, **whatever their number**: the lines may come from
  several days and from several accounts.
* The wizard computes the total of the selection and keeps two amounts
  consistent both ways: typing the **Net Amount** recomputes the
  **Fee Amount**, typing the **Fee Amount** recomputes the **Net Amount**.
* On confirmation, **one** journal entry is created and posted:

      Debit  Bank Account                95.00   (net amount)
      Debit  Bank Fees Expense Account     5.00   (fee, analytic carried over)
      Credit Visa / Card clearing       100.00   (one line per source account)

  The analytic distribution of the source journal items is carried over
  **proportionally** to the fee line and to the credit lines, so the cost
  centre (or the branch) of every sale is preserved.
* Every credit line is then reconciled with the journal items it comes
  from, through Odoo's own reconciliation (``account.move.line.reconcile()``).

History
-------

Every confirmation stores a ``bank.fees.allocation`` record: its reference,
its date, its company, its user, the bank account, the total, the net
amount, the fee, the generated journal entry and the source journal items.
The *Cancel* button unreconciles the entry, posts its reversal and frees
the original journal items: they can be allocated again.

Reports
-------

* List, pivot and graph views of the allocations: fees by bank account, by
  period (day / month), by source account (branch) and by user.
* Filters on the date range, the bank account, the source account and the
  state.
* The XLSX export is the **standard list export** of Odoo.
* A printable QWeb PDF summary (total sales, total fees, net, per bank
  account, per period, per source account).

Configuration
-------------

The settings live in *Accounting > Configuration > Settings > Accounting >
Bank Fees Allocation* and are **company dependent**:

* *Allocation Accounts*: the accounts the accountant works on (the
  Visa/card clearing accounts).  A branch may have several of them.
* *Bank Fees Expense Account*: where the fee is booked.
* *Bank Accounts*: the bank accounts offered **only** inside the wizard.
* *Allocation Journal*: defaults to the Miscellaneous journal of the
  company.

Security
--------

Two groups are created:

* *Bank Fees Allocation / Administrator*: everything, including the
  settings.
* *Bank Fees Allocation / User* (the accountant): can open the allocation
  view and run the wizard; the settings stay read-only for them.

Record rules restrict the allocations to the companies of the user.

Odoo 20
-------

The module follows the real Odoo 20 APIs: ``<list>`` views (never
``<tree>``), the ``parent_state`` / ``reconciled`` / ``full_reconcile_id``
fields of ``account.move.line``, the ``action_post()`` workflow of
``account.move``, the ``sequence.mixin`` mechanism of Odoo 20 and the
``res.groups.privilege`` group format of Odoo 20.

It depends on ``account`` (and on ``mail``, which ``account`` already
brings) **only**: it installs and runs on the Community *and* on the
Enterprise edition.
    """,
    'author': 'Islam Elgafey',
    'website': '',
    'license': 'LGPL-3',
    'depends': ['account', 'mail'],
    'data': [
        'security/bank_fees_allocation_security.xml',
        'security/ir.access.csv',
        'reports/bank_fees_allocation_report_templates.xml',
        'wizard/bank_fees_allocation_wizard_views.xml',
        'views/bank_fees_allocation_line_views.xml',
        'views/bank_fees_allocation_views.xml',
        'views/account_move_line_views.xml',
        'views/res_config_settings_views.xml',
        'views/bank_fees_allocation_menu.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': True,
}