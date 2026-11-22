# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo.tools.safe_eval import safe_eval


class Branch(models.Model):
    _name = 'branch.branch'
    _description = 'Branch'
    _order = 'code, name'
    _check_company_auto = True
    _rec_names_search = ('name', 'code')

    # Odoo 20 SQL constraint syntax (``_sql_constraints`` no longer exists).
    _code_company_unique = models.Constraint(
        'UNIQUE(company_id, code)',
        'Branch code must be unique inside its company.',
    )

    # ------------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------------
    name = fields.Char(
        string='Branch Name', required=True, translate=True,
    )
    code = fields.Char(
        required=True,
        help='Short code of the branch, for example BR-RYD. '
             'It must be unique inside the company.',
    )
    active = fields.Boolean(
        default=True,
    )
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company,
    )
    manager_id = fields.Many2one(
        'res.users', string='Manager', check_company=True,
    )
    notes = fields.Text(
        string='Notes',
    )

    # ------------------------------------------------------------------
    # Warehouse and locations (standard Odoo locations only)
    # ------------------------------------------------------------------
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Warehouse', check_company=True,
        domain="[('company_id', '=', company_id)]",
        help='Warehouse of the branch. By default one warehouse belongs to '
             'one branch.',
    )
    default_stock_location_id = fields.Many2one(
        'stock.location', string='Default Stock Location',
        compute='_compute_default_stock_location_id',
        store=True, readonly=False, precompute=True, check_company=True,
        domain="[('usage', '=', 'internal')]",
        help='Internal location used as the default stock location of the '
             'branch. It always belongs to the warehouse of the branch.',
    )
    default_customer_location_id = fields.Many2one(
        'stock.location', string='Default Customer Location', check_company=True,
        domain="[('usage', '=', 'customer')]",
    )
    default_vendor_location_id = fields.Many2one(
        'stock.location', string='Default Vendor Location', check_company=True,
        domain="[('usage', '=', 'supplier')]",
    )

    # ------------------------------------------------------------------
    # Analytic accounting
    # ------------------------------------------------------------------
    analytic_plan_id = fields.Many2one(
        'account.analytic.plan', string='Analytic Plan',
        default=lambda self: self._default_analytic_plan(),
        help='Plan used when the analytic account of the branch is created '
             'automatically.',
    )
    auto_create_analytic = fields.Boolean(
        string='Create Analytic Account Automatically', default=True,
        help='Create an analytic account for the branch as long as the branch '
             'does not have one yet.',
    )
    analytic_account_id = fields.Many2one(
        'account.analytic.account', string='Analytic Account', check_company=True,
        help='Analytic account used by the accounting entries of the branch. '
             'The same analytic account can never be shared by two branches.',
    )

    # ------------------------------------------------------------------
    # Price list of the branch
    # ------------------------------------------------------------------
    pricelist_id = fields.Many2one(
        'product.pricelist', string='Price List', check_company=True,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        help='Price list this branch sells with. The price list of the branch '
             'is proposed on every quotation of the branch and the prices of '
             'its lines follow it. This column holds at most one price list, '
             'so a branch can never belong to two price lists, while one '
             'price list is free to cover as many branches as needed.',
    )

    # ------------------------------------------------------------------
    # Address and contact
    # ------------------------------------------------------------------
    address_id = fields.Many2one(
        'res.partner', string='Address', check_company=True,
    )
    phone = fields.Char(
        string='Phone',
    )
    email = fields.Char(
        string='Email',
    )

    # ------------------------------------------------------------------
    # Computes / defaults
    # ------------------------------------------------------------------
    @api.depends('warehouse_id')
    def _compute_default_stock_location_id(self):
        for branch in self:
            branch.default_stock_location_id = branch.warehouse_id.lot_stock_id

    @api.model
    def _default_analytic_plan(self):
        """Plan of the automatic analytic account of the branches.

        ``account.analytic.plan`` has no company field in Odoo 20, so no
        company domain is used here.
        """
        plan = self.env.ref(
            'branch_management.analytic_plan_branches', raise_if_not_found=False,
        )
        if plan:
            return plan
        return self.env['account.analytic.plan'].sudo().search(
            [], order='sequence, id', limit=1,
        )

    # ------------------------------------------------------------------
    # Automatic analytic account
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        branches = super().create(vals_list)
        branches._ensure_analytic_account()
        # A new branch changes the list of visible branch ids that is embedded
        # in the ir.access domains: those domains are cached, invalidate them.
        self.env['ir.access']._clear_caches()
        return branches

    def write(self, vals):
        res = super().write(vals)
        if {'code', 'name', 'analytic_plan_id', 'auto_create_analytic'} & vals.keys():
            self._ensure_analytic_account()
        return res

    def unlink(self):
        res = super().unlink()
        self.env['ir.access']._clear_caches()
        return res

    def _ensure_analytic_account(self):
        """Create the analytic account of every branch that needs one.

        The account is only created, never overwritten: an account that was
        changed by the user stays untouched.
        """
        # sudo(): the analytic account is a technical consequence of the
        # branch, a Branch Manager may not have the rights to create analytic
        # accounts but still has to get the account of his branches.
        Account = self.env['account.analytic.account'].sudo()
        for branch in self:
            if not branch.auto_create_analytic or branch.analytic_account_id:
                continue
            plan = branch.analytic_plan_id or branch._default_analytic_plan()
            if not plan:
                continue
            account = Account.create({
                'name': _('%(code)s - %(name)s', code=branch.code, name=branch.name),
                'code': branch.code,
                'plan_id': plan.id,
                'company_id': branch.company_id.id,
            })
            branch.analytic_account_id = account

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    @api.constrains('warehouse_id', 'company_id')
    def _check_warehouse_company(self):
        for branch in self:
            if branch.warehouse_id and branch.warehouse_id.company_id != branch.company_id:
                raise ValidationError(_(
                    'The warehouse of the branch "%(branch)s" belongs to another company.',
                    branch=branch.display_name,
                ))

    @api.constrains('analytic_account_id', 'company_id')
    def _check_analytic_account_company(self):
        for branch in self:
            account = branch.analytic_account_id
            if account and account.company_id and account.company_id != branch.company_id:
                raise ValidationError(_(
                    'The analytic account of the branch "%(branch)s" belongs to another company.',
                    branch=branch.display_name,
                ))

    @api.constrains('analytic_account_id')
    def _check_analytic_account_unique(self):
        Branch = self.with_context(active_test=False).sudo()
        for branch in self.filtered('analytic_account_id'):
            other = Branch.search([
                ('id', '!=', branch.id),
                ('analytic_account_id', '=', branch.analytic_account_id.id),
            ], limit=1)
            if other:
                raise ValidationError(_(
                    'The analytic account "%(account)s" is already used by the branch "%(branch)s".',
                    account=branch.analytic_account_id.display_name,
                    branch=other.display_name,
                ))

    @api.constrains('warehouse_id')
    def _check_warehouse_exclusive(self):
        Branch = self.with_context(active_test=False).sudo()
        for branch in self.filtered('warehouse_id'):
            if not branch.company_id.branch_warehouse_exclusive:
                continue
            other = Branch.search([
                ('id', '!=', branch.id),
                ('warehouse_id', '=', branch.warehouse_id.id),
            ], limit=1)
            if other:
                raise ValidationError(_(
                    'The warehouse "%(warehouse)s" is already linked to the branch "%(branch)s". '
                    'Deactivate "One Warehouse = One Branch" on the company to allow it.',
                    warehouse=branch.warehouse_id.display_name,
                    branch=other.display_name,
                ))

    # ------------------------------------------------------------------
    # Smart buttons (documents of the branch)
    # ------------------------------------------------------------------
    # No ``@api.depends()``: nothing inside the branch changes when a document
    # is created. The fields are not stored, so they are computed on read,
    # which keeps the counters of the form up to date and costs nothing on the
    # list view, where they are not used.
    sale_count = fields.Integer(compute='_compute_document_counts')
    picking_count = fields.Integer(compute='_compute_document_counts')
    invoice_count = fields.Integer(compute='_compute_document_counts')

    def _compute_document_counts(self):
        for branch in self:
            branch.sale_count = self._count_records(
                'sale.order', [('branch_id', '=', branch.id)])
            branch.picking_count = self._count_records(
                'stock.picking', [('branch_id', '=', branch.id)])
            branch.invoice_count = self._count_records(
                'account.move',
                [('branch_id', '=', branch.id), ('move_type', '!=', 'entry')],
            )

    @api.model
    def _count_records(self, model_name, domain):
        """Count the records of ``model_name`` matching ``domain``.

        The counters are read with the rights of the user opening the form.
        A user without any right on the model (a Branch Administrator without
        the Invoicing group, for instance) gets 0 instead of an AccessError:
        the form of a branch must stay readable by everybody.
        """
        Model = self.env[model_name]
        if not Model.has_access('read'):
            return 0
        return Model.search_count(domain)

    def action_view_sale_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sales Orders'),
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': [('branch_id', '=', self.id)],
            'context': {'default_branch_id': self.id},
        }

    def action_view_pickings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Transfers'),
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'domain': [('branch_id', '=', self.id)],
            'context': {'default_branch_id': self.id},
        }

    def action_view_invoices(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Invoices'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('branch_id', '=', self.id), ('move_type', '!=', 'entry')],
            'context': {'default_branch_id': self.id},
        }

    def action_view_sale_analysis(self):
        """Open the sales analysis report, limited to this branch."""
        self.ensure_one()
        action = dict(self.env['ir.actions.act_window']._for_xml_id(
            'sale.action_order_report_all'))
        # the domain of an action is stored as a string; keep the conditions
        # already set by the standard action (state != cancel, ...) and only
        # add the branch to them.
        domain = action.get('domain') or '[]'
        if isinstance(domain, str):
            domain = safe_eval(domain)
        action['domain'] = list(
            Domain(domain) & Domain([('branch_id', '=', self.id)]))
        return action
