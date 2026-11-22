# -*- coding: utf-8 -*-
from datetime import datetime, time, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.sql import column_exists

# Locations considered as "our own stock" (same rule as Odoo: a move is incoming
# when its destination is one of these and its source is not, outgoing otherwise).
INTERNAL_USAGES = ('internal', 'transit')

# All the SQL is done on stock_move, the table behind
# Inventory > Reporting > Moves Analysis.
# ``stock_move.value`` only exists once ``stock_account`` is installed, which
# Odoo auto-installs when accounting is present. The token below is replaced by
# the safe expression ``COALESCE(ABS(move.value), 0)`` when the column is there,
# and by ``0`` otherwise, so the report still runs on a bare inventory database.
BALANCE_QUERY = """
    SELECT
        result.product_id,
        result.opening,
        result.qty_in,
        result.qty_out,
        result.opening + result.qty_in - result.qty_out AS closing,
        result.opening_value,
        result.value_in,
        result.value_out,
        result.opening_value + result.value_in - result.value_out AS closing_value
    FROM (
        SELECT
            flows.product_id,
            SUM(CASE
                WHEN flows.date < %(date_from)s THEN flows.direction * flows.qty
                ELSE 0
            END) AS opening,
            SUM(CASE
                WHEN flows.date >= %(date_from)s AND flows.date < %(date_to)s
                     AND flows.direction > 0
                THEN flows.qty
                ELSE 0
            END) AS qty_in,
            SUM(CASE
                WHEN flows.date >= %(date_from)s AND flows.date < %(date_to)s
                     AND flows.direction < 0
                THEN flows.qty
                ELSE 0
            END) AS qty_out,
            SUM(CASE
                WHEN flows.date < %(date_from)s THEN flows.direction * flows.val
                ELSE 0
            END) AS opening_value,
            SUM(CASE
                WHEN flows.date >= %(date_from)s AND flows.date < %(date_to)s
                     AND flows.direction > 0
                THEN flows.val
                ELSE 0
            END) AS value_in,
            SUM(CASE
                WHEN flows.date >= %(date_from)s AND flows.date < %(date_to)s
                     AND flows.direction < 0
                THEN flows.val
                ELSE 0
            END) AS value_out
        FROM (
            SELECT
                move.product_id,
                move.date,
                move.quantity * uom_move.factor / uom_product.factor AS qty,
                __MOVE_VALUE__ AS val,
                CASE
                    WHEN src.usage IN %(internal_usages)s THEN -1
                    ELSE 1
                END AS direction
            FROM stock_move move
                INNER JOIN stock_location src ON src.id = move.location_id
                INNER JOIN stock_location dst ON dst.id = move.location_dest_id
                INNER JOIN product_product pp ON pp.id = move.product_id
                INNER JOIN product_template pt ON pt.id = pp.product_tmpl_id
                INNER JOIN uom_uom uom_move ON uom_move.id = move.uom_id
                INNER JOIN uom_uom uom_product ON uom_product.id = pt.uom_id
            WHERE move.state = 'done'
                AND move.company_id = %(company_id)s
                AND move.date < %(date_to)s
                AND (src.usage IN %(internal_usages)s) <> (dst.usage IN %(internal_usages)s)
        ) flows
        GROUP BY flows.product_id
    ) result
        INNER JOIN product_product pp ON pp.id = result.product_id
    WHERE result.opening <> 0 OR result.qty_in <> 0 OR result.qty_out <> 0
    ORDER BY (COALESCE(pp.default_code, '') = ''), COALESCE(pp.default_code, ''),
             result.product_id
"""


