# -*- coding: utf-8 -*-
{
    'name': 'Bank Fees Allocation',
    'version': '20.0.1.0.2',
    'category': 'Accounting/Accounting',
    'sequence': 40,
    'summary': 'Allocate part of a journal item being reconciled to a Bank Fees expense account.',
    'description': """
Bank Fees Allocation
====================

Adds a **Closing Fees** button next to the standard **Reconcile** button in
*Accounting > Closing > Reconcile* (Journal Items to Reconcile).

The wizard accepts **one or several** selected journal items (they must share
the same account) and splits the amount available for reconciliation:

    Unlink Account Amount  +  Bank Fees Amount  =  Amount to reconcile

The **Unlink Account** is **optional** and starts **empty**: it is shown in
*green* (`text-success`) and only offers **Bank and Cash** accounts. Left
empty, the remaining amount simply stays on the account of the selection.
When a Bank and Cash account is picked, the line that reconciles the source
items is always posted on the source account (Odoo refuses to reconcile items
coming from different accounts), while the remaining amount is unloaded on
that chosen account.

The **Bank Fees configuration is required only when fees are actually
charged**: with a zero Bank Fees Amount no fees account and no cost center
are needed, because the fees line is worth nothing in both currencies and is
dropped from the generated entry.

The **Cost Center** (analytic distribution) is stored on the Bank Fees line
of the generated entry and is exposed in the entry itself as a *Cost Center*
column.

The **journal entry date** is the user's own choice: if a lock date blocks
the selected date, the wizard raises a clear error instead of silently moving
the entry to another date. Picking another journal re-validates that date,
it never overwrites it either.

The wizard posts the entry **once**: pressing Post a second time is refused
with a clear message and never creates a second journal entry.

The generated entry always carries at least two lines (three when fees are
charged) and is always balanced, including a foreign currency selection whose
Unlink Account Amount is set to zero (the "Unlink" line is dropped only when
it is worth nothing in both currencies).

It then reconciles the new entry with every selected journal item using
Odoo's own reconciliation mechanism.

The module never modifies Odoo core files, never patches core methods and
never fabricates a reconciliation status.
    """,
    'author': 'Custom',
    'website': '',
    'license': 'LGPL-3',
    'depends': ['account_accountant', 'analytic'],
    'data': [
        'security/ir.access.csv',
        'wizard/bank_fees_wizard_views.xml',
        'views/bank_fees_reconcile_views.xml',
        'views/bank_fees_move_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
}
