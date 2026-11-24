# -*- coding: utf-8 -*-
"""Printing helpers of the allocation summary.

The XLSX export of the allocations is the **standard list export** of
Odoo (the *Export* button of the list view), so nothing has to be written
here for it: the list view of ``bank.fees.allocation`` exports the
selected records to XLSX out of the box.

This file only holds the helpers used by the QWeb PDF summary:

* the totals (sales, fees, net) of the printed allocations;
* the breakdown per bank account;
* the breakdown per period (day and month).
"""

from odoo import _, models
from odoo.tools import groupby


class BankFeesAllocationReport(models.AbstractModel):
    """ Helpers of the Bank Fees Allocation PDF summary. """

    _name = 'bank.fees.allocation.report'
    _description = 'Bank Fees Allocation Report'

    # ------------------------------------------------------------------
    # Totals
    # ------------------------------------------------------------------
    def _report_totals(self, allocations):
        """ Totals of the printed allocations.

        :param allocations: a recordset of ``bank.fees.allocation``.
        :return: a dictionary with the total sales, the total fees, the
                 total net and the currency.
        """
        allocations = allocations.exists()
        currency = allocations[:1].currency_id or self.env.company.currency_id
        return {
            'currency': currency,
            'total_sales': sum(allocations.mapped('total_amount')),
            'total_fees': sum(allocations.mapped('fee_amount')),
            'total_net': sum(allocations.mapped('net_amount')),
            'count': len(allocations),
        }

    # ------------------------------------------------------------------
    # Breakdown per bank account
    # ------------------------------------------------------------------
    def _report_by_bank_account(self, allocations):
        """ Breakdown of the fees per bank account.

        :return: a list of dictionaries sorted by the total fees.
        """
        allocations = allocations.exists()
        rows = []
        for bank_account, lines in groupby(allocations, lambda a: a.bank_account_id):
            rows.append({
                'bank_account': bank_account,
                'total_sales': sum(line.total_amount for line in lines),
                'total_fees': sum(line.fee_amount for line in lines),
                'total_net': sum(line.net_amount for line in lines),
                'count': len(lines),
            })
        rows.sort(key=lambda row: row['total_fees'], reverse=True)
        return rows

    # ------------------------------------------------------------------
    # Breakdown per period
    # ------------------------------------------------------------------
    def _report_by_day(self, allocations):
        """ Breakdown of the fees per day.

        :return: a list of dictionaries sorted by the date.
        """
        allocations = allocations.exists()
        rows = []
        for date, lines in groupby(allocations, lambda a: a.date):
            rows.append({
                'date': date,
                'total_sales': sum(line.total_amount for line in lines),
                'total_fees': sum(line.fee_amount for line in lines),
                'total_net': sum(line.net_amount for line in lines),
                'count': len(lines),
            })
        rows.sort(key=lambda row: row['date'] or '')
        return rows

    def _report_by_month(self, allocations):
        """ Breakdown of the fees per month.

        :return: a list of dictionaries sorted by the month.
        """
        allocations = allocations.exists()
        buckets = {}
        for allocation in allocations:
            if not allocation.date:
                continue
            key = (allocation.date.year, allocation.date.month)
            row = buckets.setdefault(key, {
                'label': allocation.date.strftime('%m/%Y'),
                'date': allocation.date,
                'total_sales': 0.0,
                'total_fees': 0.0,
                'total_net': 0.0,
                'count': 0,
            })
            row['total_sales'] += allocation.total_amount
            row['total_fees'] += allocation.fee_amount
            row['total_net'] += allocation.net_amount
            row['count'] += 1
        return [buckets[key] for key in sorted(buckets)]

    # ------------------------------------------------------------------
    # Breakdown per source account (branch)
    # ------------------------------------------------------------------
    def _report_by_account(self, allocations):
        """ Breakdown of the fees per source account.

        The source accounts are read from the allocated journal items, so
        the breakdown follows the branches (a branch has its own card
        clearing account).

        :return: a list of dictionaries sorted by the total fees.
        """
        allocations = allocations.exists()
        rows = {}
        for allocation in allocations:
            for account in allocation.line_ids.mapped('account_id'):
                row = rows.get(account.id, {
                    'account': account,
                    'total_sales': 0.0,
                    'total_fees': 0.0,
                    'total_net': 0.0,
                    'count': 0,
                })
                row['total_sales'] += allocation.total_amount
                row['total_fees'] += allocation.fee_amount
                row['total_net'] += allocation.net_amount
                row['count'] += 1
                rows[account.id] = row
        result = list(rows.values())
        result.sort(key=lambda row: row['total_fees'], reverse=True)
        return result

    # ------------------------------------------------------------------
    # Helpers used by the template
    # ------------------------------------------------------------------
    def _report_title(self, allocations):
        """ Title of the report. """
        return _("Bank Fees Allocation Summary")

    def _report_period(self, allocations):
        """ Period covered by the printed allocations.

        :return: a tuple of dates ``(date_from, date_to)``.
        """
        dates = allocations.exists().mapped('date')
        dates = [date for date in dates if date]
        if not dates:
            return False, False
        return min(dates), max(dates)
