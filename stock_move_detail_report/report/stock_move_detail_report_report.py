# -*- coding: utf-8 -*-
from odoo import api, fields, models


class StockMoveDetailReportDocument(models.AbstractModel):
    """Rendering context of the PDF report.

    The model name must be ``report.<report_name>`` so that
    ``ir.actions.report._get_rendering_context`` picks it up and merges the
    values returned here (``docs`` is already provided by the generic path,
    we only add the printing information shown in the header/footer).
    """
    _name = 'report.stock_move_detail_report.document'
    _description = 'Stock Move Detail Report PDF'

    @api.model
    def _get_report_values(self, docids, data=None):
        now = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        return {
            'doc_ids': docids,
            'doc_model': 'stock.move.detail.report',
            'docs': self.env['stock.move.detail.report'].browse(docids),
            'printed_at': now.strftime('%Y-%m-%d %H:%M'),
            'printed_by': self.env.user.name,
        }
