# -*- coding: utf-8 -*-
"""عرض PDF مدموج لأكتر من مستند (فاتورة/بوليصة) في ملف واحد.

لماذا controller أصلًا؟
-----------------------
wkhtmltopdf المثبّت على الخادم بدون patched QT يرفض تحويل أكتر من مستند في
استدعاء واحد، فالأمر اللي عليه مثلاً 5 فواتير كان يقع بـ:

    UserError: Tried to convert multiple documents in wkhtmltopdf using unpatched QT

فبدل ما نغيّر محرك الـ PDF العام (والخط/التنسيق اللي اتضبطوا) أو نطبع مستند
واحد بس، بنستدعي التقرير مرة لكل سجل وندمج النتائج في ملف واحد
(odoo.tools.pdf.merge_pdf) ونرجّعه من هنا.

الاستدعاء: زرّين في شاشة أمر البيع بيرجعوا ir.actions.act_url لمسارين:

    GET /sale_print_buttons/pdf/invoice?orders=3,7
    GET /sale_print_buttons/pdf/delivery?orders=3,7

المنطق كله في sale.order._spb_kind_pdf (يتاختبر من odoo shell مباشرة) —
الـ controller هنا غلاف HTTP رفيع بس.
"""

from odoo.http import Controller, request, route


class SalePrintButtonsController(Controller):

    def _pdf_response(self, orders_param, kind):
        """orders_param: أرقام أوردرات مفصولة بفواصل ("" أو None → 404)."""
        order_ids = [
            int(value)
            for value in (orders_param or "").split(",")
            if value.strip().isdigit()
        ]
        pdf, filename = request.env["sale.order"]._spb_kind_pdf(order_ids, kind)
        if not pdf:
            raise request.not_found()
        return request.make_response(pdf, headers=[
            ("Content-Type", "application/pdf"),
            ("Content-Length", len(pdf)),
            # inline: المتصفح يعرض الـ PDF فيتّسع للمعاينة/الطباعة (Ctrl+P).
            ("Content-Disposition", 'inline; filename="%s"' % filename),
        ])

    @route("/sale_print_buttons/pdf/invoice", type="http", auth="user",
           methods=["GET"], readonly=True)
    def invoice_pdf(self, orders=None, **kwargs):
        """PDF مدموج لفواتير (وكريدي نوت) أمر/أمور البيع في ?orders=1,2"""
        return self._pdf_response(orders, "invoice")

    @route("/sale_print_buttons/pdf/delivery", type="http", auth="user",
           methods=["GET"], readonly=True)
    def delivery_pdf(self, orders=None, **kwargs):
        """PDF مدموج لشحنات التسليم في ?orders=1,2"""
        return self._pdf_response(orders, "delivery")