class StockBalanceReport(models.Model):
    _name = 'stock.balance.report'
    _description = 'Stock Balance Report'

    date_from = fields.Date(
        string='From Date', required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date(
        string='To Date', required=True,
        default=fields.Date.context_today)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company)
    line_ids = fields.One2many(
        'stock.balance.report.line', 'report_id', string='Lines')

    product_count = fields.Integer(string='Products', compute='_compute_totals')
    total_opening = fields.Float(
        string='Total Opening Balance', compute='_compute_totals',
        digits='Product Unit')
    total_in = fields.Float(
        string='Total IN', compute='_compute_totals', digits='Product Unit')
    total_out = fields.Float(
        string='Total OUT', compute='_compute_totals', digits='Product Unit')
    total_closing = fields.Float(
        string='Total Closing Balance', compute='_compute_totals',
        digits='Product Unit')

    # Money side of the same four columns, summed from the same lines.
    total_opening_value = fields.Float(
        string='Total Opening Value', compute='_compute_totals',
        digits='Product Price')
    total_in_value = fields.Float(
        string='Total IN Value', compute='_compute_totals',
        digits='Product Price')
    total_out_value = fields.Float(
        string='Total OUT Value', compute='_compute_totals',
        digits='Product Price')
    total_closing_value = fields.Float(
        string='Total Closing Value', compute='_compute_totals',
        digits='Product Price')

    # ------------------------------------------------------------------
    # Constraints / computed
    # ------------------------------------------------------------------
    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for report in self:
            if report.date_from and report.date_to and report.date_from > report.date_to:
                raise UserError(_('The "To" date must be greater than or equal to the "From" date.'))

    @api.depends('line_ids', 'line_ids.opening_qty', 'line_ids.in_qty',
                 'line_ids.out_qty', 'line_ids.closing_qty',
                 'line_ids.opening_value', 'line_ids.in_value',
                 'line_ids.out_value', 'line_ids.closing_value')
    def _compute_totals(self):
        for report in self:
            lines = report.line_ids
            report.product_count = len(lines)
            report.total_opening = sum(lines.mapped('opening_qty'))
            report.total_in = sum(lines.mapped('in_qty'))
            report.total_out = sum(lines.mapped('out_qty'))
            report.total_closing = sum(lines.mapped('closing_qty'))
            report.total_opening_value = sum(lines.mapped('opening_value'))
            report.total_in_value = sum(lines.mapped('in_value'))
            report.total_out_value = sum(lines.mapped('out_value'))
            report.total_closing_value = sum(lines.mapped('closing_value'))

    @api.depends('date_from', 'date_to')
    def _compute_display_name(self):
        for report in self:
            report.display_name = '%s → %s' % (
                report.date_from or '', report.date_to or '')

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_show(self):
        """Run the SQL query and fill the lines.

        Returning True makes the web client close the (non dialog) action and
        reload the form, so the new lines are displayed.
        """
        self.ensure_one()
        lines_values = self._get_lines_values()
        self.line_ids.unlink()
        if lines_values:
            self.env['stock.balance.report.line'].create(
                [dict(values, report_id=self.id) for values in lines_values])
        return True

    def action_print_pdf(self):
        """Return the PDF report action of the displayed report.

        ``config=False`` avoids the "document layout" configurator popping up
        for administrators: the report carries its own header/footer design.
        """
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('There is no data to print. Please display the report first.'))
        report = self.env['ir.actions.report']._get_report(
            'stock_balance_report.action_report_stock_balance')
        return report.report_action(self.id, config=False)

    def action_open_list(self):
        """Open the lines as a standalone list view.

        A list view opened as a full screen action gives access to Odoo's
        standard "Export" button (Excel / CSV).
        """
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Please display the report before opening it as a list.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Stock Balance'),
            'res_model': 'stock.balance.report.line',
            'view_mode': 'list',
            'domain': [('report_id', '=', self.id)],
            'context': {'default_report_id': self.id},
            'target': 'current',
        }

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    def _get_lines_values(self):
        """Return the list of values (one dict per product) of the report."""
        self.ensure_one()
        date_from = datetime.combine(self.date_from, time.min)
        date_to = datetime.combine(self.date_to + timedelta(days=1), time.min)
        # Same rules as the quantities: one expression, one query, one pass.
        value_expr = ("COALESCE(ABS(move.value), 0)"
                      if column_exists(self.env.cr, 'stock_move', 'value')
                      else "0")
        self.env.cr.execute(BALANCE_QUERY.replace('__MOVE_VALUE__', value_expr), {
            'date_from': date_from,
            'date_to': date_to,
            'company_id': self.company_id.id,
            'internal_usages': INTERNAL_USAGES,
        })
        values = []
        for row in self.env.cr.dictfetchall():
            values.append({
                'product_id': row['product_id'],
                'opening_qty': float(row['opening'] or 0),
                'in_qty': float(row['qty_in'] or 0),
                'out_qty': float(row['qty_out'] or 0),
                'closing_qty': float(row['closing'] or 0),
                'opening_value': float(row['opening_value'] or 0),
                'in_value': float(row['value_in'] or 0),
                'out_value': float(row['value_out'] or 0),
                'closing_value': float(row['closing_value'] or 0),
            })
        return values


class StockBalanceReportLine(models.Model):
    _name = 'stock.balance.report.line'
    _description = 'Stock Balance Report Line'
    _order = 'id'

    report_id = fields.Many2one(
        'stock.balance.report', string='Report', required=True,
        ondelete='cascade', index=True)
    product_id = fields.Many2one(
        'product.product', string='Product', required=True, index=True)
    default_code = fields.Char(
        string='Internal Reference', related='product_id.default_code',
        store=True)
    uom_id = fields.Many2one('uom.uom', string='Unit',
                             related='product_id.uom_id')
    opening_qty = fields.Float(
        string='Opening Balance', digits='Product Unit')
    in_qty = fields.Float(string='IN', digits='Product Unit')
    out_qty = fields.Float(string='OUT', digits='Product Unit')
    closing_qty = fields.Float(
        string='Closing Balance', digits='Product Unit')

    # Money counterpart of the four quantities above. Each value sits right
    # after the quantity it belongs to, and is summed exactly like it.
    opening_value = fields.Float(
        string='Opening Value', digits='Product Price')
    in_value = fields.Float(string='IN Value', digits='Product Price')
    out_value = fields.Float(string='OUT Value', digits='Product Price')
    closing_value = fields.Float(
        string='Closing Value', digits='Product Price')
