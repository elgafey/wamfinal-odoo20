# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    branch_id = fields.Many2one(
        'branch.branch', string='Branch',
        related='move_id.branch_id', store=True, readonly=True, index=True,
        help='Branch of the journal entry this line belongs to.',
    )

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        """Apply the branch to the lines created with a distribution.

        When the distribution is given in the values (an invoice line that
        takes the distribution of its sales order line), the compute method
        of Odoo is not called, so the merge is done here. On the other lines
        the compute method already does it, and this call changes nothing.
        """
        lines = super().create(vals_list)
        for line in lines:
            line._merge_branch_analytic_distribution()
        return lines

    # ------------------------------------------------------------------
    # Analytic distribution of the branch
    # ------------------------------------------------------------------
    @api.depends('move_id.branch_id', 'company_id.branch_analytic_auto',
                 'move_id.branch_id.analytic_account_id')
    def _compute_analytic_distribution(self):
        """Give the analytic account of the branch to the journal items.

        Odoo collects the ``@api.depends`` of every implementation of the
        compute method found along the model hierarchy, so the dependencies
        of the core method (``account_id``, ``partner_id``, ``product_id``)
        are kept and ours are added.
        """
        super()._compute_analytic_distribution()
        for line in self:
            line._merge_branch_analytic_distribution()

    def _merge_branch_analytic_distribution(self):
        """Add the analytic account of the branch to the distribution.

        The merge is done carefully:

        * the switch of the company is off   -> nothing changes,
        * the line carries no account (section, note) -> nothing changes,
        * the entry has no branch, or its branch has no analytic account ->
          the analytic accounts owned by a branch are *removed*, they
          describe a branch this entry does not have,
        * the plan of the branches is already used by an account of another
          branch -> that account is replaced by the account of this branch,
        * the plan of the branches is already used for anything else ->
          the distribution is left untouched,
        * otherwise the account of the branch is added to every key of the
          distribution: the percentages do not change, so the total of each
          analytic plan stays valid.

        Every line that carries an account receives it. On an invoice that
        is the income line, but also the receivable line, the tax lines and
        the payment term lines; outside an invoice it is also the bank and
        the payable lines of a payment or of a miscellaneous entry. A journal
        entry with a branch therefore carries the analytic account of that
        branch on *each* of its lines, and so does every analytic item made
        from them.

        The method works on a single line.
        """
        self.ensure_one()
        if not self.company_id.branch_analytic_auto:
            return
        if not self.account_id:
            return
        move = self.move_id
        account = move.branch_id.analytic_account_id
        if not account:
            self._drop_branch_analytic_accounts()
            return

        distribution = dict(self.analytic_distribution or {})
        if not distribution:
            self.analytic_distribution = {str(account.id): 100.0}
            return

        ids_by_key = {
            key: {int(account_id) for account_id in key.split(',') if account_id.strip()}
            for key in distribution
        }
        used_ids = set().union(*ids_by_key.values())
        if account.id in used_ids:
            return

        used_accounts = self.env['account.analytic.account'].browse(
            sorted(used_ids)).exists()
        same_plan = used_accounts.filtered(
            lambda used: used.root_plan_id == account.root_plan_id)

        if not same_plan:
            # the plan of the branches is free: add our account to every key
            self.analytic_distribution = {
                ','.join(str(account_id) for account_id in sorted(ids | {account.id})):
                    percentage
                for key, percentage in distribution.items()
                for ids in [ids_by_key[key]]
            }
            return

        # the plan is already used: replace the account of another branch,
        # leave anything else alone
        old_branch_accounts = self.env['branch.branch'].sudo().search(
            [('analytic_account_id', 'in', same_plan.ids)],
        ).mapped('analytic_account_id')
        if not old_branch_accounts:
            return
        replaced = set(old_branch_accounts.ids)
        merged = {}
        for key, percentage in distribution.items():
            ids = {(account.id if used in replaced else used)
                   for used in ids_by_key[key]}
            merged_key = ','.join(str(account_id) for account_id in sorted(ids))
            merged[merged_key] = merged.get(merged_key, 0.0) + percentage
        self.analytic_distribution = merged

    def _drop_branch_analytic_accounts(self):
        """Remove the analytic accounts owned by a branch from the
        distribution of this line.

        The distribution of a journal item mirrors the branch of its entry:
        when the branch is taken away, the account that was put there for it
        has to go too, otherwise the analytic items built from this line
        keep describing a branch the entry no longer has. Only the accounts
        owned by a branch are dropped: an account of the branch plan that
        belongs to no branch was put there by the user and is not ours to
        remove. The method works on a single line.
        """
        distribution = dict(self.analytic_distribution or {})
        if not distribution:
            return
        ids_by_key = {
            key: {int(account_id) for account_id in key.split(',') if account_id.strip()}
            for key in distribution
        }
        used_ids = set().union(*ids_by_key.values())
        branch_accounts = set(self.env['branch.branch'].sudo().search(
            [('analytic_account_id', 'in', sorted(used_ids))],
        ).mapped('analytic_account_id').ids)
        if not used_ids & branch_accounts:
            return
        merged = {}
        for key, percentage in distribution.items():
            kept = ids_by_key[key] - branch_accounts
            if not kept:
                continue            # this key only described a branch
            kept_key = ','.join(str(account_id) for account_id in sorted(kept))
            merged[kept_key] = merged.get(kept_key, 0.0) + percentage
        self.analytic_distribution = merged or False

    # ------------------------------------------------------------------
    # Refresh of the analytic items
    # ------------------------------------------------------------------
    def _reapply_branch_analytic(self, snapshot=None):
        """Recompute the distribution of these journal items and rebuild the
        analytic items of the posted ones.

        Two situations need it:

        * the branch of the entry was just written. The distribution of the
          journal items is a stored computed field that depends on
          ``account.move.branch_id``, so Odoo recomputes it, but a
          recomputation is not a write made by the user: the inverse method
          that creates the analytic items is never called. The entry keeps
          its analytic items of before, or keeps none at all when it was
          posted without a branch;
        * the entries that already existed when this module was installed:
          their distributions were computed without the branch of the entry
          and nothing recomputes them by itself.

        The recomputation itself is left to Odoo: the field is marked as "to
        compute" and read back, which puts the new value in the cache, where
        the flush writes it. Only the analytic items are rebuilt here, and
        only for the lines whose distribution really changed.

        :param dict snapshot: value of the distribution *before* the change.
            It is read here when it is not given, which is the second
            situation above, where nothing has been written yet.
        """
        lines = self.exists().filtered(lambda line: line.account_id)
        if not lines:
            return
        if snapshot is None:
            snapshot = {line.id: line.analytic_distribution for line in lines}
        field = self.env['account.move.line']._fields['analytic_distribution']
        self.env.add_to_compute(field, lines)

        def changed(line):
            old = snapshot.get(line.id) or False
            new = line.analytic_distribution or False
            return old != new

        posted = lines.filtered(lambda line: line.parent_state == 'posted')
        to_sync = posted.filtered(changed)
        # a posted line that has a distribution but no analytic item at all
        # is restored as well: this is what an entry posted before the
        # branch was ever known looks like
        missing = posted.filtered(
            lambda line: line.analytic_distribution and not line.analytic_line_ids)
        to_sync |= missing
        if not to_sync:
            return
        # ``skip_analytic_sync`` is essential: removing an analytic item
        # makes Odoo call ``_update_analytic_distribution()``, which reads
        # the distribution back from the analytic items that were just
        # removed and empties it, so nothing would ever be created again.
        to_sync.analytic_line_ids.with_context(skip_analytic_sync=True).unlink()
        to_sync.filtered(lambda line: line.analytic_distribution)._create_analytic_lines()
