# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AccountMove(models.Model):
    _inherit = 'account.move'

    branch_id = fields.Many2one(
        'branch.branch', string='Branch',
        domain=lambda self: [
            ('id', 'in', self.env.user.with_context(active_test=False).branch_visible_ids.ids),
        ],
        index=True, check_company=True, tracking=True, copy=True,
        help='Branch of the company this journal entry belongs to. It comes '
             'from the sales order (invoice and down payment) and is kept by '
             'the credit notes, which are created with a copy of the entry. '
             'It drives the branch of the journal items and their analytic '
             'distribution.',
    )

    # ------------------------------------------------------------------
    # The journal decides the branch
    # ------------------------------------------------------------------
    def _branch_of_journals(self, journal_ids):
        """Map ``{journal_id: branch_id}`` for the given journals."""
        journals = self.env['account.journal'].browse(list(journal_ids))
        return {journal.id: journal.branch_id.id for journal in journals}

    @api.model_create_multi
    def create(self, vals_list):
        """An entry created in the journal of a branch lands on that branch.

        The value is filled *before* the entry is written, so the journal
        items receive their analytic distribution with the right branch
        from the very first computation. An entry that is given another
        branch on purpose is not corrected here: the constraint below turns
        it into a clear error instead.
        """
        journal_branch = self._branch_of_journals(
            vals['journal_id'] for vals in vals_list if vals.get('journal_id')
        )
        for vals in vals_list:
            branch_id = journal_branch.get(vals.get('journal_id'))
            if branch_id and not vals.get('branch_id'):
                vals['branch_id'] = branch_id
        moves = super().create(vals_list)
        # safety net: the core also picks the journal on its own (a default
        # chosen for the form, or a computed journal when the document type
        # changes), and that journal never appears in the values given to
        # ``create``.
        for move in moves:
            if move.journal_id.branch_id and not move.branch_id:
                move.branch_id = move.journal_id.branch_id
        return moves

    @api.onchange('journal_id')
    def _onchange_journal_branch(self):
        """Show the branch of the journal as soon as it is selected."""
        if self.journal_id.branch_id:
            self.branch_id = self.journal_id.branch_id

    @api.constrains('branch_id', 'journal_id')
    def _check_branch_matches_journal(self):
        """The journal of an entry may only belong to its branch.

        This is the rule that makes every branch independent with its own
        journals: whatever path brought the two values together — the form,
        an import, the copy of an entry, a script or the entry created by
        Odoo itself — they are checked here, once, at write time.
        """
        for move in self:
            journal_branch = move.journal_id.branch_id
            if journal_branch and move.branch_id != journal_branch:
                raise ValidationError(_(
                    'The journal "%(journal)s" belongs to the branch '
                    '"%(journal_branch)s": every entry recorded in it must '
                    'be on that branch. This entry is on "%(entry_branch)s". '
                    'Choose another journal, or move the entry to the '
                    'branch of the journal.',
                    journal=move.journal_id.display_name,
                    journal_branch=journal_branch.display_name,
                    entry_branch=move.branch_id.display_name or _('No branch'),
                ))

    def write(self, vals):
        """Rebuild the analytic items when the branch of the entry changes.

        ``analytic_distribution`` on the journal items is a stored computed
        field that depends on ``branch_id``, so Odoo recomputes it as soon as
        the branch is written. But a recomputation is not a write made by the
        user: ``_inverse_analytic_distribution``, the core method that drops
        and recreates the analytic items of the posted lines, is only called
        when the distribution itself is written. Without this hook an entry
        that receives its branch after being posted would keep an empty
        analytic, and an entry whose branch is replaced would keep analytic
        items of the previous branch.

        The values of the distribution are read *before* the change: after
        the write they would already be the new ones, and nothing could be
        compared.

        Moving an entry to another journal moves it to the branch of that
        journal too — unless the caller is putting a branch on the entry at
        the same time, which the constraint then checks against the journal.
        A journal without a branch imposes nothing and leaves the branch of
        the entry untouched.
        """
        if 'journal_id' in vals and 'branch_id' not in vals:
            journal_branch = self.env['account.journal'].browse(
                vals['journal_id']
            ).branch_id
            if journal_branch:
                vals = dict(vals, branch_id=journal_branch.id)
        if 'branch_id' not in vals:
            return super().write(vals)
        # the values before the change: once the write is done they are
        # already the new ones, and there would be nothing left to compare
        snapshot = {line.id: line.analytic_distribution for line in self.line_ids}
        res = super().write(vals)
        # the journal items may have been rebuilt by the synchronization of
        # the core while writing, so the lines are read again: a line that
        # was destroyed is simply not in the snapshot any more, and a line
        # created in the meantime is not in it either, which is what makes
        # it look like an empty distribution to refresh.
        self.line_ids._reapply_branch_analytic(snapshot)
        return res
