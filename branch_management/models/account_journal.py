# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    branch_id = fields.Many2one(
        'branch.branch', string='Branch',
        domain=lambda self: [
            ('id', 'in', self.env.user.with_context(active_test=False).branch_visible_ids.ids),
        ],
        index=True, check_company=True, tracking=True, copy=True,
        help='Branch this journal belongs to. The journal is the source of '
             'truth for the branch of an entry: an entry recorded in this '
             'journal automatically lands on this branch, and an entry on '
             'another branch is refused. A journal without a branch is a '
             'shared journal and stays visible to every user.',
    )
