# Bank Fees Allocation

**Odoo 20 module** — split the bank fees of an aggregated card settlement
over the original sales journal items.

Salespeople record card (Visa) sales, e.g. `100.00`. The bank settles the
card transactions of the day in **one single aggregated line**, net of the
fees (`95.00` deposited, `5.00` of fees). The accountant has to group the
original sales journal items, type the amount the bank really deposited and
post **one** entry that splits the fee and reconciles everything.

---

## Table of contents

- [What it does](#what-it-does)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [The generated entry](#the-generated-entry)
- [Cancellation](#cancellation)
- [Reports](#reports)
- [Security](#security)
- [Technical notes (Odoo 20 APIs)](#technical-notes-odoo-20-apis)
- [Folder structure](#folder-structure)
- [Tests](#tests)

---

## What it does

* A dedicated view (*Accounting > Bank Fees Allocation*) lists the journal
  items of the configured allocation accounts: **posted** entries only, **not
  fully reconciled**, restricted to the company of the user. The list is
  grouped by account (the group header shows the balance sum) and can be
  grouped by date, partner, journal, analytic distribution or entry.
* The **Bank Fees Allocation** button of the list header opens a wizard on
  the selected lines, **whatever their number**: the lines may come from
  several days and from several accounts.
* The wizard computes the total of the selection and keeps two amounts
  consistent **both ways**:
  * typing the **Net Amount** recomputes the **Fee Amount**;
  * typing the **Fee Amount** recomputes the **Net Amount**.
* On confirmation, **one** journal entry is created and posted, then every
  credit line is reconciled with the journal items it comes from, through
  Odoo's own reconciliation (`account.move.line.reconcile()`).
* The analytic distribution of the source journal items is carried over
  **proportionally** to the fee line and to the credit lines, so the cost
  centre (or the branch) of every sale is preserved.
* Every confirmation stores a `bank.fees.allocation` record (history) that
  can be cancelled: the entry is unreconciled, reversed and the original
  journal items are freed.

---

## Requirements

* **Odoo 20.0** (Community *or* Enterprise).
* The module depends on `account` and `mail` only — **no** Enterprise
  module is required.

---

## Installation

1. Copy the `bank_fees_allocation` folder into your addons path
   (for this server: `/home/admin/custom_addons`).
2. Make sure the folder is readable by the user that runs Odoo.
3. Restart Odoo and install the module from *Apps > Accounting > Bank Fees
   Allocation*, or from the command line:

   ```bash
   odoo -d <your_database> -i bank_fees_allocation --stop-after-init
   ```

   To upgrade an existing installation:

   ```bash
   odoo -d <your_database> -u bank_fees_allocation --stop-after-init
   ```

---

## Configuration

*Accounting > Configuration > Settings > Accounting > Bank Fees Allocation*
(only visible to the **Bank Fees Allocation / Administrator** group).

| Setting | Meaning |
|---|---|
| **Allocation Accounts** | The accounts the accountant works on: the Visa/card clearing accounts. Only the journal items of these accounts show up in the allocation view. A branch may have several of them. |
| **Bank Fees Expense Account** | Where the fee is booked. It **must** be configured, otherwise the allocation cannot be confirmed (the wizard says where to go). |
| **Bank Accounts** | The bank accounts offered **only** inside the wizard. |
| **Allocation Journal** | The journal used by the generated entries. Defaults to the *Miscellaneous* journal of the company. |

All the settings are **company dependent**: each company has its own
configuration.

---

## Usage

1. Open *Accounting > Bank Fees Allocation*.
2. Filter (date range, account, partner, amount) and group the list as you
   need — by account, by day, by branch…
3. Select the journal items of the settlement (they may come from several
   days and several accounts) and click **Bank Fees Allocation** in the list
   header.
4. In the wizard:
   * **Total Amount** is the sum of the selection (read-only);
   * type the **Net Amount** the bank really credited — the **Fee Amount**
     is computed for you;
   * or type the **Fee Amount** — the **Net Amount** is computed for you;
   * pick the **Bank Account**, the **Journal**, the **Date** and the
     **Reference**.
5. Click **Confirm**.

---

## The generated entry

For a `100.00` sale settled at `95.00` with a `5.00` fee, the module posts:

```
Debit   Bank Account                  95.00    <- the net amount
Debit   Bank Fees Expense Account      5.00    <- the fee (analytic carried over)
Credit  Visa / Card clearing         100.00    <- one credit line per source account
```

* one **credit line per source account**: the balances of the items of a
  same account are added up, so several sales of the same account produce a
  single credit line;
* the entry is always **balanced**;
* every credit line is reconciled with the journal items of its own account.

---

## Cancellation

*Accounting > Bank Fees Allocation > Allocations*: open an allocation and
click **Cancel & Reverse**.

* the reconciliation links are removed (through Odoo's own
  `remove_move_reconcile()`);
* the entry is **reversed** by Odoo's own `_reverse_moves()` and the
  reversal is posted;
* the allocation is marked **Cancelled**;
* the original journal items are **free again** and can be allocated anew.

---

## Reports

* **List, pivot and graph** views of the allocations:
  * fees by **bank account**;
  * fees by **period** (day / month);
  * fees by **source account** (branch);
  * fees by **user**.
* Filters: date range, bank account, source account, state.
* **XLSX export**: the *standard list export* of Odoo (select the records
  and use *Export*).
* **PDF summary**: the *Print > Allocation Summary* action of the list /
  form view. It shows the total sales, the total fees, the net amount, and
  the breakdowns per bank account, per period and per source account.

---

## Security

Two groups are created (Odoo 20 `res.groups.privilege` format):

| Group | Rights |
|---|---|
| **Bank Fees Allocation / Administrator** | Everything, including the settings. |
| **Bank Fees Allocation / User** | The accountant: opens the allocation view and runs the wizard. The settings stay read-only (the block is hidden). |

A multi-company record rule restricts the allocations to the companies of
the user.

---

## Technical notes (Odoo 20 APIs)

The module follows the **real** Odoo 20 APIs — nothing from Odoo 16/17 is
assumed:

| Topic | Odoo 20 API used |
|---|---|
| Views | `<list>` (never `<tree>`), `column_invisible`, `optional`, `sum=` |
| Journal item state | `account.move.line.parent_state` (`'posted'`) |
| Reconciliation state | `account.move.line.reconciled` / `full_reconcile_id` |
| Residual | `account.move.line.amount_residual` / `amount_residual_currency` |
| Account flag | `account.account.reconcile` (*Payment Reconciliation*) |
| Posting | `account.move.action_post()` |
| Reconciliation | `account.move.line.reconcile()` / `remove_move_reconcile()` |
| Reversal | `account.move._reverse_moves()` |
| Analytic | `account.move.line.analytic_distribution` (Json) |
| Sequence | `sequence.mixin` (`_set_next_sequence()`, `_get_starting_sequence()`) |
| Groups | `res.groups.privilege` + `res.groups.privilege_id` |
| Access rules | `ir.access` (the `ir.rule` model was merged into `ir.access` in Odoo 20: a record **without** group and **with** a domain is a restriction) |
| Company of a journal | `account.journal.company_id` (a journal has **one** company) |
| Analytic plan | `account.analytic.plan` has **no** `company_id` in Odoo 20 |

Nothing of the core is overridden: the module only **uses** the core APIs.

---

## Folder structure

```
bank_fees_allocation/
├── __init__.py
├── __manifest__.py
├── README.md
├── models/
│   ├── __init__.py
│   ├── account_move_line.py             # the list-header button + the helpers
│   ├── bank_fees_allocation.py          # the history record (sequence, cancel)
│   ├── bank_fees_allocation_line_action.py  # the dynamic window action
│   ├── res_company.py                   # the company configuration
│   └── res_config_settings.py           # the Accounting settings block
├── wizard/
│   ├── __init__.py
│   ├── bank_fees_allocation_wizard.py   # the wizard (compute + inverse)
│   └── bank_fees_allocation_wizard_views.xml
├── reports/
│   ├── __init__.py
│   ├── bank_fees_allocation_report.py   # the helpers of the PDF summary
│   └── bank_fees_allocation_report_templates.xml
├── views/
│   ├── __init__.py (not needed)
│   ├── account_move_line_views.xml      # the button on the core Journal Items list
│   ├── bank_fees_allocation_line_views.xml  # the main view + its search view
│   ├── bank_fees_allocation_menu.xml
│   ├── bank_fees_allocation_views.xml   # the history: list, form, search, pivot, graph
│   └── res_config_settings_views.xml    # the settings block
├── security/
│   ├── bank_fees_allocation_security.xml  # the two groups
│   └── ir.access.csv                    # the rights + the multi-company rule
├── i18n/
│   ├── bank_fees_allocation.pot
│   └── ar_001.po                        # Arabic
└── tests/
    ├── __init__.py
    └── test_bank_fees_allocation.py
```

---

## Tests

The module ships a `TransactionCase` suite covering:

* a single account allocation;
* several accounts (one credit line per account);
* a selection spanning several days;
* the two-way computation of the net amount and the fee;
* the carry-over of the analytic distribution (and its proportionality);
* the reconciliation of every source group;
* the cancel / reverse, and the allocation of the freed lines again;
* the validations (negative amounts, reconciled lines, draft lines, an
  account that is not configured, a missing fee account);
* the access rights (the accountant cannot reach the settings);
* the multi-company rule;
* the report helpers;
* the domain of the allocation view;
* the button of the list header.

Run them with:

```bash
odoo -d <your_database> --stop-after-init --test-enable \
     --test-tags /bank_fees_allocation
```
