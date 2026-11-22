# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    branch_analytic_auto = fields.Boolean(
        string='Automatic Branch Analytic Distribution',
        default=True,
        help='Apply the analytic account of the branch to the journal items '
             'of the branch, on the lines that carry a product (income and '
             'expense lines). The account of the branch is added to the '
             'distribution already set, without changing its percentages.',
    )
    branch_warehouse_exclusive = fields.Boolean(
        string='One Warehouse = One Branch',
        default=True,
        help='Prevent one warehouse from being linked to more than one branch.',
    )
