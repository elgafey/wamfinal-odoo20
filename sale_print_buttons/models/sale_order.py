# -*- coding: utf-8 -*-
"""زراير الطباعة في شاشة أمر البيع: الفاتورة المخصصة + بوليصة التسليم."""

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools.pdf import merge_pdf

# معرّفات تقارير الجاهزة — لا نُنشئ تقارير، نستدعي الموجود:
#   custom_invoice_design → قالب الفاتورة الضريبية (ZATCA) ثنائية اللغة
#   stock                 → بوليصة التسليم (Delivery Slip)
REPORT_CUSTOM_INVOICE = "custom_invoice_design.action_report_custom_invoice"
REPORT_DELIVERY_SLIP = "stock.action_report_delivery"


class SaleOrder(models.Model):
    _inherit = "sale.order"

    # ------------------------------------------------------------------
    #  المساعدات
    # ------------------------------------------------------------------
    def _spb_invoices_to_print(self):
        """فواتير الزبون المرتبطة بالأوردر (فاتورة + كريدي نوت)، الأقدم أولًا.

        تطبع كلها معًا في ملف PDF واحد — صفحة لكل مستند — لأن الفاتورة
        والكريدي نوت كلتاهما جزء من تسوية نفس الأمر.
        """
        moves = self.mapped("invoice_ids").filtered(
            lambda move: move.move_type in ("out_invoice", "out_refund")
        )
        return moves.sorted(
            key=lambda move: (
                # invoice_date قد يكون فارغًا في المسودات → نرجع لتاريخ الإنشاء
                move.invoice_date or fields.Date.to_date(move.create_date),
                move.id,
            )
        )

    def _spb_pickings_to_print(self):
        """شحنات التسليم المطبوعة للأوردر.

        الأولوية لشحنات outbound المُسلَّمة (done). ولو الأوردر لم يُسلَّم
        بعد نأخذ أي شحن غير ملغى حتى لا يموت الزر، ونبعد المرتجعات
        (picking_type != outgoing) والإلغاءات.
        """
        pickings = self.mapped("picking_ids")
        if not pickings:
            return pickings
        outgoing = pickings.filtered(
            lambda picking: picking.picking_type_id.code == "outgoing"
        )
        candidates = (outgoing or pickings).filtered(
            lambda picking: picking.state != "cancel"
        )
        done = candidates.filtered(lambda picking: picking.state == "done")
        return (done or candidates).sorted(
            key=lambda picking: (
                picking.scheduled_date or picking.create_date,
                picking.name or "",
            )
        )

    def _spb_report(self, xmlid, missing_message):
        """يجلب تقريرًا عبر xmlid أو يرمي رسالة خطأ واضحة."""
        report = self.env.ref(xmlid, raise_if_not_found=False)
        if not report:
            raise UserError(missing_message)
        return report

    # ------------------------------------------------------------------
    #  طباعة أكتر من مستند في ملف واحد
    # ------------------------------------------------------------------
    def _spb_render_merged_pdf(self, report, records):
        """يولّد PDF لكل مستند على حدة ثم يدمجهم في ملف واحد.

        السبب: wkhtmltopdf المثبّت هنا بدون patched QT يرفض تحويل أكتر من
        مستند في استدعاء واحد (UserError: "Tried to convert multiple
        documents in wkhtmltopdf using unpatched QT") — وده اللي خلّى
        أمر البيع اللي عليه 5 فواتير يقع. فنستدعي المحرّك مرة لكل سجل
        وندمج النتيجة بـ odoo.tools.pdf.merge_pdf (pypdf).
        """
        parts = []
        for record in records:
            content, _ext = self.env["ir.actions.report"]._render_qweb_pdf(
                report, res_ids=record.ids
            )
            parts.append(content)
        return parts[0] if len(parts) == 1 else merge_pdf(parts)

    def _spb_merged_pdf_action(self, kind):
        """إجراء يفتح رابط الـ PDF المدموج في تبويب جديد.

        kind: 'invoice' أو 'delivery' — نفس مسارات الـ controller.
        """
        return {
            "type": "ir.actions.act_url",
            "url": "/sale_print_buttons/pdf/%s?orders=%s"
                   % (kind, ",".join(str(order_id) for order_id in self.ids)),
            "target": "new",
        }

    @api.model
    def _spb_kind_pdf(self, order_ids, kind):
        """يبني ملف PDF المدموج لأوردرات معيّنة — ده قلب الـ controller.

        kind: 'invoice' أو 'delivery'
        يرجّع (pdf_bytes, filename)، أو (None, None) لو مفيش حاجة تتطبع
        (أو التقرير مش موجود) — والـ controller بيرجّع عندهم 404.
        وضع المنطق هنا (مش في الـ controller) عشان يتجرب مباشرة من
        odoo shell من غير HTTP.
        """
        orders = self.browse(order_ids).exists()
        if not orders:
            return None, None
        if kind == "invoice":
            report = self.env.ref(REPORT_CUSTOM_INVOICE, raise_if_not_found=False)
            records = orders._spb_invoices_to_print() if report else orders.browse()
            empty_name = "invoices"
        else:
            report = self.env.ref(REPORT_DELIVERY_SLIP, raise_if_not_found=False)
            records = orders._spb_pickings_to_print() if report else orders.browse()
            empty_name = "deliveries"
        if not report or not records:
            return None, None
        # صلاحية المستخدم الحالي (نفس فحص الزر في sale.order).
        orders.check_access("read")
        records.check_access("read")

        pdf = orders._spb_render_merged_pdf(report, records)
        base = orders.name if len(orders) == 1 else empty_name
        filename = "%s.pdf" % str(base).replace('"', "").replace("/", "_")
        return pdf, filename

    # ------------------------------------------------------------------
    #  الزر 1: Print Invoice
    # ------------------------------------------------------------------
    def action_print_custom_invoice(self):
        """اطبع فاتورة/فواتير هذا الأمر بالقالب المخصص (ZATCA)."""
        invoices = self._spb_invoices_to_print()
        if not invoices:
            raise UserError(_(
                "There is no customer invoice for this sales order yet.\n"
                "Create the invoice first, then print it."
            ))
        # الطباعة تتم بصلاحية المستخدم الحالي، فنتحقق مبكرًا لنعطي رسالة
        # مفهومة بدل خطأ AccessError من داخل محرّك التقارير.
        try:
            invoices.check_access("read")
        except AccessError:
            raise UserError(_(
                "You are not allowed to print customer invoices.\n"
                "Ask an administrator to grant you the invoicing rights."
            ))
        report = self._spb_report(
            REPORT_CUSTOM_INVOICE,
            _(
                "The custom invoice report is missing:\n"
                "the 'custom_invoice_design' module is not installed."
            ),
        )
        # config=False: نطبع مباشرة بدون نافذة «إعداد تخطيط الشركة» —
        # القالب المخصص لا يستخدم التخطيط الخارجي أصلًا.
        if len(invoices) == 1:
            # مستند واحد → الطباعة الأصلية بتاعة Odoo (نفس اللي بيحصل
            # من شاشة الفواتير).
            return report.report_action(invoices, config=False)
        # أكتر من مستند → ملف مدموج عبر الـ controller ( السبب: wkhtmltopdf
        # بدون patched QT بيرفض أكتر من مستند في استدعاء واحد).
        return self._spb_merged_pdf_action("invoice")

    # ------------------------------------------------------------------
    #  الزر 2: Print Delivery
    # ------------------------------------------------------------------
    def action_print_delivery_slip(self):
        """اطبع بوليصة التسليم لشحنات هذا الأمر."""
        pickings = self._spb_pickings_to_print()
        if not pickings:
            raise UserError(_(
                "There is no delivery to print for this sales order yet.\n"
                "Confirm the order and validate the transfer first."
            ))
        report = self._spb_report(
            REPORT_DELIVERY_SLIP,
            _(
                "The delivery slip report is missing:\n"
                "the 'stock' module is not installed."
            ),
        )
        # config=False: نفس سبب الزر الأول — زر طباعة يطبع فورًا.
        if len(pickings) == 1:
            return report.report_action(pickings, config=False)
        # أكتر من شحن → ملف مدموج عبر الـ controller (نفس سبب زر الفاتورة).
        return self._spb_merged_pdf_action("delivery")
