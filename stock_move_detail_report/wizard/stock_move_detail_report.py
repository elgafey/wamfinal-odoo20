# -*- coding: utf-8 -*-
from datetime import datetime, time, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Safety net: the detail report creates one database record per move, so a
# careless period must not be allowed to freeze the server.
MAX_MOVES = 50000

# The report is computed on the selected location *and* all of its
# sub-locations. A move crosses the boundary of that subtree when exactly one
# of its two endpoints is inside it; such a move is incoming when the
# destination is the inside, outgoing when the source is. Moves staying
# entirely inside the subtree are internal transfers and are not shown, and
# moves staying entirely outside are none of our business.
# ``__PRODUCT_FILTER__`` is replaced by an empty string, or by an extra
# ``AND move.product_id = ...`` predicate when a single product is requested.
MOVES_QUERY = """
    SELECT
        move.id AS move_id,
        move.date AS move_date,
        COALESCE(NULLIF(move.reference, ''), move.origin, '') AS move_name,
        move.product_id,
        CASE WHEN dst.id = ANY(%(location_ids)s) THEN 1 ELSE -1 END AS direction,
        COALESCE(move.quantity, 0) * uom_move.factor / uom_product.factor AS qty,
        CASE WHEN dst.id = ANY(%(location_ids)s)
             THEN src.complete_name
             ELSE dst.complete_name
        END AS counterpart
    FROM stock_move move
        INNER JOIN stock_location src ON src.id = move.location_id
        INNER JOIN stock_location dst ON dst.id = move.location_dest_id
        INNER JOIN product_product pp ON pp.id = move.product_id
        INNER JOIN product_template pt ON pt.id = pp.product_tmpl_id
        INNER JOIN uom_uom uom_move ON uom_move.id = move.uom_id
        INNER JOIN uom_uom uom_product ON uom_product.id = pt.uom_id
    WHERE move.state = 'done'
        AND move.company_id = %(company_id)s
        AND move.date >= %(date_from)s
        AND move.date < %(date_to)s
        AND (src.id = ANY(%(location_ids)s)) <> (dst.id = ANY(%(location_ids)s))
        __PRODUCT_FILTER__
    ORDER BY move.product_id, move.date, move.id
"""

# Same rule, same query, but everything that happened before the From date and
# grouped by product: that is the opening balance shown on the first line of
# each product. The product list is never empty when this query runs, because
# it is built from the rows returned by MOVES_QUERY.
OPENING_QUERY = """
    SELECT
        move.product_id,
        SUM(CASE WHEN dst.id = ANY(%(location_ids)s) THEN 1 ELSE -1 END
            * COALESCE(move.quantity, 0)
            * uom_move.factor / uom_product.factor) AS opening
    FROM stock_move move
        INNER JOIN stock_location src ON src.id = move.location_id
        INNER JOIN stock_location dst ON dst.id = move.location_dest_id
        INNER JOIN product_product pp ON pp.id = move.product_id
        INNER JOIN product_template pt ON pt.id = pp.product_tmpl_id
        INNER JOIN uom_uom uom_move ON uom_move.id = move.uom_id
        INNER JOIN uom_uom uom_product ON uom_product.id = pt.uom_id
    WHERE move.state = 'done'
        AND move.company_id = %(company_id)s
        AND move.date < %(date_from)s
        AND (src.id = ANY(%(location_ids)s)) <> (dst.id = ANY(%(location_ids)s))
        AND move.product_id = ANY(%(product_ids)s)
    GROUP BY move.product_id
"""


