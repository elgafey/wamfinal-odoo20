{
    'name': 'Sale Order Print Buttons',
    'version': '20.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'Two print buttons on the sales order: custom ZATCA invoice + delivery slip',
    'description': """
Sale Order Print Buttons
========================

Adds exactly two buttons to the sales order form header:

1. Print Invoice
   Prints the customer invoice(s) of the order — every invoice and credit
   note linked to it, oldest first, all of them in one PDF — using the
   report of ``custom_invoice_design`` (the bilingual ZATCA design).
   Shows a clear message when the order has no invoice yet, or when the
   current user may not read customer invoices.

2. Print Delivery
   Prints the delivery slip (``stock.action_report_delivery``) of the
   outgoing transfers of the order: validated (done) transfers first, and
   when the order is not delivered yet, the registered non-cancelled
   transfer, so the button is never dead.
   Shows a clear message when there is nothing to print.

Design notes
------------
* Standalone module: it does NOT modify ``custom_invoice_design``,
  ``sale`` nor ``stock`` — it only inherits ``sale.order`` (two methods)
  and ``sale.view_order_form`` (two buttons).
* Labels are English, like the neighbouring buttons of the same header.
* The buttons are hidden on unsaved records (``invisible="not id"``).
""",
    'author': 'Custom Development',
    'depends': [
        'sale_management',         # sale.order + the Sales menu
        'sale_stock',              # sale.order.picking_ids (delivery slips)
        'custom_invoice_design',   # the ZATCA invoice report action
    ],
    'data': [
        'views/sale_order_views.xml',
    ],
    # يضمن إن module_type='official' بعد التثبيت (بينادي بعد تحميل الـ data).
    # من غيره الموديول بيتخفي من شريط «Official Apps» في صفحة Apps —
    # التفاصيل في تعريف الدالة في __init__.py.
    'post_init_hook': 'post_init_hook',
    'license': 'LGPL-3',
    # application=True → يظهر كتلة App في شاشة التطبيقات مباشرة.
    # (الافتراضي False كان بيخفيه خلف فلتر «Apps» الافتراضي
    #  search_default_app، فماكانش يتشاف غير من فلتر «Extra».)
    'application': True,
    'installable': True,
    'auto_install': False,
}
