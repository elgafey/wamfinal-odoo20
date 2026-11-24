from . import models
from . import controllers


def post_init_hook(env):
    """إصلاح module_type عشان الموديول يبان في صفحة Apps.

    السبب: ``ir.module.module.update_list()`` بينادي قبل تحميل الموديولات
    (``odoo/modules/loading.py:403``)، فـ وقت تنفيذ التثبيت بالـ CLI
    (``odoo -i``) صف الموديول بيتخلق قبل ما الريجيستري يعرف حقل
    ``module_type`` بتاع ``base_import_module`` → الـ default بتاعه
    (``'official'``) مايتطبقش → القيمة بتبقى NULL.

    والنتيجة: شريط Apps في شاشة التطبيقات بيفتح باختيار افتراضي
    ``searchpanel_default_module_type='official'``، فالموديول بيسقط
    من الدومين ويختفي من كل النتائج حتى لو بحثت باسمه.

    (الإصلاح idempotent — لو القيمة مضبوطة مفيش حاجة بتحصل.)
    """
    env.cr.execute("""
        UPDATE ir_module_module
           SET module_type = 'official'
         WHERE name = 'sale_print_buttons'
           AND module_type IS NULL
    """)
