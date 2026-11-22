# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    branch_id = fields.Many2one(
        'branch.branch', string='Branch',
        related='move_line_id.branch_id', store=True, readonly=True, index=True,
        help='Branch of the journal item that created this analytic entry. '
             'It follows the branch of the journal entry, so an analytic '
             'report can be cut by branch.',
    )
