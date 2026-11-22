# -*- coding: utf-8 -*-
"""المرحلة 15 — دفتر الشركاء والأرصدة المتأخرة لا يتجاوزان تقييد البرنش.

العقدة
------
تقريرَا «Partner Ledger» و«Aged Receivable / Aged Payable» يبنيان استعلامهما
عبر ``account.report._get_report_query()``, وتلك الدالة تنتهي بسطر واحد:

    ``self.env['account.move.line']._search(domain, bypass_access=True)``

أي **تخطٍّ صريح لقواعد الوصول**، وتعليق النواة نفسه يقول ذلك حرفًا::

    # The bypass below will ignore access rules ; we still want to check access

وهو سبب المشكلة: قيد ``ir.access`` العالمي الذي تضيفه هذه الوحدة على
``account.move.line`` (README §3) يُطبَّق على كل بحث عادي — فقائمة عناصر
الدفتر تظهر مقيّدة كما يجب — بينما التقرير يمرّ بـ ``bypass_access=True``
فيتجاوزه ويعيد أرقام كل الفروع.

الحل
----
إعادة الشرط **جوّه الاستعلام نفسه**، عبر نقطة الاختناق الوحيدة التي يمرّ
عندها كلا التقريرين: ``account.report._get_options_domain()`` — فهي التي
يبني بها ``_get_report_query()`` مجاله، وهي أيضًا التي يستعملها «التدقيق»
على خلية الـ Aging حين تفتح عناصر الدفتر.

شرطان يجب تحقّقهما قبل إضافة الشرط، كي لا يتغيّر شيء لمن لا قيد عليه
ولا تنكسر الوحدة في قاعدة بلا ``account_reports``:

1. التقرير واحد من الثلاثة المطلوبة (يُعرف من الـ handler الخاص به)،
2. المستخدم **مقيّد فعلًا** (``branch_restricted``) — غير المقيّد تعود
   ``branch_visible_ids`` لديه بكل الفروع، فالشرط مبدئيًا مساوٍ لمدلوله.

وبناءً على ذلك: حساب المدير وتقارير المحاسبة الأخرى **لا تتغيّر حرفًا**.
"""

from odoo import models
from odoo.fields import Domain

#: التقارير الثلاثة الخاضعة للتقييد.
#:
#: تُعرَّف بالـ ``custom_handler_model_id`` لا بالـ xmlid: هذا حقل قراءة واحدة
#: على السجل المحمَّل أصلًا، بينما ``env.ref()`` تستدعي ``ir.model.data`` في كل
#: مرّة يُبنى فيها الاستعلام (ودالتان تبنيانه عشرات المرّات لكل تقرير).
#:
#: الدقة هنا مقصودة: «التقرير المصاحب للتحصيل» (Follow-Up) و«كشف حساب العميل»
#: يرثان نفس الـ handler بتعدد وراثتهما لكنهما يحملان ``_name`` خاصًا بهما،
#: فلا يدخلان في النطاق الذي اختاره صاحب الطلب.
BRANCH_RESTRICTED_HANDLERS = frozenset({
    'account.partner.ledger.report.handler',
    'account.aged.receivable.report.handler',
    'account.aged.payable.report.handler',
})


class AccountReport(models.Model):
    _inherit = 'account.report'

    def _is_branch_restricted_report(self):
        """هل هذا التقرير واحد من التقارير الثلاثة الخاضعة للتقييد؟

        الحقل ``custom_handler_model_id`` يضيفه ``account_reports``؛ ولهذا لا
        يُستدعى هذا method قبل أن نتأكّد في ``_get_options_domain`` أن النواة
        الموسّعة موجودة أصلًا (انظر هناك).
        """
        self.ensure_one()
        return (
            self.custom_handler_model_id.model in BRANCH_RESTRICTED_HANDLERS
        )

    def _branch_visibility_domain(self):
        """شرط البرنش — **نفس نص** قيد ``ir.access`` العالمي.

        مقتطف حرافي من ``security/ir.access.csv``::

            ['|', ('branch_id', '=', False),
             ('branch_id', 'in', user.with_context(active_test=False)
                                    .branch_visible_ids.ids)]

        إعادة استعمال النص نفسه هي ما يجعل التقرير يقول تمامًا ما تقوله
        القائمة: سطر بلا فرع يبقى مرئيًّا للجميع (لم يتغيّر قرار المرحلة 11)،
        وسطر فرع آخر يختفي عن المقيّد.

        تُستدعى فقط حين يكون المستخدم مقيّدًا، فلا يمرّ شرط إضافي على
        استعلام المدير أبدًا.
        """
        user = self.env.user.with_context(active_test=False)
        return [
            '|',
            ('branch_id', '=', False),
            ('branch_id', 'in', user.branch_visible_ids.ids),
        ]

    def _get_options_domain(self, options, date_scope):
        """أضِف شرط البرنش إلى مجال التقرير الخاضع للتقييد.

        لماذا هذا الاسم بالذات؟ لأنه نقطة الاختناق الوحيدة المشتركة:

        * ``_get_report_query()`` تستدعيه لبناء الاستعلام — وعليه تقرير
          الدفتر وحرفيه الأربعة (الأساسي، الفترة، «بلا شريك»، الوحدة)،
        * ``aged_partner_balance_audit()`` يستعمله لبناء مجال «فتح
          عناصر الدفتر» عند النقر على خلية،
        * ``_get_expression_audit_aml_domain()`` يستعمله لتدقيق أي خلية.

        أما زرّ «فتح عناصر الدفتر» في الدفتر (``open_journal_items``) فلا يحتاج
        إلى تعديل: يعيد قائمة ``account.move.line`` عادية، والبحث العادي
        يمرّ على قيد ``ir.access`` العالمي — فالأمر محسوم قبل الوصول إلينا.

        ملاحظتان على ``super()``:

        * ``_get_options_domain`` يحدّدها ``account_reports`` لا ``account``
          (الأخيرة تُعرّف الموديل ``account.report`` وحده). وبدون الوحدة
          الموسّعة لا يوجد تقرير يُبنى ولا من يستدعي هذا method، ولهذا نعود
          بـ ``Domain.TRUE`` بدل أن نرمي ``AttributeError``. هذا هو أيضًا ما
          يجرّب أن ``account_reports`` مثبّتة فعلًا — وحين تُستدعى فعلاً فمعناها
          مثبّتة، فيصحّ التعامل مع حقل ``custom_handler_model_id``.
        * شرطا التقييد يوضعان **بعد** ``super()``: مجال النواة يبقى محفوظًا
          كما هو ويُقاطَع بشرطنا فقط.
        """
        if not hasattr(super(), '_get_options_domain'):
            return Domain.TRUE

        domain = super()._get_options_domain(options, date_scope)

        if not self._is_branch_restricted_report():
            return domain
        if not self.env.user.branch_restricted:
            return domain

        return domain & Domain(self._branch_visibility_domain())