class StockMoveDetailReport(models.Model):
    _name = 'stock.move.detail.report'
    _description = 'Stock Move Detail Report'

    date_from = fields.Date(
        string='From Date', required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date(
        string='To Date', required=True,
        default=fields.Date.context_today)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company)
    location_id = fields.Many2one(
        'stock.location', string='Location', required=True,
        domain=[('usage', '=', 'internal')])
    product_id = fields.Many2one(
        'product.product', string='Product',
        domain=[('is_storable', '=', True)],
        help='Leave it empty to get every product of the location.')
    line_ids = fields.One2many(
        'stock.move.detail.report.line', 'report_id', string='Lines')

    product_count = fields.Integer(string='Products', compute='_compute_totals')
    move_count = fields.Integer(string='Moves', compute='_compute_totals')
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

    # ------------------------------------------------------------------
    # Constraints / computed
    # ------------------------------------------------------------------
    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for report in self:
            if report.date_from and report.date_to and report.date_from > report.date_to:
                raise UserError(_('The "To" date must be greater than or equal to the "From" date.'))

    @api.constrains('location_id')
    def _check_location(self):
        """The balance only makes sense on a real storage location."""
        for report in self:
            if report.location_id and report.location_id.usage != 'internal':
                raise UserError(_(
                    'The location "%s" is not an internal location. '
                    'Please choose a location whose usage is "Internal Storage".'
                ) % report.location_id.complete_name)

    @api.depends('line_ids', 'line_ids.is_opening', 'line_ids.qty_in',
                 'line_ids.qty_out')
    def _compute_totals(self):
        for report in self:
            lines = report.line_ids
            opening_lines = lines.filtered('is_opening')
            report.product_count = len(opening_lines)
            report.move_count = len(lines) - len(opening_lines)
            report.total_opening = sum(opening_lines.mapped('balance'))
            report.total_in = sum(lines.mapped('qty_in'))
            report.total_out = sum(lines.mapped('qty_out'))
            report.total_closing = (
                report.total_opening + report.total_in - report.total_out)

    @api.depends('date_from', 'date_to', 'location_id')
    def _compute_display_name(self):
        for report in self:
            report.display_name = '%s · %s → %s' % (
                report.location_id.complete_name or '',
                report.date_from or '', report.date_to or '')

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_show(self):
        """Run the SQL queries and fill the lines.

        Returning True makes the web client close the (non dialog) action and
        reload the form, so the new lines are displayed.
        """
        self.ensure_one()
        lines_values = self._get_lines_values()
        self.line_ids.unlink()
        if lines_values:
            self.env['stock.move.detail.report.line'].create(
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
            'stock_move_detail_report.action_report_stock_move_detail')
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
            'name': _('Stock Move Detail'),
            'res_model': 'stock.move.detail.report.line',
            'view_mode': 'list',
            'domain': [('report_id', '=', self.id)],
            'context': {'default_report_id': self.id},
            'target': 'current',
        }

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    def _get_lines_values(self):
        """Return the list of values (one dict per line) of the report."""
        self.ensure_one()
        date_from = datetime.combine(self.date_from, time.min)
        date_to = datetime.combine(self.date_to + timedelta(days=1), time.min)
        # The subtree of the location: the location itself and every child.
        location_ids = self.env['stock.location'].search(
            [('id', 'child_of', self.location_id.id)]).ids
        if not location_ids:
            return []
        params = {
            'date_from': date_from,
            'date_to': date_to,
            'company_id': self.company_id.id,
            'location_ids': location_ids,
            # only read by MOVES_QUERY when a single product is requested
            'product_id': self.product_id.id,
        }

        product_filter = ('AND move.product_id = %(product_id)s'
                          if self.product_id else '')
        self.env.cr.execute(
            MOVES_QUERY.replace('__PRODUCT_FILTER__', product_filter), params)
        moves = self.env.cr.dictfetchall()
        if len(moves) > MAX_MOVES:
            raise UserError(_(
                'The selected criteria match %s moves, which is more than the '
                '%s moves this report can display. Please shorten the period '
                'or select a product.'
            ) % (len(moves), MAX_MOVES))
        if not moves:
            return []

        # Opening balances, restricted to the products actually displayed.
        product_ids = sorted({row['product_id'] for row in moves})
        self.env.cr.execute(
            OPENING_QUERY, dict(params, product_ids=product_ids))
        opening = {row['product_id']: float(row['opening'] or 0)
                   for row in self.env.cr.dictfetchall()}

        # One block per product, products ordered by internal reference with
        # the products without reference last (same rule as Stock Balance).
        moves_by_product = {}
        for row in moves:
            moves_by_product.setdefault(row['product_id'], []).append(row)
        products = self.env['product.product'].browse(product_ids)
        products = products.sorted(
            key=lambda p: (not p.default_code, p.default_code or '', p.id))

        values = []
        for product in products:
            product_moves = moves_by_product.get(product.id)
            if not product_moves:
                continue
            balance = opening.get(product.id, 0.0)
            values.append({
                'date': self.date_from,
                'name': _('Opening Balance'),
                'product_id': product.id,
                'counterpart': '',
                'qty_in': 0.0,
                'qty_out': 0.0,
                'balance': balance,
                'is_opening': True,
            })
            for move in product_moves:
                qty = float(move['qty'] or 0)
                if move['direction'] > 0:
                    balance += qty
                    qty_in, qty_out = qty, 0.0
                else:
                    balance -= qty
                    qty_in, qty_out = 0.0, qty
                values.append({
                    'date': move['move_date'].date(),
                    'name': move['move_name'] or '',
                    'product_id': move['product_id'],
                    'counterpart': move['counterpart'] or '',
                    'qty_in': qty_in,
                    'qty_out': qty_out,
                    'balance': balance,
                    'is_opening': False,
                })
        return values


class StockMoveDetailReportLine(models.Model):
    _name = 'stock.move.detail.report.line'
    _description = 'Stock Move Detail Report Line'
    _order = 'id'

    report_id = fields.Many2one(
        'stock.move.detail.report', string='Report', required=True,
        ondelete='cascade', index=True)
    date = fields.Date(string='Date', required=True)
    name = fields.Char(string='Move')
    product_id = fields.Many2one(
        'product.product', string='Product', required=True, index=True)
    default_code = fields.Char(
        string='Internal Reference', related='product_id.default_code',
        store=True)
    uom_id = fields.Many2one('uom.uom', string='Unit',
                             related='product_id.uom_id')
    counterpart = fields.Char(string='Counterpart Location')
    qty_in = fields.Float(string='IN', digits='Product Unit')
    qty_out = fields.Float(string='OUT', digits='Product Unit')
    # Stock of the location once this line is applied: the first line of a
    # product holds its opening balance, the last one holds its closing one.
    balance = fields.Float(
        string='Balance After Move', digits='Product Unit')
    is_opening = fields.Boolean(string='Opening Balance Line', default=False)
