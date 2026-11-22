# Branch Management — إدارة الفروع (وحدة Odoo 20)

وحدة مستقلة تُنشئ بيانات «الفرع» كأصل رئيسي وتوصله بالـ **Sales / Inventory /
Accounting / Analytic**، باستخدام آليات الامتداد القياسية في Odoo فقط
(`_inherit`، نماذج جديدة، حقول محسوبة ومرتبطة، قيود، ORM، قواعد أمان) —
**دون تعديل أي ملف من ملفات نواة Odoo**.

| البند | القيمة |
|---|---|
| اسم الوحدة | `branch_management` |
| الإصدار | `20.0.1.2.0` |
| التبعيات | `sale_stock`, `stock`, `account`, `analytic` |
| التصنيف | `Sales/Sales` |
| الرخصة | `LGPL-3` |
| عدد صفوف `ir.access` | 19 |

---

## 1. نظرة عامة

* **الفرع** = الاسم + الرمز (فريد داخل الشركة) + الشركة + المسؤول + المستودع +
  الحساب التحليلي + العنوان والحالة (نشط/مؤرشف).
* الفرع **يُورَّث تلقائيًا** في: طلب البيع ← التجهيز ← حركة المخزون ← التحويل،
  وفي: طلب البيع ← الفاتورة ← القيود اليومية ← القيود التحليلية.
* حساب الفرع التحليلي **يُطبَّق على كل سطر من سطور القيد** الذي يحمل
  فرعًا: سطر الدخل، والمستحق، والضرائب، والتقريب، والبنك، والدائن
  والمدين — فتُبنى القيود التحليلية على هذا الأساس أيضًا (القسم 6.4
  والقسم 14).
* **السداد** (دفع العميل والمورد) يحمل الفرع: المعالج يقترحه من الفاتورة،
  وفورم وقائمة الدفعات تعرضانه، وقيد الدفعة يرثه (القسم 6.8).
* **جهات الاتصال** تحمل **فرعًا أو أكثر** في حقل واحد على شاشة Contact
  (فورم + قائمة + بحث) (القسم 6.9)، والمستخدم المقيَّد **لا يرى ولا يعدّل**
  جهات الاتصال التابعة لفرع آخر (القسم 6.10).
* **تقرير تحليل المبيعات** (`sale.report`) يحمل عمود الفرع مع خاصية البحث
  والتجميع (القسم 6.5).
* **تقرير تحليل الفواتير** (`account.invoice.report`) يحمل عمود الفرع أيضًا
  مع بحث وتجميع «حسب الفرع»، ويُقتصر على فروع المستخدم (القسم 6.11)، وتُصلَح
  فيه أربعة مقاييس Pivot كانت تظهر فارغة بسبب خلل في نواة Odoo (القسم 13).
* **نموذج الفرع** يعرض عدّادات وصولًا بالأزرار الذكية (القسم 6.6).
* **الرؤية مقيّدة بالفرع** لمن يحمل مجموعة «Branch User» فقط (القسم 7).

---

## 2. المتطلبات

* Odoo 20 (اختُبرت على إصدار الحزمة `20.0+e.20260925`).
* وحدات `sale_stock` / `stock` / `account` / `analytic` (تُثبَّت تلقائيًا عبر
  `depends`).

---

## 3. التثبيت والترقية

**من الواجهة:** تطبيقات ← ابحث عن «Branch Management» ← تثبيت (أو ⚙ ← ترقية
الوحدة بعد أي تعديل).

**من سطر الأوامر:**

```bash
# تثبيت جديد
/usr/bin/odoo -d <DB> \
  --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/home/admin/custom_addons \
  -i branch_management --stop-after-init

# ترقية بعد تعديل ملفات الوحدة
/usr/bin/odoo -d <DB> \
  --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/home/admin/custom_addons \
  -u branch_management --stop-after-init
```

> ⚠️ **لا تشغِّل شيئًا على قاعدة `test20` (الإنتاج، المنفذ 8069)** أثناء
> التطوير. حزمة الاختبارات ترفض تشغيل نفسها على `test20` تلقائيًا (القسم 9).

### القوائم

| القائمة | الموقع | القائمة الأب (تحدّد الرؤية) |
|---|---|---|
| `menu_branch_settings` | الإعدادات ← الفروع | `base.menu_administration` + `groups="base.group_system,base.group_erp_manager"` |
| `menu_branch_sales` | المبيعات ← التهيئة ← الفروع | `sale.menu_sale_config` |
| `menu_branch_stock` | المخزون ← التهيئة ← الفروع | `stock.menu_stock_config_settings` |
| `menu_branch_account` | المحاسبة ← التهيئة ← الفروع | `account.menu_finance_configuration` |

---

## 4. نموذج الفرع: الحقول والقيود

### الحقول

* **التعرّف:** `name`، `code`، `active`، `company_id`، `manager_id`، `notes`
* **المخزون:** `warehouse_id` + `default_stock_location_id` +
  `default_customer_location_id` + `default_vendor_location_id`
  (الموقع الداخلي يُقترح من المستودع تلقائيًا)
* **التحليل:** `analytic_plan_id`، `auto_create_analytic`،
  `analytic_account_id` (يُنشأ تلقائيًا عند الحاجة)
* **البيع:** `pricelist_id` (قائمة أسعار الفرع — المرحلة 19)
* **العنوان:** `address_id`، `phone`، `email`

### القيود (جميعها منع تكرار، لا تعديل على قيود Odoo)

| القيد | الشرط |
|---|---|
| `_code_company_unique` | الرمز فريد داخل الشركة — `models.Constraint('UNIQUE(company_id, code)')` (صيغة Odoo 20، فلما `UNIQUE` لم تعد موجودة) |
| `_check_warehouse_company` | شركة المستودع = شركة الفرع |
| `_check_analytic_account_company` | شركة الحساب التحليلي = شركة الفرع |
| `_check_analytic_account_unique` | الحساب التحليلي لا يُشارك بين فرعين |
| `_check_warehouse_exclusive` | المستودع لا يخص فرعين (يُعطَّل من الإعدادات) |

---

## 5. حساب المستخدم وفروعه

في **الإعدادات ← المستخدمون ← تبويب «Branches»** (صفحة جديدة `user_branches`
أُضيفت بـ `_inherit` إلى `base.view_users_form`):

* `branch_ids` — الفروع المسموح بها
* `branch_visible_ids` — (مخفي، محسوب) الفروع المرئية فعليًا لقواعد الأمان
* `default_branch_id` — الفرع الافتراضي عند إنشاء مستند

**قيد:** الفرع الافتراضي يجب أن يكون ضمن الفروع المسموح بها، وإلا `ValidationError`.

**منطق `branch_visible_ids`:**

| المستخدم | الرؤية |
|---|---|
| ليس «Branch User» | **كل الفروع** (حتى لا ينكسر شيء لمن لا يستخدم التقييد) |
| «Branch User» فقط | فروعه المُسندة فقط |
| «Branch Manager» أو «Branch Administrator» | **كل الفروع** (الإدارة تتجاوز التقييد) |

تُقرأ الفروع بـ `active_test=False` حتى يبقى **الفرع المؤرشف** مرئيًا لقواعد
الأمان (تبقى مستنداته قابلة للقراءة)، ويُطبَّق فلتر النشط من قبل المستهلك.
الحساب يتم بـ `sudo()` لأنه يُنفَّذ أثناء تقييم نطاق الوصول إلى `branch.branch`
(وإلا دخل في تلاقي لا نهائي).

---

## 6. التكامل مع التطبيقات

### 6.1 المبيعات — `models/sale_order.py`

* `branch_id` مخزّن، مفهرس، `check_company`، مع تتبّع القيم،
  **وقيمه الافتراضية = `env.user.default_branch_id`**،
  و`domain` يعرض فقط `branch_visible_ids` (اختياريًا لا يرى المستخدم فرعًا لا
  يملكه).
* **الإلزام على مستوى النموذج لا `required=True`** (قرار متفق عليه): الحقل
  مطلوب في الفورم، وزر «تأكيد» يستدعي فحصًا يمنع التأكيد بدون فرع مع رسالة
  واضحة — فلا تفشل عمليات الـ ORM الجماعية.
* مستودع الفرع يُقترح تلقائيًا في `warehouse_id`.
* **قائمة أسعار الفرع تُقترح على الطلب، ويتبعها تسعير السطور**
  (المرحلة 19): `_compute_pricelist_id` يضع قائمة الفرع فوق قائمة العميل
  ما دام الطلب قابلًا للتعديل (`state not in ('sale', 'cancel')` — نفس
  حالات المستودع)، و`@api.onchange('branch_id')` يستدعي
  `_recompute_prices()` عند انتقال القائمة فقط. **لا ربط لسعر السطر
  بـ `pricelist_id`** — Odoo يمنع ذلك صراحةً في تعليق خاص به.
* **قائمة أسعار الطلب تُقفل حين يحضر فرعه قائمته** (المرحلة 20): حقل
  محسوب **غير مخزَّن** `has_branch_pricelist` = `True` حين يكون
  `branch_id.pricelist_id` موجودًا ومتوافقًا مع شركة الطلب، ويُقرأ في
  الفورم `readonly="state in ['cancel','sale'] or has_branch_pricelist"`
  على **عقدتي** `pricelist_id` اللتين تؤثران في النموذج، ويحميه حارس في
  `write()` يرفع `ValidationError` على أي محاولة تغيير يدوي أو
  استيراد — ما دام الطلب في المسودة وما دام موضع القائمة قد تحرّك
  فعلًا. وقائمة أسعار شركة أخرى لا تُقترح أصلًا فلا تُقفل شيئًا.
* **تبويب «Branches» في بطاقة قائمة الأسعار يضيف فرعًا موجودًا**
  (المرحلة 20): حقل `Many2many` **غير مخزَّن** `branch_ids` يقرأ
  `branch.pricelist_id` ويعكسه — زر «Add» فيه يفتح نافذة البحث (زر
  فتح نموذج إنشاء في الـ `one2many`)، وحذف سطر منه يفكّ الارتباط ولا
  يحذف الفرع، ولا يوجد في قاعدة البيانات سوى نسخة واحدة من الرابط
  (عمود `Many2one` على الفرع) فلا يتعارض الجانبان أبدًا.
* **جورنال المبيعات يُقترح من الفرع** (المرحلة 17): `_compute_journal_id`
  يبحث عن جورنال `type='sale'` مربوط بالفرع، فإن لم يوجد فـ جورنال مبيعات
  بلا فرع، فإن لم يوجد فـ لا شيء (وتبقى قاعدة Odoo: الأدنى تسلسلًا)،
  ويُبقي الجورنال المختار يدويًّا ما دام مربوطًا بالفرع نفسه.
  والعكس أيضًا: اختيار جورنال ينقل الطلب إلى فرع الجورنال.
* `_prepare_invoice()` تمرّر الفرع إلى الفاتورة — **وجورنالها أيضًا** حين
  يحمل الطلب جورنالًا، أو حين لا يحمله (فتُؤخذ جورنالات فرعه).
* `_prepare_procurement_values()` تمرّر الفرع إلى التجهيزات.

### 6.2 المخزون — `models/stock_*.py`

* `stock.warehouse.branch_id`، `stock.picking.branch_id`،
  `stock.move.branch_id` (**مخزّن ومؤشَّر** — قرار: يُتاح البحث والتجميع به).
* `StockRule._get_custom_move_fields()` يضيف الحقل إلى التحركات المولَّدة،
  فتمرّ السلسلة: **طلب بيع ← تجهيز ← حركة ← تحويل**.
* عرض التحويل: عمود وحقل الفرع.
* **المرحلة 18 — الرؤية داخل التطبيق**: المستخدم المقيَّد لا يرى إلا مخازن
  فروعه، ولا بطاقات أنواع عمليات غيرها، ولا مواقع مخازن غيرها. الصفوف
  الثلاثة في `security/ir.access.csv` تسأل دالتين جديدتين على `res.users`
  (القسم 18).

### 6.3 المحاسبة — `models/account_move*.py`

* `account.move.branch_id`: مفهرس، `check_company`، تتبّع، و**`copy=True`**
  حتى يرثه دفعة الدائن/الإشعار المدين (لأن `account.move._reverse_moves()`
  يقوم بـ `copy()`).
* `account.move.line.branch_id`: `related='move_id.branch_id'` مخزّن، مؤشَّر،
  للقراءة فقط — يتبع حركات القيد.
* `account.analytic.line.branch_id`: `related='move_line_id.branch_id'`
  مخزّن، للقراءة فقط.
* **الفواتير النازلة مسبقًا** (down payment) تحمل الفرع، لأن
  `sale.advance.payment.inv.create_invoices()` تبني الفاتورة من
  `**order._prepare_invoice()`.
* الفروع المرئية: حقل الفرع في فورم الفاتورة داخل `header_left_group`
  (يصبح للقراءة فقط خارج `draft`/`cancel`)، وعمود في قائمة القيود اليومية.

### 6.4 المحاسبة التحليلية — قواعد الدمج

مفتاحان على مستوى الشركة (القسم 6.7): `branch_analytic_auto`.

يُطبَّق الآن على **كل سطر من سطور القيد الذي يحمل حسابًا** (المرحلة 14)،
لا على سطر الدخل والمصروف فقط:

* **داخل الفاتورة/الفاتورة الراجعة**: سطر المنتجات، **وسطر المستحق
  (`payment_term`)، وسطور الضرائب (`tax`)، وسطر التقريب**.
* **خارج الفاتورة** (قيد دفع، قيد مصروفات عامة): **كل السطور التي لها
  حساب** — بما فيها سطر البنك وسطر الدائن والمدين.
* **السطور بلا حساب** (قسم/ملاحظة) لا تحمل شيئًا: ليس لها حساب فلا
  يُبنى لها تحليل.

وإذا **زِيل الفرع** عن القيد فُكِّل حسابه التحليلي من التوزيع أيضًا، لأن
القيد لم يعد يخص ذلك الفرع (القسم 14.2).

(الاختبار: `test_suite/test_phase6.py` T7f، و`test_phase9.py` T7 و T10،
و`test_phase14.py` كاملة — 12 اختبارًا.)

| الحالة | النتيجة |
|---|---|
| المفتاح `branch_analytic_auto` مُطفأ | **لا تغيير** |
| السطر بلا حساب (قسم/ملاحظة) | **لا تغيير** |
| القيد بلا فرع، أو فرعه بلا حساب تحليلي | **يُزال** حساب كل فرع من التوزيع |
| التوزيع فارغ | `{حساب_الفرع: 100}` |
| خطة الفرع حرة (لا يستخدمها فرع آخر) | يُضاف حساب الفرع لكل مفتاح، **النسب كما هي** |
| الخطة مستخدمة من **حساب فرع آخر** | يُستبدل بحساب هذا الفرع |
| الخطة مستخدمة من **حساب لا يخص فرعًا** | يُترك كما هو |
| التوزيع يحوي حساب هذا الفرع أصلًا | يُترك كما هو |

### 6.5 تقرير تحليل المبيعات — `models/sale_report.py`

* `branch_id` يُضاف بـ `_inherit` و`_select_dict()` (نفس أسلوب `sale_stock`
  مع `warehouse_id`).
* العرض: عمود اختياري في القائمة، حقل بحث، وفلتر تجميع **«Branch»**.
* صف `ir.access` يمنع تسريب صفوف الفروع الأخرى.

### 6.6 الأزرار الذكية — `views/branch_views.xml`

داخل `<div class="oe_button_box" name="button_box">`:

| الزر | النموذج | الظهور |
|---|---|---|
| Orders | `sale.order` | `invisible="sale_count == 0"` |
| Transfers | `stock.picking` | `invisible="picking_count == 0"` |
| Invoices | `account.move` (`move_type != 'entry'`) | `invisible="invoice_count == 0"` |
| Analysis | `sale.report` | `groups="sales_team.group_sale_salesman"` |

كل زر يفتح القائمة المفلترة على الفرع مع `context = {'default_branch_id': id}`.

**العدّادات غير مخزّنة** (تُحسب عند القراءة، بلا كلفة في القائمة)، وتحمي
نفسها بـ `has_access('read')`: من لا صلاحياته على النموذج يرى **0 بدل
`AccessError`**، فيختفي الزر تلقائيًا وتبقى الفورم مقروءة للجميع.

زر «Analysis» يستخدم `_for_xml_id()` ويحافظ على مجال الـ action الأصلي
(`state != 'cancel'`) بإضافة مجال الفرع بـ `Domain(...) & Domain(...)`.

### 6.7 إعدادات الشركة — `views/res_config_settings_views.xml`

تطبيق «Branch Management» في الإعدادات يحوي مفتاحين تابعين للشركة
(`company_dependent="1"`):

| المفتاح | أثره |
|---|---|
| `branch_analytic_auto` | تطبيق الحساب التحليلي للفرع على التوزيع (القسم 6.4) |
| `branch_warehouse_exclusive` | منع انتساب مستودع واحد لفرعين |

### 6.8 المدفوعات — `models/account_payment*.py`

عند «تسجيل دفعة» (سداد عميل أو مورد) يظهر الفرع الآن في كل خطوة:

| المكان | السلوك |
|---|---|
| نافذة `account.payment.register` | حقل **Branch** يُقترح من الفاتورة أو الفاتورة التي تُسدَّد (من أول سطر في `line_ids`)، ويُمكن تعديله قبل الإنشاء |
| فورم الدفعة `view_account_payment_form` | الحقل بعد `memo`، للقراءة فقط خارج `draft` (نفس قاعدة بقية حقول الدفعة) |
| قائمة الدفعات | عمود اختياري `optional="show"` + حقل بحث + تجميع «Branch» |
| قيد الدفعة `account.move` | يأخذ الفرع، وكذلك سطوره |

التفاصيل:

* `account.payment.branch_id`: مخزّن، قابل للتعديل، مفهرس، `check_company`،
  تتبّع، ويُحسب من `move_id.branch_id` عبر `@api.depends` — أي أن **الدفعة
  وقيدها لا يختلفان أبدًا** في الاتجاهين.
* **لماذا ليس `related='move_id.branch_id'`؟** لأن القيد لا يوجد بعد وقت
  إنشاء الدفعة، فحقل `related` سيقرأ حقلًا غير موجود. الحل المعتمد: حقل
  مخزّن يُحسب ويُعطى للقيد لاحقًا — وهو بالضبط أسلوب `journal_id` الذي
  يمرّره Odoo نفسه في المعالج.
* `_generate_move_vals()` تُضاف إليها `branch_id` (القيد يرث الدفعة)، و
  `write()` تكتب الفرع في القيد إذا تغيّر على الدفعة.
* المعالج يمرّر الفرع بتجاوز `_create_payment_vals_from_wizard()` و
  `_create_payment_vals_from_batch()` — `_inherit` فقط، بلا تعديل نواة.
* صف قيد `groupless` جديد على `account.payment`: ترى المستخدم المقيَّد
  دفعات فروعه فقط، **والدفعات بلا فرع تبقى مرئية للجميع**.
* عدّاد الفواتير في فورم الفرع يستبعد `move_type = 'entry'`، فلا تُعدّ
  قيود الدفعات فواتير (اختبار T14).
* لا توزيع تحليلي يُفرض على قيد الدفعة (اختبارا T7 و T10 في المرحلة 9).

### 6.9 جهات الاتصال — `models/res_partner.py`

حقل `branch_ids` (علاقة متعدّدة) على `res.partner` — **يمكن اختيار أكثر من
فرع لجهة الاتصال الواحدة**:

| المكان | السلوك |
|---|---|
| فورم جهات الاتصال `base.view_partner_form` | الحقل بعد «Tags» في نفس العمود، بوسم `many2many_tags` |
| قائمة جهات الاتصال | عمود اختياري `optional="hide"` |
| بحث جهات الاتصال | حقل بحث بالفرع + تجميع «Branches» |

ملاحظات مهمّة (كلّها مُتحقَّق منها في مصدر Odoo 20):

* العلاقة `res_partner_branch_rel` بعمودَي `partner_id` / `branch_id`.
* المجال يعرض **فروع المستخدم المرئية فقط** (`branch_visible_ids`)، مثل بقية
  حقول الوحدة.
* **لا `check_company=True` عن قصد**: `res.partner.company_id` كثيرًا ما يكون
  فارغًا (جهة اتصال مشتركة بين الشركات)، و`_check_company_domain(شركة فارغة)`
  ترجع `('company_id', '=', False)` — وبما أن كل فرع له شركة، **لن يمكن
  اختيار أي فرع إطلاقًا**. (المصدر: `odoo/orm/models.py::_check_company_domain`.)
* **`res.users` يرث `res.partner` بـ `_inherits`**: ألا ينهار حقل صلاحيات
  المستخدم `branch_ids`؟ لا — Odoo لا يرث حقلًا **مُعاد تعريفه محليًا**
  (`odoo/orm/model_classes.py::_add_inherited_fields`: «add inherited fields
  that are not redefined locally»)، فيبقى `res.users.branch_ids` حقل
  الصلاحيات و`res.partner.branch_ids` حقل تصنيف جهة الاتصال، بجدولَي علاقة
  مختلفين (اختبار T7 في المرحلة 10).
* قراءة مجال حقل مكتوب بـ `lambda` تتم بـ `field._description_domain(env)`
  — وهي ما يستعمله Odoo نفسه في العروض.

---

### 6.10 تقييد جهات الاتصال بالفرع — `security/ir.access.csv` + `has_branch`

صف `groupless` واحد يضيف قيدًا على `res.partner` (المرحلة 11):

```python
['|', '|',
 ('has_branch', '=', False),                 # جهة بلا فرع ← مرئية للجميع
 ('branch_ids', 'in',
  user.with_context(active_test=False).branch_visible_ids.ids),   # فروعه
 ('id', 'child_of', user.commercial_partner_id.id)]               # شريكه وشركته
```

**لماذا الحقل المُساعد `has_branch`؟** لأنه لا يمكن كتابة `('branch_ids',
'=', False)` — راجع القسم 8، البند 13: Odoo 20 يعيد كتابة فراغ الـ x2many في
مجالات `ir.access` إلى «لا يملك فرعًا **مرئيًا**»، فيمرّ فرع الغرباء!
ولأن `many2one` لا يتأثر بهذه المشكلة، بقيت كل قيود النماذج الأخرى على
نمط `('branch_id', '=', False)` دون تغيير.

```python
has_branch = fields.Boolean(compute='_compute_has_branch', store=True)
@api.depends('branch_ids')
def _compute_has_branch(self): ...
```

| الحالة | النتيجة |
|---|---|
| جهة اتصال تابعة لفرع المستخدم | ✅ مرئية، يقرأها ويعدّلها |
| جهة اتصال **بلا فرع** | ✅ مرئية للجميع (كما اخترت) |
| جهة اتصال لفرع آخر | ❌ لا بحث، ولا قراءة، ولا تعديل، ولا حذف |
| شريك المستخدم نفسه / شريك الشركة | ✅ محفوظ دائمًا بالورقة `child_of` |
| مستخدم **ليس** «Branch User» | ✅ كل شيء كما هو |

**تنبيهان مقصودان (بيانات، لا كود):**

* مستند لفرعه يشير إلى جهة اتصال **لفرع آخر** ← المستند مرئي لكن حقل
  الشريك سيرفض `read` على `res.partner`. الجهة الاتصال الخاطئة هي السبب،
  فلا تُسنَد فرع غريب لجهة اتصال يُشار إليها من مستندات فرع آخر.
* جهات اتصال **المستخدمين** (الموظفين): إن حُوِّلت إلى فرع غريب فإن
  `res.users` يرث `res.partner`، فيختفي ذلك المستخدم من نتائج البحث
  ويُسقط `AccessError` عند `read` عليه. لذلك: **الموظفون إمّا بلا فرع أو
  بفرعهم هم**.

---

### 6.11 تحليل الفواتير — `models/account_invoice_report.py`

**Invoices Analysis** (`account.invoice.report`، القائمة: المحاسبة ← التقارير ←
تحليل الفواتير) — نفس المكان الذي أضفنا فيه عمود الفرع إلى `sale.report`:

| المكان | السلوك |
|---|---|
| عمود القائمة `account_invoice_report_view_tree` | عمود «Branch» بعد «Salesperson» بحالة `optional="show"` |
| بحث التقرير `view_account_invoice_report_search` | حقل بحث بالفرع + فلتر تجميع **«Branches»** (يقود Pivot وGraph) |
| `security/ir.access.csv` | صف قيد `groupless` على `account.invoice.report` |

لماذا لا يحتاج هذا التقرير `init()`؟ لأنّ `account.invoice.report` في Odoo 20
**ليس view في قاعدة البيانات** إطلاقًا — `_table_sql` خاصية تُعيد الاستعلام
ويدمج Odoo في كل `SELECT`، وقائمة الأعمدة يبنيها `_select_list()`:

```python
branch_id = fields.Many2one('branch.branch', readonly=True)   # store=True افتراضيًا

def _select_list(self, table):
    return super()._select_list(table) + [
        SQL("%s AS branch_id", table.branch_id),
    ]
```

* `table` هو رمز `account_move_line` داخل استعلام التقرير، و
  `account.move.line.branch_id` حقل **related مخزَّن** لـ `move_id.branch_id`
  ← قيمته هي فرع الفاتورة تمامًا **دون أي JOIN إضافي**.
* التسمية `AS branch_id` ضرورية: التقرير يُقرأ من `FROM (<subselect>) AS
  "account_invoice_report"`، فكل الأعمدة و`GROUP BY` تُحلَّل باسم عمود المخرجات.
* الإضافة تُصبح فعّالة فور تحميل الوحدة: لا `DROP VIEW`، ولا `CREATE VIEW`،
  ولا إعادة تشغيل `-u account` (راجع القسم 8، البند 1).
* **التقييد**: قاعدة `groupless` تعمل على `read_group` أيضًا، لأنّ
  `_read_group()` يبدأ بـ `_search(domain)` الذي يطبّق مجالات `ir.access` —
  أي أنّ **التجميع لا يسرّب فروع الغير** (اختبار T6).

> **⚠️ ملاحظة (ليست من الوحدة):** في عرض **Pivot** لهذا التقرير كانت أعمدة
> `Untaxed Amount` و`Total` و`Margin` و`Inventory Value` تظهر **فارغة**.
> الخلل في `pivot_model.js` تابع لـ Odoo core، وقد عولج بإعادة تعريف المقاييس
> الأربعة (المرحلة 13 — القسم 13). المقاييس الأربعة الأخرى لم تتأثر إطلاقًا.

---

## 7. الأمان

### المجموعات (خاصية `Branches` — `res.groups.privilege`)

| المجموعة | التسلسل | تُلزم بـ | الصلاحيات |
|---|---|---|---|
| `group_branch_user` | 10 | `base.group_user` | مقيَّد بفروعه المُسندة |
| `group_branch_manager` | 20 | `group_branch_user` | **يرى كل الفروع** + إنشاء/تعديل/أرشفة الفروع |
| `group_branch_admin` | 30 | `group_branch_manager` | التحكم الكامل مع إسناد الفروع للمستخدمين |

### نمط `ir.access` — 19 صفًا

```
3 صفات مجموعة لـ branch.branch   (base.group_user / base.group_system / group_branch_manager)
1 صفة قيد   لـ branch.branch
15 صفة قيد (groupless) لـ: sale.order, sale.order.line, sale.report,
             stock.warehouse, stock.picking.type, stock.location,
             stock.picking, stock.move,
             account.move, account.move.line, account.analytic.line,
             account.payment, account.journal, res.partner,
             account.invoice.report
                                    = 3 + 1 + 15 = 19 صفًا
```

**تركيب النطاقات في Odoo 20** (من `orm/models.py::_access_domain`):

```python
if access.group_id: permissions.append(domain)   # صفات المجموعة ← OR
else:               restrictions.append(domain)  # بلا مجموعة  ← AND
return Domain.OR(permissions) & Domain.AND(restrictions)
```

أي أن **صفوفنا غير المجموعة تُطبَّق على الجميع كقيد** فوق أي صلاحية أخرى.
ثلاث عشرة صفة منها يحوي مجالها:

```python
['|', ('branch_id', '=', False),
       ('branch_id', 'in', user.with_context(active_test=False).branch_visible_ids.ids)]
```

شرط `branch_id = False` يجعل **السجلات القديمة (بلا فرع) مرئية للجميع** فلا
ينكسر شيء للورثة ولا لـ `stock.warehouse0`.

> **استثناءان مقصودان:**
>
> **(أ) صفوف المخازن الثلاثة (المرحلة 18)** لا تحوي هذا المجال، بل تسأل
> دالة على `res.users`:
>
> ```
> user._branch_strict_domain('branch_id')     # stock.warehouse
> user._branch_through_warehouse_domain()     # stock.picking.type
> user._branch_through_warehouse_domain()     # stock.location
> ```
>
> السبب: مجال Odoo لا يستطيع أن يقول **«إن لم يكن المستخدم مقيَّدًا فلا
> تضع له شرطًا»**. المجال الحرفي `('branch_id', 'in', branch_visible_ids)`
> كان سيُخفي `stock.warehouse0` من أمام المدير نفسه، لأنّ
> `branch_visible_ids` تعني «كل الفروع» وهي **لا تحوي «بلا فرع»**.
> والدالة تُرجع `[]` حين لا يكون المستخدم مقيَّدًا، وترجع ورقة واحدة حين
> يكون. (التفاصيل: القسم 18.)
>
> **(ب) `res.partner`** لا يستطيع استعمال ورقة الفراغ على
> علاقته المتعدّدة (القسم 8، البند 13)، فيستعمل حقلًا مُساعدًا هو
> `has_branch` بدلها — والنتيجة العملية نفسها: من بلا فرع يبقى مرئيًا.
> والنطاق يضيف ورقة ثالثة `(id, 'child_of', user.commercial_partner_id.id)`
> حتى **يبقى شريك المستخدم وشريك الشركة مقروئَين مهما كانت فروعهما**
> (لأن `res.users` يرث `res.partner`، فلو اختفى شريك مستخدم لأُسقط
> `AccessError` في أسماء المستخدمين).

**النتيجة العملية:**

| المستخدم | الرؤية |
|---|---|
| ليس «Branch User» | كل شيء (لا تغيير عن Odoo) |
| «Branch User» بفروع مُسندة | مستندات فروعه فقط — تقارير المبيعات والمخزون والمحاسبة معه |
| «Branch User» — جهات الاتصال | جهات فروعه + جهات بلا فرع + شريكه وشركته فقط (المرحلة 11) |
| «Branch User» — جورنالات | جورنالات فروعه + جورنالات بلا فرع فقط (المرحلة 16) |
| «Branch User» — المخازن | مخازن فروعه **فقط** — لا المخازن التي لا فرع لها (المرحلة 18) |
| «Branch User» — العمليات والمواقع | ما يخص مخازن فروعه + المواقع المشتركة التي لا فرع لها (المرحلة 18) |
| من بلا أي مجموعة على النموذج | `has_access` = `False` → العدّادات 0 بدل `AccessError` |

---

## 8. الفروق الجوهرية عن Odoo 20 (مُتحقَّق منها في المصدر)

1. **`sale.report` ليس عرض SQL** — لا يوجد جدول `sale_report` في القاعدة؛
   `_table_sql` يُضمَّن في كل استعلام عبر `Query.__init__`. لذلك **لا `init()`،
   ولا `DROP VIEW`/`CREATE VIEW`، ولا إعادة تشغيل `-u sale`** لضبط عمود جديد.
   تُبنى قائمة الأعمدة من الحقول المخزّنة (`_select_dict_to_list`).
   **`account.invoice.report` كذلك** (القسم 6.11) — لكن قائمة أعمدته تُبنى
   بـ `_select_list()` المُعاد تعريفها، ويجب تسمية العمود
   `AS branch_id` لأنّ الأعمدة و`GROUP BY` تُحلَّل على اسم مخرجات
   `FROM (<subselect>) AS "account_invoice_report"`.
2. **`GROUP BY` لا يحتاج تعديلًا**: النطاق يجمّع بـ `sale_order.id` (مفتاح
   أساسي) فيسمح PostgreSQL بأي عمود آخر من `sale_order` في `SELECT`.
3. **`ir.access`**: الحقول `operation` + `for_read/for_write/for_create/for_unlink`
   — لم تعد `perm_read/perm_write/...`.
4. **`has_access(operation)`** بديل `check_access_rights(operation,
   raise_exception=False)` (أُزيلت).
5. **`Domain`** من `odoo.fields` بديل `odoo.osv.expression` (وحدة `osv` لم
   تعد موجودة)؛ يُدمج بـ `&`/`|` ويعاد كقائمة بـ `list(...)`.
6. **`_for_xml_id()`** هو الطريقة القياسية لجلب `ir.actions`؛ حقل `domain`
   يعود **نصًا** فيُفكّ بـ
   `from odoo.tools.safe_eval import safe_eval` (لا
   `from odoo.tools import safe_eval` — هذا يستورد الوحدة لا الدالة).
7. **`_sql_constraints` لم تعد موجودة** → `models.Constraint('UNIQUE(...)', 'msg')`.
8. **العروض**: `<list>` بدل `<tree>`، و`view_mode='list,form'`، و
   `invisible="expr"` بدل `attrs`/`states` (التي لم تعد مدعومة).
9. **معرفات سجلات العرض يجب أن تكون فريدة داخل الوحدة** — تعارض معرّف محايد
   يخطف عرضًا من وحدة أخرى (حدث فعلًا: `view_move_tree` سرق قائمة حركات
   المخزون، وأُصلح إلى `account_move_tree_branch`).
10. حقائق أخرى رُكِّبت عليها: `stock.move.name` أُزيل (استخدم `reference`)،
    `stock.move.product_uom` ← `uom_id`،
    `sale.order.procurement_group_id` أُزيل،
    `account.account` له `company_ids` لا `company_id`،
    `ir.ui.menu` يستخدم `group_ids`،
    لا توجد علامة اختيار على الحسابات «تقبل التوزيع التحليلي».
11. **الدفعات**: `account.payment` ليس له `_inherits` على `account.move`
    (له `move_id` فقط)، وقيده يُنشأ بعد الدفعة عبر
    `_generate_journal_entry()` ← `_generate_move_vals()`؛ وسماع
    `field.depends` لم يعد موجودًا — الاستعلام الصحيح
    `field.get_depends(model)`؛ وقيم المعالج تمرّ عبر
    `_create_payment_vals_from_wizard()` / `_create_payment_vals_from_batch()`.
12. **جهات الاتصال**: ملف صلاحيات `base` في Odoo 20 اسمه
    `security/ir.access.csv` (لم يعد `ir.model.access.csv`)؛ و
    `res.users._inherits = {'res.partner': 'partner_id'}` — الحقل **المُعاد
    تعريفه محليًا يتفوّق على الموروث**
    (`model_classes.py::_add_inherited_fields`)؛ و
    `_check_company_domain(شركة فارغة)` ترجع `('company_id', '=', False)`،
    فـ`check_company=True` على `res.partner` كان سيمنع اختيار أي فرع؛
    ومجال حقل `lambda` يُقرأ بـ `field._description_domain(env)`.
13. **لا تكتب `('x2many', '=', False)` في مجال `ir.access`!** عند حساب
    `_access_domain` يعدّل Odoo ورقة فراغ علاقة متعدّدة إلى
    `('branch_ids', 'not any!', <فروع يحقّ لي قراءتها>)` — أي **«لا يملك
    فرعًا مرئيًا»** لا «لا يملك فرعًا إطلاقًا» — ودمجها مع ورقة `in`
    المجاورة ينتج `has OR has-not` أي **الحقيقة للجميع**: تسرّب كامل
    (تحقَّقنا بحثًا مباشرًا: `res.partner` أظهرت `pB=True` بينما
    `Partner.search(...)` الصحيحة تعطي `False`). سببها أن المحقّق يبني
    استعلامًا فرعيًا فوق `branch.branch` **وقواعد وصولها مُطبَّقة داخله**.
    الحقول من نوع `many2one` لا تتأثر (`= False` ← `IS NULL` بسيط)، لذا
    بقيت كل قيود الوحدة البالغة 11 كما هي؛ وحُلّ مسألة `res.partner`
    بحقل مُساعد مخزَّن `has_branch` (القسم 6.10).

---

## 9. الاختبارات

### التشغيل

```bash
cd /home/admin/custom_addons/branch_management/test_suite
./run_tests.sh                # كل المراحل + فحص سلامة نواة Odoo
./run_tests.sh 4 7            # مرحلة محددة فقط
./run_tests.sh --no-upgrade    # دون ترقية الوحدة قبل الاختبار
./run_tests.sh --help
```

بيئة التطوير الافتراضية (قابلة للتجاوز بمتغيرات البيئة): قاعدة `balance_mod`،
PostgreSQL على `127.0.0.1:55432` المستخدم `admin`، منفذ HTTP `8097`.

| المتغيّر | الافتراضي |
|---|---|
| `ODOO_DB` | `balance_mod` |
| `ODOO_PG_HOST` / `ODOO_PG_PORT` / `ODOO_PG_USER` | `127.0.0.1` / `55432` / `admin` |
| `ODOO_BIN` | `/usr/bin/odoo` |
| `ODOO_HTTP_PORT` | `8097` |
| `ODOO_ADDONS` | مسار نواة Odoo + مجلّد الوحدة |
| `ODOO_CORE` | `1` (0 لتجاوز فحص النواة) |

**كيف تعمل:** كل مرحلة تُشغَّل في **جلسة `odoo shell` مستقلة** تُrolled-back
في نهايتها — لأن تشغيلها في جلسة واحدة يجعل بيانات المرحلة التالية تمحو
تصحيحات التي قبلها.

**أكواد الخروج:** `0` كل شيء نجح · `1` يوجد فشل · `2` وسيلة إدخال خاطئة ·
`3` **رفض قاعدة `test20` (الإنتاج)**.

### النتائج الحالية

```
upgrading branch_management ... ok
[PASS] phase 2 - core model          39 passed, 0 failed, 1 skipped
[PASS] phase 3 - security            17 passed, 0 failed, 0 skipped
[PASS] phase 4 - sales               12 passed, 0 failed, 0 skipped
[PASS] phase 5 - inventory           13 passed, 0 failed, 0 skipped
[PASS] phase 6 - accounting/analytic 20 passed, 0 failed, 0 skipped
[PASS] phase 7 - reports & buttons   10 passed, 0 failed, 0 skipped
[PASS] phase 9 - payments            14 passed, 0 failed, 0 skipped
[PASS] phase 10 - contacts            9 passed, 0 failed, 0 skipped
[PASS] phase 11 - access tightening   10 passed, 0 failed, 0 skipped
[PASS] phase 12 - invoice analysis    10 passed, 0 failed, 0 skipped
[PASS] phase 13 - pivot measures      10 passed, 0 failed, 0 skipped
[PASS] phase 14 - every line carries  12 passed, 0 failed, 0 skipped
[PASS] phase 15 - partner ledger      12 passed, 0 failed, 0 skipped
[PASS] phase 16 - branch journals     13 passed, 0 failed, 0 skipped
[PASS] phase 17 - sales journal       12 passed, 0 failed, 0 skipped
[PASS] phase 18 - stock visibility    14 passed, 0 failed, 0 skipped
[PASS] phase 19 - price list          11 passed, 0 failed, 0 skipped
[PASS] phase 20 - locked price list   12 passed, 0 failed, 0 skipped
[PASS] odoo core integrity    0 modified file, 0 reference to the module
==================================================================
==== TOTAL: 250 passed, 0 failed, 1 skipped ====
```

الوصف التفصيلي لكل اختبار مكتوب في ترويسة كل ملف
`test_suite/test_phaseN.py`.

### فحص سلامة نواة Odoo (مضمَّن في الحزمة)

1. `dpkg -V odoo` — يقارن الملفات ببصمات حزمة DebPa: يجب ألّا يظهر أي ملف
   تحت `/usr/lib/python3/dist-packages/odoo`. (النتيجة الحالية: ملف واحد
   مختلف وهو `/etc/odoo/odoo.conf` — ملف إعدادات وليس نواة.)
2. `grep` داخل `addons` بحثًا عن `branch_management` / `branch_visible_ids` /
   `branch_analytic_auto` — يجب ألّا يعثر على أي مرجع.

أي انتهاك يُعرض كـ `[FAIL] odoo core integrity` ويُرجِع كود `1`.

---

## 10. مراحل التطوير

| المرحلة | المحتوى | الحالة |
|---|---|---|
| 1 | وثيقة المعمارية (عربية) | ✅ |
| 2 | النموذج الأساسي، الحقول، القيود، الحساب التحليلي، القوائم، العرض | ✅ 39 |
| 3 | الأمان: الخصائص، المجموعات، `ir.access`، تبويب المستخدم، إبطال الكاش | ✅ 17 |
| 4 | المبيعات: حقل الفرع، فحص التأكيد، مستودع الفرع، الفاتورة | ✅ 12 |
| 5 | المخزون: المستودع/التحويل/الحركة + `StockRule` + قيم التجهيز | ✅ 13 |
| 6 | المحاسبة + التحليل (قواعد الدمج) + إعدادات الشركة | ✅ 20 |
| 7 | `sale.report` + عرضه + الأزرار الذكية وعدّاداتها | ✅ 10 |
| 8 | حزمة الاختبارات الموحّدة + هذا الملف | ✅ |
| 9 | المدفوعات: المعالج + فورم/قائمة الدفعة + القيد + قيد الوصول | ✅ 14 |
| 10 | جهات الاتصال: `branch_ids` متعدّد + الفورم/القائمة/البحث | ✅ 9 |
| 11 | تقييد جهات الاتصال بالفرع: `has_branch` + قيد `groupless` على `res.partner` | ✅ 10 |
| 12 | تحليل الفواتير `account.invoice.report`: عمود + بحث + تجميع + قيد | ✅ 10 |
| 13 | إصلاح مقاييس Pivot الأربعة في `account.invoice.report` (خلّ في Odoo core) | ✅ 10 |
| 14 | **كل سطر من سطور القيد يحمل حساب الفرع التحليلي** + إصلاح فجوة القيود التحليلية الناقصة | ✅ 12 |
| 15 | **دفتر الشركاء والأرصدة المتأخرة داخل الفرع فقط** (التقارير تتجاوز `ir.access` بـ `bypass_access=True`) | ✅ 12 |
| 16 | **جورنال لكل فرع**: `account.journal.branch_id` + إلزام القيد بجورناله + قيد وصول على الجورنالات | ✅ 13 |
| 17 | **الفرع يختار جورنال المبيعات** في أمر البيع: `_compute_journal_id` + اتباع الطلب للجورنال + إظهار حقل Journal في الفورم | ✅ 12 |
| 18 | **المخازن لا يراها إلا أهل فروعها**: دالتان على `res.users` + صفّان جديدان على `stock.picking.type` و `stock.location` + تشديد صف `stock.warehouse` | ✅ 14 |
| 19 | **قائمة أسعار الفرع**: `branch.pricelist_id` + `product.pricelist.branch_ids` + اتباع `pricelist_id` وأسعار السطور للفرع | ✅ 11 |
| 20 | **قفل قائمة أسعار الطلب** حين يحضر فرعه قائمته (`has_branch_pricelist` + حارس `write`) + تبويب فروع قائمة الأسعار يضيف **فرعًا موجودًا** | ✅ 12 |

**250 اختبارًا ناجحًا، 0 فاشل، 1 مُتخطًّى** — التخطيّ الوحيد من المرحلة 2:
اختبارات تعدد الشركات لم تُنفَّذ لأن إنشاء شركة ثانية تعذّر في قاعدة
الاختبار (`res.company.create`) — قيد بيئة الاختبار لا قيد في الوحدة.

---

## 11. الالتزامات والقيود

* ✅ **صفر تعديل على ملفات نواة Odoo** (مُتحقَّق بـ `dpkg -V` داخل الحزمة).
* ✅ لا استخدام لـ `attrs`/`states` (المُهجرة).
* ✅ لا اختراع لواجهات برمجية: كل حقل/دالة مُتحقَّق منها في مصدر Odoo 20.
* ⚠️ قاعدة الإنتاج `test20` (المنفذ 8069) **لا تُمَس** — حزمة الاختبارات ترفضها.
* ⚠️ تقاريرك السابقة `stock_balance_report` و `stock_move_detail_report`
  **لم تُمَس** (قرار صريح).

---

## 12. محتويات الملفات

```
branch_management/
├── __manifest__.py                     الإصدار، التبعيات، قائمة ملفات البيانات
├── __init__.py
├── README.md                           هذا الملف
├── data/branch_data.xml                خطة التحليل «Branches» (الفروع)
├── models/
│   ├── branch.py                       النموذج، القيود، العدّادات، الأزرار
│   ├── res_company.py                  مفتاحا الشركة
│   ├── res_partner.py                  الفروع المتعدّدة + has_branch (القيد)
│   ├── res_users.py                    branch_ids / branch_visible_ids / branch_restricted / القيد
│   ├── res_config_settings.py          حقول الإعدادات المرتبطة
│   ├── sale_order.py                   حقل الفرع، فحص التأكيد، جورنال الفرع، قائمة الأسعار وقفلها، التجهيز، الفاتورة
│   ├── sale_report.py                  عمود الفرع في تحليل المبيعات
│   ├── stock_warehouse.py              الفرع في المستودع
│   ├── stock_picking.py                الفرع في التحويل
│   ├── stock_move.py                   الفرع في الحركة + StockRule
│   ├── account_journal.py              فرع الجورنال (الجورنال هو مصدر الفرع)
│   ├── account_move.py                 الفرع في القيد/الفاتورة + إعادة بناء القيود التحليلية
│   ├── account_move_line.py            الفرع + دمج التوزيع التحليلي + التحديث
│   ├── account_payment.py              الفرع في الدفعة + إعطاؤه للقيد
│   ├── account_payment_register.py     اقتراح الفرع في معالج السداد
│   ├── account_analytic_line.py        الفرع في القيود التحليلية
│   ├── account_invoice_report.py       عمود الفرع في تحليل الفواتير
│   ├── account_report.py               تقييد دفتر الشركاء والأرصدة المتأخرة بالفرع
│   └── product_pricelist.py            branch_ids (Many2many غير مخزَّن: قراءة + كتابة + بحث) من الفروع
├── security/
│   ├── branch_security.xml             الخاصية + المجموعات الثلاث
│   └── ir.access.csv                   19 صفًا (3 صفات + 16 قيد)
├── views/
│   ├── branch_views.xml                القوائم/الفورم/الأزرار/القوائم الفرعية
│   ├── res_partner_views.xml           الفروع في فورم/قائمة/بحث جهات الاتصال
│   ├── res_users_views.xml             تبويب Branches في المستخدم
│   ├── sale_order_views.xml            حقل الفرع + ظهور جورنال المبيعات + قفل قائمة الأسعار (xpath على عقدتَيْ pricelist_id)
│   ├── sale_report_views.xml           عمود/بحث/تجميع الفرع في التحليل
│   ├── stock_views.xml                 الفرع في التحويل والحركة
│   ├── account_views.xml               الفرع في الفاتورة وقائمة القيود
│   ├── account_invoice_report_views.xml عمود/بحث/تجميع الفرع في تحليل الفواتير
│   ├── account_payment_views.xml       الفرع في الدفعة وقائمتها ومعالج السداد
│   ├── account_journal_views.xml        فرع الجورنال في الفورم/القائمة/البحث
│   ├── product_pricelist_views.xml     تبويب «الفروع» في بطاقة قائمة الأسعار
│   └── res_config_settings_views.xml   تطبيق الإعدادات + المفتاحان
└── test_suite/
    ├── run_tests.sh                    الحزمة الموحّدة (مدفوعة + executable)
    └── test_phase{2..20}.py            18 حزمة اختبار (ترجع الكاش في النهاية)
```

---

## 13. المرحلة 13: إصلاح مقاييس Pivot الفارغة في تحليل الفواتير

### 13.1 العَرَض

قبل الإصلاح كانت **أربعة** مقاييس في **Pivot** «تحليل الفواتير» تظهر فارغة،
والبقية تظهر بأرقامها — والفصل الوحيد بين المجموعتين هو حقل `aggregator`:

| المقياس | الحقل | `aggregator` | قبل | بعد |
|---|---|---|---|---|
| Untaxed Amount in Currency | `price_subtotal_currency` | `sum` (لم يتغيّر) | 712,954.00 SR ✓ | ✓ |
| Total in Currency | `price_total_currency` | `sum` (لم يتغيّر) | 819,897.10 SR ✓ | ✓ |
| Product Quantity | `quantity` | `sum` (لم يتغيّر) | 8.00 ✓ | ✓ |
| Average Price | `price_average` | `avg_currency` (لم يتغيّر) | 89,119.25 SR ✓ | ✓ |
| **Untaxed Amount** | `price_subtotal` | `sum_currency` → **`sum`** | **فارغ ✗** | ✓ |
| **Total** | `price_total` | `sum_currency` → **`sum`** | **فارغ ✗** | ✓ |
| **Margin** | `price_margin` | `sum_currency` → **`sum`** | **فارغ ✗** | ✓ |
| **Inventory Value** | `inventory_value` | `sum_currency` → **`sum`** | **فارغ ✗** | ✓ |

### 13.2 التشخيص (مُتحقَّق منه في المصدر والبيانات)

**أ)** في نواة Odoo، `Monetary.aggregator = 'sum'` وهو القيمة الافتراضية
(`odoo/orm/fields_numeric.py`) — ولهذا يظهر `price_total_currency` صحيحًا.
والنص `aggregator='sum_currency'` **غير موجود إلا في ملف واحد** في كل
`addons`، وهو `account/report/account_invoice_report.py` (4 مواضع بالضبط).

**ب)** في `web/static/src/views/pivot/pivot_model.js`:

```js
// _getMeasureSpecs(): لكل مقياس نقّد ثلاث مواصفات
acc.push(measure + ":" + field.aggregator);            // price_total:sum_currency
acc.push(field.currency_field + ":array_agg_distinct"); // company_currency_id:array_agg_distinct
acc.push(field.name + ":sum_currency");                 // price_total:sum_currency (مكرّرة)

// _getMeasurements():
if (aggregator === "sum_currency") {
    const currencies = group[...currency_field + ":array_agg_distinct"];
    if (currencies.length === 1) { return measurements; }   // ← لا يسجّل القيمة
}
```

لأن `field.aggregator` **هو نفس** `sum_currency`، لا توجد مواصفة `sum`
بديلة تُسجّل القيمة ⇒ تُرفض المواصفتان ⇒ تبقى `measurements[name]`
بلا قيمة ⇒ `value === undefined` ⇒ خلية فارغة.

**ج)** الحارس يعمل **كلما احتوت المجموعة على عملة واحدة** — وهي الحالة
الطبيعية. على `test20`: كل السطور بالريال (`currency_id = 151`)، و
`account_move.invoice_currency_rate = 1.0` في كل فاتورة
(`rate NULL = 0`)، أي أن **البيانات سليمة تمامًا** والخلّ في الواجهة فقط.

**د)** الـ **graph** لا يتأثر لأنه يقرأ `group[fieldAggregate]` ثم يستبدلها
بالقيمة المحوّلة **فقط** عند تعدّد العملات:

```js
const value = group[fieldAggregate];
if (currencies.length > 1) { dataPoint.value = dataPoint.convertedValue; }
```

**هـ)** التحقق من البيانات على `test20` (أداة `diag_report20.sh`):
`Total NULL = 0`، `Margin/Inventory NULL risk = 0`،
و`708,310 + 4,644 = 712,954` = تمامًا صف «Total» في اللقطة.

### 13.3 الإصلاح

إعادة تعريف الحقول الأربعة في `models/account_invoice_report.py` بقيمة
`Monetary` الافتراضية:

```python
price_total = fields.Monetary(
    string='Total',
    readonly=True,
    currency_field='company_currency_id',
    aggregator='sum',
)
# وكذلك price_subtotal و price_margin و inventory_value
```

الآن تصبح مواصفات المقياس:

```text
price_total:sum                        ← يُسجّل القيمة (تعمل دائمًا)
company_currency_id:array_agg_distinct ← تُستخدم للحكم
price_total:sum_currency               ← يُرفض عند عملة واحدة (صحيح)،
                                          ويحلّ محلّ القيمة عند تعدّد العملات (صحيح)
```

**أي أنّ السلوك يصبح مطابقًا تمامًا لما يفعله الـ graph أصلًا:**

| الحالة | النتيجة |
|---|---|
| مجموعة بعملة واحدة | `sum` (القيمة تظهر) |
| مجموعة بعدة عملات | `sum_currency` (القيمة محوّلة) |

### 13.4 ما الذي لم يتغيّر

* **لا ملف من نواة Odoo** — يتحقق `dpkg -V odoo` في كل تشغيل لحزمة الاختبار.
* لا عمود، ولا استعلام، ولا تسمية حقل، ولا تغيير في `_select_list()`.
* `currency_field` بقي `company_currency_id` ⇒ مواصفة التحويل لا تزال
  تُطلب، فبقاء سلوك تعدد العملات محفوظ.
* `price_average` لم يُمَس: لا يزال `avg_currency` ولا يزال Odoo يعالجه
  في `_read_group_select()` الخاص به.
* `price_subtotal_currency` و `price_total_currency` و `quantity` لم تُمَس.

### 13.5 التحقق

```bash
cd /home/admin/custom_addons/branch_management/test_suite
./run_tests.sh                # 176 ناجحًا، 0 فاشل، 1 مُتخطًّى
```

اختبارات المرحلة 13 (10 اختبارات) تغطّي:

| الاختبار | ما يثبته |
|---|---|
| T1 | `aggregator` للحقول الأربعة = `sum` |
| T2 | التسميات و`currency_field` لم تتغيّر |
| T3 | المقاييس الأخرى لم تُمَس (`avg_currency`, `sum`, `currency_id`) |
| T4 | الخادم يجيب عن `:sum` بأرقام حقيقية (شامل القيمة التكميلية والهامش) |
| **T5** | **محاكاة حرافية لدالتيّ JavaScript ⇒ لا خلية فارغة** |
| T6 | المقاييس التي كانت تعمل لا تزال تعمل بنفس القيم |
| T7 | `:sum_currency` ما يزال يجيب (مسار تعدد العملات سليم) |
| T8 | `array_agg_distinct` للعملتين ما يزال يجيب |
| T9 | انحدار: التجميع بالفرع + المواصفات الجديدة |
| T10 | `price_average` يحتفظ بمعالجه الخاص |

**مقارنة قبل/بعد على البيانات نفسها** (محاكاة `pivot_model.js` على قاعدة
بيانات فعلية — القيم التي كانت تظهر قبل الإصلاح لم تتغيّر إطلاقًا):

| المقياس | قبل | بعد |
|---|---|---|
| price_subtotal_currency | 600.0 | 600.0 |
| price_total_currency | 690.0 | 690.0 |
| quantity | 2.0 | 2.0 |
| price_average | 300.0 | 300.0 |
| **price_margin** | **فارغ** | **600.0** |
| **inventory_value** | **فارغ** | **0.0** |
| **price_total** | **فارغ** | **690.0** |
| **price_subtotal** | **فارغ** | **600.0** |

### 13.6 طريقة التطبيق

> **ملاحظة على الجدول أعلاه:** `inventory_value = 0.0` لأنّ منتج قاعدة
> التجربة تكلفته صفر؛ على `test20` التكاليف مسجَّلة (`{"1": 86.83}`) فسيظهر
> رقمًا حقيقيًا — واختبار T4 يفرض ذلك بمنتج مُكلَّف صراحةً.

* لا تحتاج إلا `-u branch_management` — لا أصول JavaScript، ولا إعادة بناء
  للحزمة، ولا أي ملف من `web`.
* على الإنتاج: `/home/admin/dev_addons/branch_management` ←
  `/home/admin/custom_addons/branch_management` ثم الترقية. السكربت
  الجاهز يفعل ذلك بترتيب آمن (نسخة احتياطية ← إيقاف ← نسخ ← ترقية ←
  تحقّق من `fields_get` ← تشغيل):

  ```bash
  sudo bash /home/admin/upgrade_test20_phase13.sh
  ```

  رابط التحقق بعد الترقية:
  `http://localhost:8069/odoo/customer-invoices-analysis?view_type=pivot`
* إذا رأيت `aggregator='sum_currency'` في نسخة أحدث من Odoo، فالإصلاح
  زائل: أزل التعريفات الأربعة من `models/account_invoice_report.py` أو
  تحقّق أولًا من أن Odoo عالج الخلل نفسه.

---

## 14. المرحلة 14: حساب الفرع على كل سطر من سطور القيد

### 14.1 العَرَض

كانت القاعدة قبل هذه المرحلة: **سطور الدخل والمصروف وحدها** تحمل حساب
الفرع. ففي فاتورة عُدّت ثلاث سطور — والنتيجة كانت:

| السطر | قبل المرحلة 14 | بعد المرحلة 14 |
|---|---|---|
| المنتج (دخل `400000`) | `{DGN1:100}` + **قيد تحليلي واحد** | كما هو |
| الضريبة (`251000`) | **لا شيء إطلاقًا** | `{DGN1:100}` + قيد تحليلي |
| المستحق / `payment_term` (`101300`) | **لا شيء إطلاقًا** | `{DGN1:100}` + قيد تحليلي |
| قيد دفع: بنك + دائن | **لا شيء للسطرين** | `{DGN1:100}` للسطرين |

أي أنّ القيود التحليلية للفرع كانت تُبنى عن **نصف القيد** فقط: يظهر أنّ
الفرع حقّق دخلًا، ولا يظهر أين ذهب هذا الدخل (لم يُحلَّل سطر المستحق
ولا سطر الضريبة).

وراء ذلك **فجوتان حقيقيتان** كانتا مُسجَّلتين في الاختبارات وفشلتا فعليًا
قبل الإصلاح:

| الفجوة | الحالة | ما كان يحدث |
|---|---|---|
| **أ** | قيد سُجّل **ثم حصل على فرعه** | **صفر** قيد تحليلي، لا للدخل ولا لغيره |
| **ب** | تغيير الفرع أو إزالته بعد التسجيل | تظلّ القيود التحليلية **للفرع القديم** |

سبب الفجوة أ: إعادة الحساب التي يقوم بها Odoo عند تغيير `branch_id` هي
**إعادة حساب حقل**، والحساب ليس كتابةً — فلا تُستدعى
`_inverse_analytic_distribution` التي هي وحدها تبني القيود التحليلية.
والسبب في ب: نفس الشيء، مضافًا إليه أنّ القيود التحليلية القديمة لا
يحذفها أحد.

### 14.2 القاعدة الجديدة

**كل سطر في قيد يحمل فرعًا ولديه حساب ⇒ حساب ذلك الفرع في توزيعه
التحليلي، وقیده التحليلي مبنيٌّ عليه.**

* داخل الفاتورة/الفاتورة الراجعة: سطر المنتجات، **وسطر المستحق
  (`payment_term`)، وسطور الضرائب، وسطر التقريب**.
* خارج الفاتورة (قيد دفعة، قيد مصروفات): **كل السطور** — بما فيها سطر
  البنك وسطر الدائن والمدين.
* **السطور بلا حساب** (قسم / ملاحظة) مستثناة: ليس لها حساب فلا يُبنى
  لها تحليل.
* **زِيل الفرع** ⇒ يُزال حسابه من التوزيع، والقيود التحليلية التي بنيها
  تُعاد بناؤها من دونه.

جدول الحالات كاملًا في **القسم 6.4**، والمفتاح `branch_analytic_auto`
يبقى عليه دلّال إطفاء منزليًا لكل شيء ما عدا الإزالة.

### 14.3 التنفيذ

| الملف | التغيير |
|---|---|
| `models/account_move_line.py` | حُذف ثابت `BRANCH_ANALYTIC_ACCOUNT_TYPES` وشرط `display_type == 'product'` وشرط `account_type` من `_merge_branch_analytic_distribution` — صار الشرط الوحيد: **`self.account_id` موجود** |
| `models/account_move_line.py` | جديد: `_drop_branch_analytic_accounts()` — الجزء المعاكس من القاعدة (إزالة الفرع) |
| `models/account_move_line.py` | جديد: `_reapply_branch_analytic(snapshot=None)` — يبني التوزيع ثم يبني القيود التحليلية المفقودة أو المتغيّرة |
| `models/account_move.py` | جديد: طبقة `write()` — عند تغيّر `branch_id` تُلتقط نسخة من توزيع السطور **قبل** `super().write()` ثم تُعاد المعالجة **بعده** |

### 14.4 خمس نقاط حرجة — لو أسقطت أيًّا منها لم تعمل المرحلة 14

كلها مُتحقَّق منها في مصدر Odoo 20 نفسه، ومُختبرة بفشل حقيقي قبل الإصلاح.

**أ) `skip_analytic_sync` عند حذف القيود التحليلية (النقطة الأهم).**

`account/models/account_analytic_line.py` ← `unlink()` تستدعي
`affected_move_lines._update_analytic_distribution()`، وهذه الدالة (في
`account/models/account_move_line.py`) **تكتب التوزيع من القيود التحليلية
المتبقّية**. فإذا حذفنا القيود ثم عدنا لبناءها في نفس العملية، فستكتب
الدالة التوزيع ← `{}` أولًا، فتجد `_create_analytic_lines()` توزيعًا فارغًا
ولا تُنشئ شيئًا. النتيجة: تغيير الفرع **يحذف** القيود التحليلية ولا
يعيد بناءها. هذا بالضبط ما حدث في السيناريو C قبل إضافة `skip_analytic_sync`
(حذف الفرع القديم واستبداله، ثم يبقى التوزيع فارغًا و0 قيود).

**ب) إعادة قراءة `self.line_ids` بعد `super().write()`.**

نهاية `account.move.write` في النواة تنفّذ `_sync_dynamic_lines(container)`
التي قد **تبني سطر `payment_term` من جديد** (يُحذف قديمه ويُنشأ آخر في
المعرّف نفسه). نسختنا الأولى التقطت `self.line_ids` قبل الكتابة ومرّرتها
إلى `_reapply` ⇒ `MissingError: Record does not exist or has been
deleted`. الإصلاح: قراءة `self.line_ids` **بعد** `super().write()`.

**ج) لماذا نبني القيود التحليلية بأيدينا بدل كتابة التوزيع.**

الطريقة المغرية `line.write({'analytic_distribution': new})` لاستدعاء
الـ inverse في النواة **عملية بلا أثر**: `account.move.line.write` تحذف من
`line_to_write` كل سطر لا تتغيّر قيمته (`_field_will_change`) — ونحن
قرأنا القيمة الجديدة للتوّ فالمحمّل (cache) يحملها أصلًا، فشرط «لا تتغيّر
القيمة» **متحقّق دائمًا**. لذلك نفعل ما تفعله الدالة العكسية بنفسها
بيدينا: حذف القيود التحليلية للسطور المنشورة (`skip_analytic_sync`) ثم
استدعاء `_create_analytic_lines()` في النواة — هما بالضبط النداءان اللذان
تنفّذهما `_inverse_analytic_distribution`.

**د) `env.add_to_compute` يكفي للحفظ.**

النادى على `env.add_to_compute` ثم قراءة الحقل يُنفّذ
`Field.compute_value()` ← `Field.write(..., dirty=True)` ← يُحفظ عند
`flush`. فلا حاجة لكتابة صريحة للتوزيع — أصلًا كما في النقطة ج كانت
الكتابة مرفوضة. ما يحتاج بناءً يدويًا هو **القيود التحليلية فقط**.

**هـ) ممرّ «الأصناف الناقصة» في إعادة البناء.**

`_reapply_branch_analytic` لا يعمل على «السطور التي تغيّرت» فقط، بل
يعيد بناء أي سطر منشور **له توزيع وصفر قيد تحليلي**. هذا هو بالضبط ما
يبدو عليه قيد سُجّل قبل أن يعرف الودّة فرعه — ولا تُصلحه الترقية وحدها.
بدون هذا الممرّ كانت الفجوة أ تبقى فجوة.

### 14.5 ما الذي يتغيّر في أرقامك ⚠️ — اقرأ هذا قبل قراءة تقريرك التحليلي

لأنّ سطر المستحق والضرائب والبنك صار يحمل التحليل أيضًا، **قيود الفرع
التحليلية لفاتورة واحدة تُصفّر إلى صفر** (قيد مزدوج مكتمل):

| السطر | مبلغ تحليلي | كرفون (`balance`) |
|---|---|---|
| دخل | **+100.00** | −100.00 |
| ضريبة القيمة المضافة | **+15.00** | −15.00 |
| مستحق (العميل) | **−115.00** | +115.00 |
| **المجموع** | **0.00** | 0.00 |

وهذا يعني شيئين معًا:

1. **توازن حقيقي:** القيود التحليلية لم تعد نصفًا — شجرة الربح
   والخسارة التحليلية لم تعد تحمل «دينًا عالقًا» باسم المستحق.
2. **لكن ميزان التحليل (Balance) لكل فرع يقترب من صفر** على أي فترة
   تضمّ قيودًا مُسجَّلة كاملة، فلا يصلح بعد الآن كمقياس ربح.

**إن أردت معاودة عرض الربح** (وهو المقصود من تقرير الأرباح والخسائر) فهناك
طريقتان، ولكنهما مختلفتان:

* **طريقة جاهزة — تحليل الفواتير** (`account.invoice.report`): له عمود
  **Branch** وزر تجميع (القسم 6.11)، وله فلترا **Customers** و**Vendors**
  من النواة أنفسهما. فاجمع حسب الفرع مع فلتر Customers يعطيك **الدخل**،
  ومع فلتر Vendors يعطيك **التكلفة**، والفرق = الربح. (تنبيه صادق: حقل
  `account_id` = «Revenue/Expense Account» موجود في هذا التقرير لكن عرض
  البحث في النواة لا يعرضه، فلا تستطيع تصفية الربح بحساب دخل بعينه من
  الواجهة.)

* **طريقة يدوية — القيود التحليلية** (`account.analytic.line`): افتح
  «Analytic Items» وفلتر يدويًّا على الحساب المالي
  `general_account_id.account_type` بحيث يدخل `income`, `income_other`,
  `expense`, `expense_other`, `expense_depreciation`,
  `expense_direct_cost` فقط — عندها يعود الميزان = دخل − مصروف = الربح.
  **ولكن:** الوحدة تخزّن `branch_id` على القيود التحليلية ولا تُضيف عمودًا
  لها في قوائم Odoo للـ Analytic Items — فلا توجد تجميع بالفرع هناك بعد.
  لو أردت ذلك فهو تغيير صغير في عروض النواة (شجرة + بحث) ويمكن أن يكون
  مرحلة قادمة.

**إن أردت عرض الحركة النقدية والموقع** — فميزان الفرع صار هو المعنى
الصحيح حاليًّا.

(ولم يتغيّر شيء في `account.invoice.report` ولا في أي تقرير مالي —
التغيير على `account.analytic.line` التي هي قاعدة البيانات التحليلية
وحدها.)

### 14.6 التحقق

```bash
cd /home/admin/dev_addons/branch_management/test_suite
./run_tests.sh 14          # 12 اختبارًا
```

| الاختبار | ما يثبته |
|---|---|
| **T1** | فاتورة لها فرع ⇒ **كل** سطر منها (سطر المنتج + سطر المستحق) يحمل حساب الفرع |
| T2 | سطر قسم بلا حساب ⇒ لا توزيع ولا قيد تحليلي، والسطور الأخرى سليمة |
| T3 | عند التسجيل يُبنى **قيد تحليلي واحد لكل سطر**، وكلها تحمل الفرع |
| **T4** | **الفجوة أ:** قيد سُجّل بلا فرع ثم حصل عليه ⇒ توزيع وقيود تحليلية |
| **T5** | **الفجوة ب:** تغيير الفرع ⇒ توزيع جديد **وقيود الفرع القديم كلها منقولة** إلى الجديد |
| **T6** | إزالة الفرع ⇒ يُزال حسابه من التوزيع وتُحذف قيوده التحليلية |
| T7 | قيد تحرير (دخل + نقدية) ⇒ السطورتان تحملان الفرع، وبعد التسجيل يبني البنك قيدًا تحليليًّا |
| T8 | قيد دفع ⇒ سطر البنك وسطر الدائن يحملان الفرع، وقيود تحليلية تحمله |
| T9 | **التعبئة (backfill):** يُمحى التوزيع يدويًّا ⇒ يعود كما كان |
| T10 | بلا فرع / بلا حساب تحليلي للفرع / المفتاح مُطفأ ⇒ لا شيء يتغيّر |
| T11 | قيد بلا فرع لا يُبقي حساب أي فرع — **لكن** حساب الفرع الذي لا يملكه أي فرع يبقى كما هو |
| T12 | حساب في خطة أخرى ليس لفرع ⇒ لا يُمس، ويُستبدل حساب الفرع القديم بالجديد فوقه |

### 14.7 طريقة التطبيق على test20

> ⚠️ **الترقية وحدها (`-u branch_management`) لا تُصلح القيود القائمة** —
> لأن إضافة `depends` جديدة لا تعيد حساب التوزيع. **التعبئة (backfill)
> إلزامية.**

سكربت واحد يفعل كل شيء:

```bash
sudo bash /home/admin/upgrade_test20_phase14.sh
```

ما يفعله (ثماني خطوات):

1. يكتشف الملفات المختلفة **آليًّا** بمقارنة `dev_addons` بـ
   `custom_addons` (لا قائمة ثابتة تنتقى).
2. نسخة احتياطية كاملة لقاعدة `test20`.
3. إيقاف خدمة `odoo`.
4. نسخ الملفات المختلفة.
5. `-u branch_management`.
6. تحقّق من المرحلة 13 (`aggregator='sum'` للحقول الأربعة) ومن سلامة
   النواة (`dpkg -V odoo`).
7. **التعبئة** عبر `backfill_test20_phase14.py` داخل `odoo shell`:
   * **الممرّ أ:** كل قيد له فرع ⇒ يُعاد بناء توزيعه ومن ثمّ قيوده
     التحليلية.
   * **الممرّ ب:** كل سطر بلا فرع ما تزال توزيعه يحوي حساب فرع ⇒
     يُزال منه (يمكن تعطيله بجعل `PASS_B = 0` في الملف).
   * **التحقّق:** يطبع `VERIFY checked=N without_distribution=0
     posted_without_item=0` — ولو لم يكن `without_distribution = 0`
     توقّف السكربت وأعاد تشغيل الخدمة.
8. إعادة تشغيل الخدمة والتحقّق من الاستجابة عبر HTTP.

السجل الكامل يُحفظ في `/var/tmp/test20_backfill_phase14_*.log`، والنسخة
الاحتياطية في `/var/tmp/test20_before_phase14_*.dump`.

**مثال تشغيل فعلي** (على قاعدة تشخيصية، بعد محاكاة بيانات ما قبل المرحلة
14 بالمحو اليدوي للتوزيع):

```
[A]  1..1 من 1: سطور 3، بتوزيع 0 -> 3، قيود تحليلية 0 -> 3
PASS_A moves=1 lines=3 dist_before=0 dist_after=3
[B]  1..1 من 1: سطور 1، بتوزيع 1 -> 0
PASS_B candidates=1 stale_fixed=1 dist_before=1 dist_after=0
VERIFY checked=3 without_distribution=0 posted_without_item=0
DONE
```

ثم التحقّق اليدوي للنتيجة:

```
move INV/2026/00001 branch=DGN1
   400000   dist={'571': 100.0}   items=1 accounts=['DGN1'] branch=['DGN1']
   251000   dist={'571': 100.0}   items=1 accounts=['DGN1'] branch=['DGN1']
   101300   dist={'571': 100.0}   items=1 accounts=['DGN1'] branch=['DGN1']
move INV/2026/00002 branch=-
   400000   dist=False            items=0 accounts=[]        branch=[]
   ...
```

أي أنّ: الفاتورة ذات الفرع ⇒ ثلاثة سطور، ثلاثة توزيعات، ثلاثة قيود
تحليلية، كلها تحمل الفرع؛ والفاتورة بلا فرع ⇒ التوزيع والقيود قد
أُزيلا (الممرّ ب).

**ملاحظة:** هذا السكربت **يُطبّق المرحلة 13 مع المرحلة 14** (ملفات
المرحلة 13 منسوخة أصلًا في نسخة الإنتاج ومتطابقة). سكربت
`upgrade_test20_phase13.sh` يبقى صالحًا إن أردت المرحلة 13 وحدها.

### 14.8 ما الذي لم يتغيّر

* **لا ملف من نواة Odoo** — `dpkg -V odoo` يبقى صفرًا، ويُفحص داخل
  السكربت نفسه قبل التعبئة.
* لا عمود جديد، ولا استعلام SQL، ولا تسمية حقل — التغيير في حِمل
  الحقول (`computed`) وفي المنطق المكتوب بالبايثون فقط.
* لا شيء في `account.invoice.report` ولا في تقارير الأرباح
  والخسائر — التغيير على `account.analytic.line` وحدها.
* مفتاح `branch_analytic_auto` ما زال دلّال إطفاء، ومما عدا الإزالة
  يبقى معطّلًا إذا كان مُطفأً.

---

## 15. المرحلة 15: دفتر الشركاء والأرصدة المتأخرة داخل الفرع فقط

### 15.1 العَرَض

مستخدم مقيّد بفرع يفتح **Partner Ledger** أو **Aged Receivable /
Aged Payable** فيجد أمامه أرقام **كل** الفروع، بينما لو فتح قائمة
**Journal Items** — ولو بالنقر على أي سطر من داخل التقرير نفسه — لا
يُرى إلا فرعه. التقرير يفضّح ما تمنعه القائمة.

### 15.2 التشخيص (مُتحقَّق منه في مصدر Odoo 20)

المصدر: `account_reports/models/account_report.py`، داخل
`_get_report_query()`:

```python
# The bypass below will ignore access rules ; we still want to check access
if not self.env.user.has_groups('account.group_account_readonly,account.group_account_basic') \
        and not self.env.su:
    raise AccessError(...)
query = self.env['account.move.line'].with_context(...)._search(domain, bypass_access=True)
```

`bypass_access=True` تتجاوز **كل** قواعد الوصول — ومنها القيد العالمي
الذي تضيفه هذه الوحدة على `account.move.line` (§3، وصفه السادس عشر في
`ir.access.csv`). فالقيد يعمل في القائمة ولا يعمل في التقرير. هذا هو
بالضبط سبب الفرق بين الحالتين.

### 15.3 نقطة الاختناق

التقارير الثلاثة كلها تمرّ بـ `account.report._get_options_domain(options, date_scope)` —
وهي المكان الوحيد الذي نستطيع فيه إضافة الشرط مرة واحدة لكل مسارات
التقرير:

| المستدعي | ماذا يغطي |
|---|---|
| `_get_report_query()` | سطور الدفتر الأساسية وسطور الوحدة والافتتاحية وسطور «بلا شريك»، وسطور الـ Aging كلها |
| `aged_partner_balance_audit()` | النقر على خلية الـ Aging لفتح عناصر الدفتر |
| `_get_expression_audit_aml_domain()` | تدقيق أي خلية في أي تقرير |

### 15.4 الحل

ملف جديد `models/account_report.py` يورّث `account.report` ويضيف شرطًا
واحدًا، **بعد** `super()` لا بدلًا منه. الإضافة لا تقع إلا إذا تكمّل
شرطان:

1. **التقرير واحد من الثلاثة** المطلوبة — يُعرف من
   `custom_handler_model_id.model` (انظر 15.5)،
2. **المستخدم مقيّد فعلًا** — عبر حقل `branch_restricted` الجديد
   (انظر 15.6).

وإلا يعود `super()` وحده، فلا يتغيّر حرف واحد في أي تقرير آخر أو لأي
مستخدم آخر.

الشرط المضاف هو **النص الحرفي** للقيد الموجود أصلًا في
`security/ir.access.csv`:

```python
['|', ('branch_id', '=', False),
 ('branch_id', 'in', user.with_context(active_test=False).branch_visible_ids.ids)]
```

أي أن التقرير يقول تمامًا ما تقوله القائمة: سطر بلا فرع يبقى ظاهرًا
للمقيّد وغير المقيّد (قرار المرحلة 11 لم يتغيّر)، وسطر فرع آخر يختفي.

### 15.5 لماذا `custom_handler_model_id` وليس `env.ref()`

* `env.ref()` تستدعي `ir.model.data` في كل استدعاء، ودالتا بناء
  الاستعلام تستدعيان `_get_options_domain` عشرات المرّات لكل تقرير —
  فارق صغير بلا داعٍ في مسار حسابي حسّاس.
* الحقل قراءة واحدة على السجل المحمَّل أصلًا، فلا يكلف شبه شيئًا.
* **الدقّة:** «التقرير المصاحب للتحصيل» (Open Items / Follow-Up) و«كشف
  حساب العميل» يورّثان نفس الـ handler لكن لكل منهما `_name` خاصًا
  به، فلا يدخلان في النطاق. اختبار T1 يفرض ذلك على **كل** تقارير
  القاعدة (٢٥ تقريرًا): المطلوبة ثلاثة فقط.

### 15.6 لماذا حقل `branch_restricted` جديد على `res.users`

لأن `branch_visible_ids` تعود **بكل الفروع** لمستخدم غير مقيّد، فيصبح
الشرط `branch_id IN (كل الفروع) OR branch_id IS NULL` مساويًا لمدلوله
**إلا أنه شرط إضافي** يُركَّب على كل استعلام تقرير دون داعٍ. الحقل
الجديد يجعل الإضافة **صفرًا تمامًا** لغير المقيّد (المدير، المحاسب،
مدير الفرع).

وكلا الحقلين يُحسبان من `compute` واحدة واحدة (`_compute_branch_visible_ids`)
بحُرفة واحدة، فلا يمكن أبدًا أن يقول أحدهما «مقيّد» والآخر «كل
الفروع». الحقل غير مخزَّن (`store=False`) فلا يوجد عمود جديد في قاعدة
البيانات، والترقية تسجّله في `ir.model.fields` فقط.

### 15.7 ما الذي لم يتغيّر — ولماذا لم نعدّل `open_journal_items`

* **لا ملف من نواة Odoo** — `dpkg -V odoo` صفر، ويُفحص داخل الحزمة.
* **لا تبعية جديدة** — `account.report` مُعرَّف في وحدة `account`
  نفسها (وليس في `account_reports`)، فـ `_inherit` يعمل بلا شرط.
  اختبار T12 يفرض ذلك.
  وحقيقة أن `account_reports` و`account_accountant` كلاهما
  `auto_install: True` تعتمد على `account` — أي أنهما مثبّتان في كل
  قاعدة فيها `account` — لا يُشرِّح وضعهما في `depends`؛ فالحارس في
  الكود يبقى دفاعيًّا عن حالة إلغاء تثبيتهما، ففي تلك الحالة يعود
  `Domain.TRUE` ولا يُرمى `AttributeError` (الدالة غير موجودة أصلًا
  إلا في `account_reports`).
* **لا تعديل لـ `open_journal_items`** (زرّ «فتح عناصر الدفتر»): تعيد
  تلك الدالة قائمة `account.move.line` عادية، والبحث العادي يمرّ على
  القيد العالمي. اختبار T10 يثبّت ذلك بالقياس: مجال الإجراء لا يحمل
  شرط فرع، لكن البحث به كمستخدم الفرع الأول يرجع سطور فرعه وبس،
  وسطور الفرع الثاني مستبعدة.
* لا تغيير في `account.invoice.report` ولا في التقارير التحليلية.

### 15.8 الأرقام (جهزة الاختبار: فاتورتان بفرعَين + فاتورة بلا فرع + ثلاثة فواتير شراء)

| القارئ | Partner Ledger خصم/دَين | Aged Receivable | Aged Payable |
|---|---|---|---|
| مدير (غير مقيّد) | 3400 / 1600 | 3400 | 1600 |
| مستخدم الفرع الأول | 1400 / 800 | 1400 | 800 |
| مستخدم الفرع الثاني | 2400 / 900 | 2400 | 900 |
| مدير فرع | 3400 / 1600 | 3400 | 1600 |

**سطر بلا فرع (400 من المبيعات و100 من المشتريات) يظهر للجميع.**

### 15.9 النطاق خارج هذه المرحلة (بقرار صريح)

التقارير التالية **غير** مقيّدة، وتبقى تُقرأ كما هي لكل مستخدم يملك
صلاحيتها: General Ledger، Trial Balance، Profit and Loss، Balance
Sheet، Tax Report، Journal Report، Bank Reconciliation، **Customer
Statement** و**Open Items** (وهما أقرب أقارب دفتر الشركاء). توسيع
النطاق يكفي إضافة اسمهما إلى `BRANCH_RESTRICTED_HANDLERS` في
`models/account_report.py`.

### 15.10 التحقق

```bash
cd /home/admin/dev_addons/branch_management/test_suite
ODOO_DB=balance_mod ./run_tests.sh
```

```
[PASS] phase 15 - partner ledger      12 passed, 0 failed, 0 skipped
[PASS] odoo core integrity    0 modified file, 0 reference to the module
==== TOTAL: 188 passed, 0 failed, 1 skipped ====
```

اثنا عشر اختبارًا في `test_phase15.py`، كلها تُقرأ كـ
**«القيمة قبل التجهيزات + ما تضيفه التجهيزات»**، فالحزمة صحيحة على أي
قاعدة تجريبية فيها بيانات سابقة. أهمّها:

* **T1** ثلاثة تقارير فقط مُعلَّمة من بين ٢٥ تقريرًا في القاعدة،
  وCustomer Statement وOpen Items خارجها.
* **T3/T4** الشرط يُضاف للثلاثة ولمستخدم مقيّد فقط — لا للمدير، ولا
  لـ General Ledger.
* **T5** شرط التقرير وقيد `ir.access` يختاران **نفس السطور بالضبط**،
  مُقيَّمان على السجلات الحقيقية.
* **T10** زرّ الفتح في التقرير يبقى داخل الفرع دون أي تعديل إضافي.

### 15.11 طريقة التطبيق على test20

```bash
sudo bash /home/admin/upgrade_test20_phase15.sh
```

(الترقية `-u branch_management` تكفي: لا قاعدة بيانات جديدة، ولا
عمود جديد، ولا تبعية جديدة.)

---

## 16. المرحلة 16: جورنال لكل فرع — كل فرع مستقل بجورناله

### 16.1 العَرَض

المطلوب: أن يُحدَّد لكل جورنال في شاشة الحسابات فرع، حتى **يبقى كل فرع
مستقلًا بالجورنال الخاص به**. أي: الجورنال هو مصدر الحقيقة للفرع، لا
القيد ولا المستخدم.

### 16.2 القرارات (بقرار صريح، قبل الكتابة)

| السؤال | القرار |
|---|---|
| ماذا يحدث عند اختيار جورنال له فرع؟ | **إجبار + قيد دائم**: يُملأ `branch_id` تلقائيًا، وأي محاولة لفرع آخر تُرفض بـ `ValidationError` |
| ماذا يرى المستخدم المقيّد؟ | **نمط المرحلة 11**: جورنالات فروعه + جورنالات بلا فرع، وجورنالات الفروع الأخرى مخفية |
| ماذا نفعل بالجورنالات القائمة؟ | **تعيين يدوي فقط**: لا دفعة تعبئة، ولا إنشاء جورنالات تلقائيًا |
| أين يُطبَّق؟ | **القيد والدفعات** (`account.move` + `account.payment`) |

### 16.3 ما الذي أُضيف فعلًا (ثلاثة أشياء فقط)

1. **حقل** `account.journal.branch_id` — مخزَّن، مفهرس، `check_company=True`،
   `tracking=True`، ونطاقه الفوري نفسه لكل حقول الفرع في الوحدة.
2. **صف وصول عالمي واحد** في `security/ir.access.csv` (`groupless` + `crud`)،
   بنصّ شرط المرحلة 11 حرفيًّا.
3. **الإلزام** على `account.move` و`account.payment`، في أربع طبقات.

### 16.4 كيف يعمل الإلزام (أربع طبقات، وكلها ضرورية)

| الطبقة | الملف | الدور |
|---|---|---|
| تعبئة عند الإنشاء | `create()` | تعبئة `branch_id` من الجورنال **قبل** الكتابة، كي تُحسب القيود التحليلية بالفرع الصحيح من أول مرة |
| شبكة أمان بعد الإنشاء | `create()` | النواة تختار الجورنال بنفسها أحيانًا (`_compute_journal_id`) فلا يظهر في القيم إطلاقًا — يُعبَّأ بعدها |
| تعبئة عند التعديل | `write()` | تغيير الجورنال ينقل القيد إلى فرع الجورنال الجديد، إلا لو كُتب `branch_id` صراحةً في نفس العملية |
| اقتراح فوري | `@api.onchange('journal_id')` | المستخدم يرى فرع الجورنال يظهر لحظة اختياره، فلا يلاحظ القيد أصلًا |
| **الرفض** | `@api.constrains('branch_id', 'journal_id')` | أي تعارض — مهما جاء من: الاستيراد، نسخة، سكربت، تغيير نوع المستند الذي يعيد احتساب الجورنال — يُرفض برسالة واضحة تسمّي الجورنال والفرعين |

**سلوك `branch_id=False` صراحةً:** يُعبَّأ من الجورنال ولا يُرفض (لم يُقل شيئًا،
فالجورنال يقوله). أما `branch_id=فرعٌ آخر` فيُرفض.

نفس البنية مكرّرة حرفيًّا على `account.payment` (الدفعة تُنشئ قيدها لاحقًا،
فلا يجوز أن تتعارض مع جورنالها).

### 16.5 المعالج السحري للسداد

أُضيف `journal_id.branch_id` إلى `@api.depends` الخاص بـ
`account.payment.register.branch_id`، فأصبح:

* جورنال سداد له فرع ← **يفوز** على فرع الفاتورة،
* جورنال سداد بلا فرع ← يُبقي اقتراح فرع الفاتورة.

### 16.6 لماذا هذه النقاط بالذات — لو أسقطت أيًّا منها لم تعمل المرحلة

1. **القاعدة عالمية (بلا مجموعة)** — في Odoo 20 التجميع هو
   `Domain.OR(permissions) & Domain.AND(restrictions)`
   (`orm/models.py::_access_domain`). صف بلا مجموعة = **قيد على الجميع**،
   ومنهم من لا يملك أي مجموعة على `account.journal`.
2. **`_access_domain('read')` تُطبَّق على `search` أيضًا** —
   `orm/models.py::_search` (سطر 4882: `if self.env.su or bypass_access:` ثم
   `sec_domain = self._access_domain('read')`). لهذا تختفي قائمة الجورنالات
   **ومنتقي `journal_id`** معًا، دون أي توسعة إضافية.
3. **القيد على `account.move` لا على المستخدم** — يعمل على المدير وعلى
   `sudo()` أيضًا، وإلا لكان الاستقلال قابلًا لتجاوزه بسطر واحد.
4. **`branch_id=False` ≠ خطأ** — وإلّا انكسرت كل جورنالات قاعدتك الحالية
   (كلها بلا فرع اليوم) عند أول قيد.
5. **الجورنال بلا فرع لا يفرض شيئًا ولا يُخفي شيئًا** — استمرار صريح
   لقرار المرحلة 11.

### 16.7 ⚠️ تحذير تشغيلي اقرأه قبل أن تُعطي فرعًا لجورنال قائم

إن أعطيت **جورنال المبيعات الحالي** فرعًا (مثلاً «فرع الرياض»)، فصار كل قيد
يمرّ فيه لازمًا يكون على ذلك الفرع. وفاتورة قادمة من طلب بيع **بفرع آخر**
ستُرفض بـ `ValidationError` — وهذا هو المقصود (الجورنال يقول الحقيقة)، لكنه
مفاجأة إن لم تتوقّعه.

لذلك الطريقتان الصحيحتان:

* **الأريح:** تُبقي الجورنالات بلا فرع → لا شيء يتغيّر في سلوكك اليومي،
  والقاعدة تعمل كـ«جاهزة» لمن أرادها لاحقًا، **أو**
* **الاستقلال الكامل:** تنشئ جورنالًا لكل فرع (مبيعات/مشتريات/بنك/نقدية)
  وتربط كل جورنال بفرعه، ثم تربط أوامر البيع بفرعها الصحيح.

الجورنالات بلا فرع تبقى مرئية للجميع في الحالتين.

### 16.8 ما الذي لم يتغيّر

* ✅ صفر تعديل على ملفات نواة Odoo.
* ✅ لا تبعية جديدة، ولا نموذج جديد، ولا جدول جديد.
* ✅ عمود جديد واحد فقط: `account_journal.branch_id`.
* ✅ لا دفعة تعبئة، ولا إنشاء جورنالات، ولا تعديل على بياناتك القائمة.
* ✅ القوائم والتقارير السابقة (المبيعات، المخزون، الفواتير، دفتر الشركاء)
  كما هي تمامًا — المرحلة 16 تضيف شرطًا على نموذج الجورنال وحده.
* ✅ لا `attrs` ولا `states`.

### 16.9 التحقق

```bash
cd /home/admin/custom_addons/branch_management/test_suite
ODOO_DB=balance_mod ./run_tests.sh 16
```

```
[PASS] phase 16 - branch journals     13 passed, 0 failed, 0 skipped
[PASS] odoo core integrity    0 modified file, 0 reference to the module
==== TOTAL: 13 passed, 0 failed, 0 skipped ====
```

أهمّها في `test_suite/test_phase16.py`:

* **T1** الحقل موجود على الجورنال ومخزَّن ومفهرس، وحوامله الثلاثة
  (فورم/قائمة/بحث) تحمله.
* **T2** صفّه في `ir.access.csv` عالمي (`groupless`)، `crud`، ونطاقه **حرفًا
  بحرف** هو نطاق قيد `account.move`، وسجّلته Odoo بـ `kind=restriction`.
* **T3/T4** المستخدم المقيّد يرى جورنالات فرعه + بلا فرع فقط؛ ولا يستطيع
  القراءة ولا الكتابة ولا الإنشاء على فرع لا يراه — بمستخدمين اثنين، أحدهما
  له صلاحية كتابة على الجورنالات أصلًا (وإلا أثبت الخطأ شيئًا عن الجورنالات
  لا شيء عن الفروع).
* **T5/T6** الإنشاء يأخذ الفرع من الجورنال، وتغيير الجورنال ينقل الفرع،
  والجورنال بلا فرع لا يغيّر شيئًا.
* **T7/T8** فرع مخالف يُرفض عند الإنشاء وعند الكتابة، في الاتجاهين، وعلى
  المدير أيضًا.
* **T10** سطور القيد تحمل الحساب التحليلي لفرع الجورنال، ويُعاد بناؤها عند
  نقل القيد لجورنال فرع آخر.
* **T11/T12** الدفعة تتبع جورنالها، وقيدة عند الترحيل يحمل فرع جورنالها.
* **T13** معالج السداد: جورنال السداد له فرع ← يفوز على فرع الفاتورة،
  وبلا فرع ← يُبقي فرع الفاتورة، والدفعة الناتجة تحترم القاعدة.

(عدّادات `ir.access.csv` في اختبارَي المرحلتين 11 و12 كانت 17 صفًّا /
14 قيدًا وقت كتابة المرحلة 16، والآن صارت **19 صفًّا / 16 قيدًا** بعد
المرحلة 18.)

### 16.10 طريقة التطبيق على test20

```bash
sudo bash /home/admin/upgrade_test20_phase16.sh
```

السكربت كما اعتاد: يعرض الملفات المختلفة ← نسخة احتياطية ← إيقاف الخدمة ←
النسخ ← `-u branch_management` ← تحقّق (الحقل، العرض، صفّ الوصول، سلامة
النواة) ← إعادة تشغيل والتحقق من السلامة.

**قبل أن تبدأ، اقرؤ القسم 16.7** — الجورنالات بلا فرع تتصرف تمامًا كاليوم،
وإن قررت تعيين فروع فافعلها من: **الحسابات ← الإعدادات ← الجورنالات**،
وعمود «الفرع» في القائمة (أو التجميع حسب الفرع في البحث).

---

## 17. المرحلة 17: الفرع يختار جورنال المبيعات في أمر البيع

### 17.1 العَرَض

عند اختيار **الفرع** في أمر البيع، يبحث النظام عن **جورنال المبيعات
المربوط بذلك الفرع** ويجعله جورنال الأمر — وهو الجورنال الذي ستُنشأ فيه
فاتورة الأمر.

هذا هو النصف الآخر من قاعدة المرحلة 16: هناك كان **الجورنال يفرض فرعه على
القيد**، وهنا يفرض **الفرع جورناله على الطلب**، فتلتقي القيمان دائمًا قبل
أن تُنشأ الفاتورة.

في Odoo 20 حقل `sale.order.journal_id` موجود ومخزّن وقابل للكتابة، لكن
حسابه في النواة مجرّد `self.journal_id = False` بلا أي `depends` — أي أنه
لا يفعل شيئًا إطلاقًا. وحقله موجود في فورم أمر البيع داخل مجموعة
**Invoicing** لكن مخفيًّا خلف `groups="base.group_no_one"` (وضع المطوّر
فقط). فكان اختياره يستحيل رؤيته أو فهم أثره.

### 17.2 القرارات (بقرار صريح، قبل الكتابة)

| # | الحالة | القرار |
|---|---|---|
| 1 | الفرع المختار **ليس له** جورنال مبيعات | نستعمل **جورنال مبيعات بلا فرع** (مشترك)؛ فإن لم يوجد أيّهما فلا شيء، فتبقى قاعدة Odoo نفسها (جورنال المبيعات الأدنى تسلسلًا) |
| 2 | المستخدم غيّر الجورنال يدويًّا إلى جورنال **فرع آخر** | **الطلب يتبع الجورنال** — يُنقل إلى فرع الجورنال، تمامًا كقاعدة المرحلة 16 |
| 3 | حقل Journal في الفورم | **يُظهر** في مجموعة Invoicing بدل إخفائه خلف `base.group_no_one` |

### 17.3 ما الذي أُضيف فعلًا (أربع قطع فقط)

**١) `models/sale_order.py` — دالة البحث:**

```python
def _sale_journal_for_branch(self, branch):
    self.ensure_one()
    Journal = self.env['account.journal']
    if not branch:
        return Journal
    domain = [('type', '=', 'sale'),
              ('company_id', 'in', (False, self.company_id.id))]
    journal = Journal.search(domain + [('branch_id', '=', branch.id)],
                             order='sequence, id', limit=1)
    if journal:
        return journal
    return Journal.search(domain + [('branch_id', '=', False)],
                          order='sequence, id', limit=1)
```

**٢) `_compute_journal_id` مُعاد تعريفه مع `@api.depends('branch_id')`** —
وهذه السطر واحدًا هو كل ما يلزم كي يتغيّر الجورنال تلقائيًّا عند تغيير
الفرع، **في الفورم وفي الاستيراد وفي الـ RPC وفي `create` معًا**.

**٣) الاتجاه العكسي (الجورنال يسحب الطلب):** `create` و`write`
و`@api.onchange('journal_id')` — الثلاثة معًا، لأن `branch_id` حقل عادي
ولا يُعاد حسابه من شيء.

**٤) `_prepare_invoice()`** تمرّر `journal_id` حين لا يحمله الطلب.

**٥) `views/sale_order_views.xml`** سجل وراثة واحد:

```xml
<field name="journal_id" position="attributes">
    <attribute name="groups">base.group_user</attribute>
</field>
```

لا شيء آخر: لا صفّ وصول جديد، لا حقل جديد، لا نموذج جديد، لا تغيير على
`__manifest__.py`، والإصدار يبقى `20.0.1.0.0`.

### 17.4 الجدول الزمني لما يحدث عند كل تغيير

| الذي تغيّر | ماذا يحدث لـ `journal_id` |
|---|---|
| تغيّر `branch_id` في الفورم | يُعاد حسابه ← جورنال الفرع الجديد |
| `write({'branch_id': ...})` من أي كود أو استيراد | نفسه تمامًا |
| إنشاء طلب جديد | يُحسب قبل الإدراج (`precompute`) ← جورنال فرعه من أول لحظة |
| تغيير `journal_id` في الفورم | يتبعه الفرع ← `branch_id` = فرع الجورنال |
| `write({'journal_id': ...})` | نفسه |
| جورنال بلا فرع | لا شيء يتغيّر في الفرع ولا في الجورنال |
| الطلب بلا فرع | لا يُقترح جورنال (ولا يمكن تأكيده أصلًا — المرحلة 4) |

### 17.5 نقطة الخطر — لو أسقطتها لم تعمل المرحلة 17

**الاحتفاظ بالجورنال الحالي حين يكون متوافقًا:**

```python
old = previous[order]
if old and old.branch_id == order.branch_id:
    order.journal_id = old          # محفوظ: لا نُلغي اختيار المستخدم
else:
    order.journal_id = order._sale_journal_for_branch(order.branch_id)
```

لو كتبنا `order.journal_id = lookup(branch)` مباشرةً لحدث هذا:

1. المستخدم يختار جورنال **الثاني** لفرع ب (رغم وجود جورنال أول له)؛
2. `@api.onchange('journal_id')` ينقل الطلب إلى فرع ب؛
3. تغيّر `branch_id` يُطلق إعادة حساب `journal_id`؛
4. إعادة الحساب تعيده إلى **أول** جورنال في فرع ب ← **اختيار المستخدم
   يُلغى أمام عينيه**.

الشرط أعلاه يكسر السلسلة عند الخطوة 3، ويُبقي ما اختاره.

**ولماذا قرأنا القيمة السابقة قبل `super()`؟** لأن حساب النواة هو
`self.journal_id = False` — لو نفّذناه أولًا لتلاشى ما نريد مقارنته.
ويقرأ Odoo القيمة القديمة بأمان داخل حساب الحقل نفسه:
`compute_value()` يُزيل الحقل من قائمة «يُحسب» **قبل** استدعاء الحساب
(مذكور في تعليق المصدر صراحةً)، فلا يحدث تراجع لانهائي.

**ولماذا `create` و`write` و`onchange` كلها؟** لأن لكل منها مسار مختلف:
`create` يمرّ بـ `_add_missing_default_values` و`precompute`، و`write` لا
يُعيد حساب حقل عادي مثل `branch_id` أصلًا، والفورم لا يرسل `write` قبل
أن يُغلق — فلا ينفع مسار واحد.

### 17.6 ما الذي لم يتغيّر

* ✅ **صفر تعديل على ملفات نواة Odoo** — الوحدة تُعرِّف فقط حسابًا وقيمته
  على حقل موجود (`_inherit` + `@api.depends`)، ولم تُمسّ أي ملف في
  `/usr/lib/python3/dist-packages/odoo`.
* ✅ **لا صفوف وصول جديدة من هذه المرحلة** — `ir.access.csv` كما هو وقتها
  (17 صفًا؛ صار 19 لاحقًا في المرحلة 18)، ولا تغيير على المجموعات.
* ✅ **لا تغيير على `account.move` ولا `account.payment`** — قاعدة المرحلة
  16 عليها كما هي حرفيًّا: «الجورنال يفرض فرعه على القيد».
* ✅ **لا ترحيل للبيانات** — لا يُنشأ جورنال، ولا يُعطى أي طلب قائم
  جورنالًا بأثر رجعي. الطلبات القائمة تحصل عليه لحظة كتابة فرعها أو عند
  الفوترة (بسبب `_prepare_invoice`).
* ✅ جورنالات قاعدة `test20` بلا فرع تبقى بلا فرع ولا تُقترح إطلاقًا.
* ✅ لا `attrs=` ولا `states=`، وكل XML سليم، و`py_compile` سليم.

### 17.7 التحقق

```
[PASS] phase 17 - sales journal       12 passed, 0 failed, 0 skipped
```

| # | الاختبار |
|---|---|
| T1 | الحقل مربوط بالفرع (`get_depends` == `('branch_id',)`) |
| T2 | الفرع يقترح جورناله — **والأول** تسلسلًا بين جورنالاته |
| T3 | فرع بلا جورنال ← جورنال مبيعات **بلا فرع** |
| T4 | طلب بلا فرع ← بلا جورنال |
| T5 | تغيير الفرع يغيّر الجورنال — حتى لو أُنشئ جورنال الفرع لاحقًا |
| T6 | الطلب يتبع الجورنال: ينتقل لفرعه **ويُبقي** الجورنال المختار |
| T7 | عند الإنشاء أيضًا يفوز الجورنال على الفرع المقترح |
| T8 | سلوك الفورم: المقترح + عدم إلغاء الاختيار + الجورنال المشترك لا يفرض |
| T9 | لا يُقترح إلا جورنال `type='sale'` مهما كان تسلسل غيره |
| T10 | من الفاتورة إلى الفاتورة: الفاتورة في جورنال الفرع وعلى فرعه |
| T11 | طلب بلا جورنال ← `_prepare_invoice()` تعطيه جورنال الفرع |
| T12 | حقل Journal ظاهر في الفورم لمستخدم ليس في وضع المطوّر |

**إثبات مرئي (متصفح):** فورم طلب البيع يعرض «Journal» في مجموعة Invoicing،
وتبديل «Branch» بين Branch Alpha / Branch Beta يبدّل الجورنال أمامك مباشرة
(`T17AL` / `T17BT`)، وتبديل الجورنال يبدّل الفرع.

### 17.8 طريقة التطبيق على test20

```bash
sudo bash /home/admin/upgrade_test20_phase17.sh
```

السكربت كما اعتاد: يعرض الملفات المختلفة ← نسخة احتياطية ← إيقاف الخدمة ←
النسخ ← `-u branch_management` ← تحقّق (الحساب، الوظيفة، العرض) ← إعادة
تشغيل والتحقق من السلامة.

**لا يوجد أي إجراء يدوي مسبق هذه المرة** — لا يُنشأ جورنال ولا يُعطى
جورنال قائم فرعًا. الفرق يظهر من تلقاء نفسه: عند كتابة فرع على طلب أو عند
إنشائه، ستجد حقل «Journal» في مجموعة Invoicing قد امتلأ بجورنال مبيعات
فرعه.

---

## 18. المرحلة 18: المخازن لا يراها إلا أهل فروعها

### 18.1 العَرَض

المستخدم الذي هو في مجموعة «Branch User» يدخل **تطبيق المخزون** فيجد:

* **المخازن** (الإعدادات ← المخازن): مخازن فروعه فقط.
* **شاشة التطبيق** (البطاقات): بطاقات أنواع عمليات مخازن فروعه فقط.
* **المواقع** (الإعدادات ← المواقع): مواقع مخازن فروعه، مع المواقع
  المشتركة التي لا فرع لها (العملاء، الموردون، الإنتاج، تسوية المخزون).
* وكل ما عدا ذلك: غياب تام من نتائج البحث، و`AccessError` عند القراءة
  المباشرة.

**ما الذي وجدناه قبل الكتابة** (نتائج حقيقية على قاعدة الاختبار، لا تخمين):

| الملاحظة | قبل المرحلة 18 |
|---|---|
| قيد `stock.warehouse` في وحدتنا | **موجود أصلًا ويعمل**: لا يرى مخزن فرع آخر ولا يقرأه |
| لكن المخزن **البلا فرع** (مثل `stock.warehouse0`) | **يراه** — وفي قاعدة كل مخازنها بلا فرع يرى الكل |
| شاشة التطبيق (`stock.picking.type`) | يرى **24 من 24** نوع عملية |
| المواقع (`stock.location`) | يرى **24 من 24** موقعًا |

أي أن الثغرة ليست في المخزن وحده: شاشة التطبيق تُبنى من **أنواع العمليات**
لا من المخازن، وكان المستخدم يرى من هناك كامل محتوى بقية الفروع.

### 18.2 القرارات (بقرار صريح، قبل الكتابة)

| # | السؤال | القرار |
|---|---|---|
| 1 | مخزن **بلا فرع** | **يُخفى تمامًا** — «بلا فرع» لا يعني «لي» |
| 2 | المستخدم **غير المقيَّد** (المدير، مدير الفروع) | **لا يوضع عليه أي نطاق إطلاقًا** |
| 3 | نطاق الكشف | المخازن + أنواع العمليات + المواقع (ثلاثة صفوف) |
| 4 | مخزن لم يُسند بعد | يُخفي على المقيَّدين (شرط إلزامي — انظر 18.5)، **ويظهر فور إسناده** |
| 5 | المواقع المشتركة التي لا مخزن لها | **لا تُخفى** — مخزون بلا فرع هو مخزون الجميع، وحجبها يكسر كل تحويل |
| 6 | هل يُستعمل `ir.rule`؟ | لا — نفس آلة `ir.access` القديمة (صفوف بلا مجموعة تُطابَق بـ AND) |

القرار 2 هو الأخطر منطقيًّا، وهو سبب وجود الدالتين: لو وضعنا المجال الحرفي
`('branch_id', 'in', branch_visible_ids)` لاختفى `stock.warehouse0` من أمام
**المدير نفسه**، لأنّ «كل الفروع» لا تحوي «بلا فرع».

### 18.3 ما الذي أُضيف فعلًا (ثلاث قطع فقط)

**١) `models/res_users.py` — دالتان جديدتان:**

```python
def _branch_strict_domain(self, field_name='branch_id'):
    self.ensure_one()
    if not self.branch_restricted:
        return []
    return [(field_name, 'in',
             self.with_context(active_test=False).branch_visible_ids.ids)]

def _branch_through_warehouse_domain(self, warehouse_field='warehouse_id'):
    self.ensure_one()
    if not self.branch_restricted:
        return []
    branch_path = warehouse_field + '.branch_id'
    return ['|', (warehouse_field, '=', False),
            (branch_path, 'in',
             self.with_context(active_test=False).branch_visible_ids.ids)]
```

* الدالة الأولى للنماذج التي **تحمل فرعها بنفسها** (`stock.warehouse`).
* الدالة الثانية للنماذج التي **ليس لها فرع** وتنتمي إلى مخزن
  (`stock.picking.type` و `stock.location`).
* `active_test=False` عن قصد: الفرع المؤرشف يبقى مرئيًا لقواعد الوصول
  (يجب أن تبقى مستنداته مقروءة).
* `ensure_one` لأن نطاقات الوصول تُقيَّم لمستخدم واحد فقط
  (`ir.access._eval_context()` يمرّر `env.user`).

**٢) `security/ir.access.csv` — صف معدَّل + صفّان جديدان (17 ← 19):**

| `id` | النموذج | العملية | المجال |
|---|---|---|---|
| `access_stock_warehouse_branch_restriction` *(معدَّل)* | `stock.warehouse` | `crud` | `user._branch_strict_domain('branch_id')` |
| `access_stock_picking_type_branch_restriction` *(جديد)* | `stock.picking.type` | `crud` | `user._branch_through_warehouse_domain()` |
| `access_stock_location_branch_restriction` *(جديد)* | `stock.location` | `crud` | `user._branch_through_warehouse_domain()` |

الثلاثة **بلا مجموعة** → تُطابَق بـ AND فوق أي صلاحية أخرى (نفس نمط الوحدة
كلها).

**٣) لا شيء آخر** — لا حقل جديد على أي نموذج، ولا نموذج جديد، ولا عرض، ولا
ملف أمان إضافي، ولا تغيير في `__manifest__`، والإصدار يبقى `20.0.1.0.0`.

### 18.4 كيف يمرّ النطاق من الـ CSV إلى SQL

1. `_get_all_access()` يقرأ الصف (مخزون مؤقت) ويحاول `ast.literal_eval` على
   المجال → يفشل (`user._branch_strict_domain(...)` ليست قيمة حرفية) → يُبقي
   **نصًّا** كما هو، ويُحقن كل مرة عبر `Domain(safe_eval(...))` (هذا مثبت في
   `base/models/ir_access.py` و`orm/models.py::_access_domain`).
2. سياق التقييم يحوي `user` = `self.env.user.with_context({})` — أي
   **السياق فارغ عن قصد**، ولهذا نستعمل `with_context(active_test=False)`
   داخل الدالة لا على النطاق.
3. الدالة تُرجع `[]` → `Domain([])` = `Domain.TRUE` → لا شرط أصلًا.
   أو تُرجع ورقة واحدة → شرط بسيط يتحوّل إلى `IN` في SQL.
4. `_check_domain` (قيد على `ir.access`) يقيّم المجال ويتحقق من صلاحيته في
   لحظة التثبيت/الترقية — فإن كان النص خاطئًا لُمِع الخطأ عند الترقية لا
   عند التشغيل.

**المجال الثاني** (الموقع/نوع العملية) يتحوّل إلى `LEFT JOIN` على
`stock_warehouse` ثم `branch`، لأن `warehouse_id` مخزّن في النموذجين
(مُتحقَّق منه: `stock_location.py` السطر 86 و`stock_picking_type.py`
السطر 84).

ورقة `warehouse_id = False` **ليست مكرّرة** مع المسار المنقّط:
`warehouse_id.branch_id = False` يمرّ عبر دمج داخلي، فلا يطابق سجلًا ليس له
مخزن أصلًا. جُرِّب ذلك فعليًّا بـ `search` + `read` على قاعدة الاختبار،
ولو أسقطنا الورقة لاختفت مواقع «العملاء» و«الموردون» من المستخدم المقيَّد
وأُسقطت `AccessError` في كل تحويل.

### 18.5 نقطة الخطر — الشرط الذي يجب أن يتحقق قبل التطبيق ⚠️

**مخزن بلا فرع يُخفي على المستخدم المقيَّد ثلاثة أشياء دفعة واحدة:** المخزن
نفسه، وأنواع عملياته (بطاقات الشاشة)، ومواقع مخزنه.

وهذا ليس استعلائيًّا فقط — جرّبناه على قاعدة الاختبار وحصلنا على
`AccessError` حقيقي في مسارين قياسيين في Odoo نفسه:

```
stock.picking.create
  ← picking_type.sequence_id        ← «no read access to Picking Type»

stock.move.create
  ← _update_orderpoints()           ← (stock_move.py:955)
  ← move.location_dest_id.warehouse_id  ← «no read access to ...»
```

أي أن **كل تحويل وكل حركة** التي تستخدم مخزنًا غير مُسنَد ستُسقط استثناءً
عند المستخدم المقيَّد، لا مجرد عرض ناقص.

**لذلك الشرط إلزامي: أعطِ كل مخزن فرعه قبل تطبيق هذه المرحلة.**
(المخازن موجودة عنك اليوم — `branch_id` على `stock.warehouse` مكوَّن منذ
المرحلة 5 — فالإسناد يتم من: **الفرع ← فتح الفرع ← خانة Warehouse**، يدويًّا
لكل فرع، بلا دفعة تعبئة ولا سكربت.)

وحتى لا يمرّ ذلك من غير قصد، **فحص أولي إجباري** في سكربت التطبيق
(الخطوة 1/8) يعمل قبل النسخة الاحتياطية وقبل إيقاف الخدمة:

* عدد المخازن بلا فرع **> 0** وعدد المستخدمين المقيَّدين **> 0** ←
  **يرفض التنفيذ** (رمز خروج 2) ويطبع قائمة المخازن الناقصة وما سيحدث،
  ولم يُمس أي شيء.
* لم تُجبَر: `PHASE18_FORCE=1 sudo -E bash /home/admin/upgrade_test20_phase18.sh`
* مخازن بلا فرع لكن **لا مستخدم مقيَّد بعد** ← يمرّ مع تنبيه (لا أحد يُطبَّق
  عليه القيد).
* لا مخازن بلا فرع ← يمرّ مع رسالة تأكيد.

**والمستقبَل بعد التطبيق**: أي مخزن تعطيه لفرع يظهر فورًا لأهل ذلك الفرع
بلا إعادة تشغيل ولا مسح كاش (اختبار T14 يثبت ذلك: يكتب الفرع، ويقرأ
المستخدم المقيَّد المخزن في نفس الجلسة).

### 18.6 ما الذي لم يتغيّر

* ✅ **صفر تعديل على نواة Odoo** — لا ملف واحد خارج `branch_management`.
* ✅ **لا حقل جديد ولا نموذج جديد ولا عرض جديد** — التغيير كله في الأمان:
  دالتان على `res.users` وثلاثة صفوف CSV (مُتحقَّق منه باختبار T12).
* ✅ صفّا `stock.picking` و`stock.move` كما هوان حرفيًّا، وما زالا يحفظان
  السجلات بلا فرع مرئية (`('branch_id', '=', False)` + `branch_visible_ids`)
  — لم تُمَس مرحلة 5 (اختبار T13).
* ✅ **لا ترحيل بيانات**: لا يُنشأ مخزن، ولا يُعطى مخزن قائم فرعًا، ولا
  تُرحَّل حركة واحدة. `ir.access.csv` فقط + ملف `res_users.py`.
* ✅ لا صفوف وصول جديدة لغير المخازن، ولا تغيير على المجموعات، والإصدار
  يبقى `20.0.1.0.0`.
* ✅ `attrs=` و `states=` في XML = 0.

### 18.7 التحقق

```
$ ./run_tests.sh 18
upgrading branch_management ... ok
[PASS] phase 18 - stock visibility    14 passed, 0 failed, 0 skipped
```

| الاختبار | ماذا يثبت |
|---|---|
| T1 | الصفوف الثلاثة: النموذج + بلا مجموعة + `crud` + نصّ المجال، وعدّادات الـ CSV **19 / 16 / 3** |
| T2 | الدالتان تُرجعان بالضبط مجالَي القرار للمستخدم المقيَّد وغير المقيَّد |
| T3 | نص الـ CSV يُقيَّم فعليًّا بآلة Odoo نفسها (`_eval_context` + `safe_eval`) |
| T4 | المقيَّد يرى مخزن فرعه **وحده** — لا مخزن الفرع الآخر ولا المخزن بلا فرع |
| T5 | القراءة المباشرة على مخزن غريب أو بلا فرع تُسقط `AccessError` |
| T6 | من ليس مقيَّدًا (مستخدم عادي، مدير فروع) يرى **الكل** — المخزن الافتراضي لا يضيع |
| T7 | أنواع العمليات المرئية **= أنواع مخزنه بالضبط** (شاشة التطبيق) |
| T8 | المواقع = مواقع مخزنه + المواقع المشتركة، **ولا شيء آخر** |
| T9 | الموقعان المشتركان (العملاء/الموردون) يبقيان مقروئَين مباشرةً |
| T10 | مواقع الفرع الآخر **و** مواقع المخزن غير المُسنَد تُرفض (`AccessError`) |
| T11 | المستخدم غير المقيَّد لا يفقد أي موقع ولا أي نوع عملية |
| T12 | `branch_id` ليس حقلًا جديدًا على `stock.location` ولا على `stock.picking.type` — الأمان فقط |
| T13 | صفّا `stock.picking` و`stock.move` لم يُمَسا |
| T14 | إعطاء المخزن غير المُسنَد إلى فرع يجعله **مرئيًّا في نفس الجلسة** (لا إعادة تشغيل) |

والحزمة الكاملة بعد المرحلة 18:

```
==== TOTAL: 227 passed, 0 failed, 1 skipped ====
```

(كانت 213 قبلها؛ الزيادة الـ 14 هي اختبارات هذه المرحلة.)

### 18.8 طريقة التطبيق على test20

**١) قبل أي شيء — أسنِد المخازن إلى الفروع** (انظر 18.5):
الفرع ← افتح الفرع ← خانة **Warehouse**. كرر مع كل فرع.

**٢) ثم طبّق:**

```bash
sudo bash /home/admin/upgrade_test20_phase18.sh
```

السكربت بخطوات ثمانية: الفحص الأولي (قد يرفض هنا) ← عرض الملفات ← نسخة
احتياطية ← إيقاف الخدمة ← النسخ ← الترقية ← التحقّق ← التشغيل.

**التحقّق (الخطوة 7/8)** يقرأ من القاعدة نفسها ويطبع:

```
V1_HELPER_STRICT=True            دالة المخازن مثبتة
V1_HELPER_WH=True                دالة العمليات/المواقع مثبتة
V2_ACCESS_ROWS=19                عدد صفوف CSV
V2_ACCESS_OK=True                العدد صحيح
V2_DOMAINS_OK=True               نصوص النطاقات الثلاثة صحيحة
V3_USER=<login> sees_wh=...      ما يراه كل مستخدم مقيَّد
V3_LEAKS=0                       صفر تسريب إلى فرع غريب
V4_WH_ALL=... V4_WH_BRANCHLESS=...
```

وأي قيمة غير صحيحة (دالة ناقصة، عدد صفوف خطأ، `V3_LEAKS > 0`) تُوقف
التنفيذ **قبل تشغيل الخدمة** وتُعيد تشغيلها تلقائيًّا.

**٣) للتراجع:** النسخة الاحتياطية تُطبع في نهاية السكربت، وتعاد بـ:

```bash
sudo systemctl stop odoo
pg_restore --clean --if-exists -d test20 < /var/tmp/test20_before_phase18_<الطابع>.dump
sudo systemctl start odoo
```

---

## 19. المرحلة 19: قائمة أسعار الفرع

### 19.1 العَرَض

لم تكن للفرع أي صلة بقائمة الأسعار: سعر السطر جاء دائمًا من قائمة
العميل. المطلوب:

* **القائمة تُربط بالفرع**: فرع واحد = قائمة أسعار واحدة على الأكثر،
  وقائمة واحدة قد تخدم أكتر من فرع،
* **الفرع يقود أمر البيع**: اختيار الفرع يضع قائمته على الطلب
  **ويُحدَّث تسعير سطوره**، والحقل يبقى محرَّرًا في يد المندوب.

### 19.2 القرارات (بقرار صريح، قبل الكتابة)

1. **تطبيق كامل**: تغيير الفرع داخل الفورم يغيّر `pricelist_id`
   ويستدعي `_recompute_prices()` (نفس مسار Odoo عند تغيير القائمة)،
   مع بقاء الحقل محرَّرًا، وبقاء سلوك Odoo إن لم يكن للفرش قائمة
   (تبقى قائمة العميل كما هي).
2. **الموضع**: حقل «Price List» في بطاقة الفرع، وتبويب «Branches»
   (`One2many` قابل للتحرير) في بطاقة قائمة الأسعار.
3. **الفرع بلا قائمة** ← لا شيء يتغيّر.
4. **الطلب المؤكَّد أو الملغى** لا يُمسّ إطلاقًا (نفس حالات المستودع).
5. **قائمة أسعار من شركة أخرى** لا تُؤخذ أبدًا: حارس صريح في الحساب
   + `check_company=True` على الحقل.

### 19.3 ما الذي أُضيف فعلًا (ست قطع فقط)

| الملف | الإضافة |
|---|---|
| `models/branch.py` | حقل `pricelist_id` (`Many2one` ← `product.pricelist`، `check_company=True`، مجال `company_id`) |
| `models/product_pricelist.py` **(جديد)** | `_inherit 'product.pricelist'` + `branch_ids` (`One2many` معكوسه `pricelist_id`) |
| `models/sale_order.py` | تجاوز `_compute_pricelist_id` (يضيف `branch_id` إلى الاشتراكات) + `@api.onchange('branch_id')` + امتداد `write()` لمسار غير الفورم |
| `views/branch_views.xml` | مجموعة «Sales» بحقل القائمة |
| `views/product_pricelist_views.xml` **(جديد)** | تبويب `branches` بعد `pricelist_rules` |
| `__manifest__.py` | `20.0.1.1.0` + ملف العرض الجديد |

لا حقول مخزّنة جديدة على `sale.order`، ولا صفوف `ir.access` جديدة
(لا صلاحيات خاصة بحقل القائمة: من يملك كتابة الفرع يملك ربط قائمته).

### 19.4 لماذا هذا الاتجاه بالذات — القاعدة تتحقّق من طبيعة العمود

المطلوب شرطان، واتجاه الحقل نفسه يصنعهما:

| المطلوب | كيف يتحقق |
|---|---|
| الفرع لا ينتمي لأكثر من قائمة | `branch.pricelist_id` = `Many2one` — العمود يحمل **معرّفًا واحدًا**، فلا يمكن لفرش واحد أن يحمل قائمتين. **ممنوع أصلًا**، فلا حاجة لقيد SQL |
| القائمة تخدم أكثر من فرع | `pricelist.branch_ids` = `One2many` على **نفس العمود** — كل فرع يضع معرّف قائمته، فتظهر القائمة فروعها جميعًا |

وملاحظة لو فكّرتَ في الاتجاه الآخر: جعل `branch_ids` من نوع `Many2many`
كان سيتطلب قيدًا فريدًا على عمود جدول العلاقة، و**`UNIQUE(pricelist_id)`
على `branch_branch` كانت ستُنتج العكس تمامًا** (قائمة واحدة لكل فرع،
بدل فرع واحد لكل قائمة).

النسخ لا ينسخ الفروع: `One2many.copy = False` افتراضيًّا في Odoo 20
(تحقّقنا منه في `orm/fields_relational.py` — `class One2many`)، فنسخ
قائمة أسعار لا يكرّر أي فرع؛ ونسخ فرع يحمل قائمته كما هي، وهذا مسموح
لأن القائمة تقبل أكثر من فرع.

### 19.5 نقطة الخطر — لو أسقطت أيًّا منها لم تعمل المرحلة 19

1. **`@api.depends('branch_id', 'partner_id', 'company_id')` على
   التجاوز.** `fields.py::get_depends` يمرّ على الدوال عبر
   `resolve_mro(model, compute)` ويجمع `_depends` من كل طبقة في المسار
   الوراثي، فالتعليق يُضاف فعلًا. بلا تعليق: تغيير الفرع **لا يُطلق
   إعادة الحساب إطلاقًا**.
2. **لا تجعل سعر السطر يعتمد على `pricelist_id`.** Odoo يمنع ذلك
   صراحةً في تعليق فوق `_onchange_pricelist_id_recompute_prices`
   (`sale/models/sale_order.py:1357`): «DO NOT ADD the `pricelist_id` as
   dependency …» — لأنّ ORM كان سيعيد تسعير كل سطر في كل الطلبات عند
   أي لمسة للقائمة. المسار الصحيح هو `_recompute_prices()` من
   الـ onchange، وهو ما استخدمناه.
3. **قارن مع `_origin.pricelist_id` لا مع `self.pricelist_id`.**
   دورة الـ onchange في `web/models/models.py` تُنفّذ `modified()`
   أولًا ثم `while todo`، والقراءة داخل الـ onchange تُطلق الحساب
   فتعيد **القيمة التي انت للتو ضعتها** وتُظهر نفسها دائمًا → كنتَ
   ستقفز عن إعادة التسعير.
4. **حارس `sale_onchange_first_call`** — بدونه، النداء الأول
   (عند إنشاء سجل جديد) كان سيعيد تسعير السطور قبل أن يثبت أي شيء.
5. **حارس الحالة `state in ('sale', 'cancel')`** — نفس حالات
   `_compute_warehouse_id`: مستودع الفرع لا يتحرك بعد التأكيد،
   وقائمته كذلك.
6. **`order.pricelist_id != before[order]` في `write()`** — بدونه كان
   كل تغيير فرع يمسح السعر المكتوب يدويًا حتى لو بقيت القائمة كما هي.

### 19.6 ما الذي لم يتغيّر

* **لا تعديل على نواة Odoo** — `_inherit` فقط؛ و`dpkg -V odoo` لا يظهر
  إلا `/etc/odoo/odoo.conf` (ملف إعدادات لا نواة).
* **لا حاجة لمجلّد `migrations/`** — أضفنا عمودًا جديدًا على
  `branch.branch` و`depends` جديدًا على حساب موجود. **إضافة اشتراك لا
  تجعل Odoo يعيد حساب الطلبات القائمة عند الترقية** (إعادة الحساب
  تُطلقها تغييرات البيانات لا تغيير الكود)، فطلباتك المفتوحة تبقى
  بأسعارها ولا يقع تسعير صامت يمسح ما كُتب يدويًّا.
* **لا صفوف `ir.access` جديدة** (19 كما هي)، ولا مجموعات جديدة.
* **لا `attrs`/`states`/`<tree>`** — `invisible="expr"` و`<list>` فقط.
* **سلوك Odoo محفوظ**: طلب بلا فرع أو فرع بلا قائمة يأخذ قائمة
  العميل، وتغيير العميل وحده لا يتغيّر.

### 19.7 التحقق

```bash
cd /home/admin/dev_addons/branch_management/test_suite
./run_tests.sh 19        # 11 passed, 0 failed
./run_tests.sh           # 250 passed, 0 failed, 1 skipped
```

الـ 11 اختبارًا في `test_phase19.py`:

| # | ماذا يثبت |
|---|---|
| T1 | شكل الحقول (`Many2one` على الفرع + `Many2many` غير مخزَّن بحسابه وعكسه وبحثه) واشتراكات `_compute_pricelist_id`، وأنه ما زال حقل Odoo المخزّن المحرَّر |
| T2 | الفرع يقترح قائمته والسطر يُسعَّر بها (120 بدل 100) |
| T3 | فرع بلا قائمة ← قائمة العميل وسعر الكتالوج |
| T4 | تسعيرة جديدة من الفورم تبدأ على قائمة الفرع |
| T5 | **تغيير الفرع داخل الفورم ينقل القائمة ويُعيد التسعير — ذهابًا وإيابًا** |
| T6 | سعر مكتوب يدويًا ينجو من تغيير فرع لا ينقل القائمة |
| T7 | القاعدة تعمل خارج الفورم أيضًا (`write()` ← استيراد أو استدعاء API) |
| T8 | الطلب المؤكَّد يحتفظ بقيمته وسعره |
| T9 | قائمة شركة أخرى لا تُؤخذ، والفرع يرفضها بخطأ من Odoo |
| T10 | **الشرطان معًا**: قائمة واحدة لفرعين، وفرش لا يكون إلا في قائمة واحدة |
| T11 | كلا الشاشتين تحملان الرابط |

**ملاحظة بيئية:** الحزمة تفعّل ميزة `product.group_product_pricelist`
لأن Odoo لا يحسب قائمة العميل وهي مطفأة
(`res.groups._is_feature_enabled` يسأل مستخدم 1). هذه قيد في بيئة
الاختبار لا قيد في الوحدة: **قائمة الفرع تُطبَّق وتُسعِّر السطور في
الحالتين** — وكان أول ما تحقّقنا منه أن السطر جاء 120.00 وإن كانت
الميزة مطفأة تمامًا.

### 19.8 طريقة التطبيق على test20

```bash
# لا فرق بين نسخة التطوير ونسخة الإنتاج
diff -r /home/admin/dev_addons/branch_management \
        /home/admin/custom_addons/branch_management

sudo -u odoo /usr/bin/odoo -c /etc/odoo/odoo.conf -d test20 \
     -u branch_management --stop-after-init --no-http --log-level=warn
```

* لا خطوة إضافية ولا `migrations/`.
* بعد الترقية: من **الفرع** (مجموعة `Sales` ← `Price List`) أو من
  **قائمة الأسعار** (تبويب `Branches`)، ثم جرّب أمر بيع جديد واختر
  فرعًا له قائمة وراقب تغيّر السطر وتغيّر الإجمالي.

---

## 20. المرحلة 20: قفل قائمة أسعار الطلب، وإضافة فرع موجود لقائمة الأسعار

مرحلتان تتبعان مباشرة لـ 19، بطلبَين منك:

1. «لو البرنش مربوط ببريس ليست مينفعش اغير في السيلز اوردار البريس ليست دا»
2. «ثانيا انت ضفت تابت البرينش في البريس ليست انا عاوز اضيف برنش موجود مش
   انشاء برنش في التابه»

### 20.1 العَرَض

**أولًا:** فرع له قائمة أسعار، فتحت أمر بيع بهذا الفرع وبدّل القائمة من
الحقل الظاهر ← السطور تُسعَّر بقائمة أخرى والفرع يبقى على قائمته، فلا
يجب أن يقبل Odoo هذا التغيير.

**ثانيًا:** تبويب `Branches` في بطاقة قائمة الأسعار كان `One2many`، وزر
«Add» فيه يفتح **نموذج إنشاء فرع جديد**، وحذف سطر فيه **يحذف الفرع نفسه**.

### 20.2 القرار الأول: القفل — ثلاث طبقات

| الطبقة | الأثر |
|---|---|
| حقل محسوب غير مخزَّن `sale.order.has_branch_pricelist` | = `True` حين يحمل `branch_id.pricelist_id` شركة متوافقة مع `company_id` |
| قيد في الفورم (على **عقدتَيْ** `pricelist_id`) | `readonly="state in ['cancel','sale'] or has_branch_pricelist"` — الحقل يُصبح للقراءة فقط فلا يدخل في حفظ Odoo أصلًا |
| حارس في `write()` — `_check_pricelist_written()` | يرفع `ValidationError` على أي محاولة تغيير بيدٍ أخرى (استيراد، استدعاء API، `write` مباشر) |

**الطبقة الأولى تفصيلية:**

```python
has_branch_pricelist = fields.Boolean(
    compute='_compute_has_branch_pricelist', ...)

@api.depends('branch_id.pricelist_id', 'company_id')
def _compute_has_branch_pricelist(self):
    # True فقط لو القائمة موجودة فعلًا وشركة الفرع تطابق شركة الطلب
```

**الطبقة الثانية — ولماذا حقل محسوب وليس `branch_id.pricelist_id` في القيد؟**
لأنّ **المُعدِّلات المُنقَّطة (dotted modifiers) لا تعمل على حقل مالتي-أون في
Odoo 20**: `record.js:_computeDataContext` يضع قيمة الحقل المالتي-أون
**كعدد** (`value.id`)، فيصير `left['pricelist_id']` = رقم، ثم
`left['pricelist_id']['company_id']` = `undefined` → يبقى المُعدِّل غير مطبَّق
**صامتًا**. وهذا خلل خفي في بعض وحدات Odoo نفسها (مثل
`quality_control` مع `point_id.spreadsheet_template_id`)، فاعتمادنا عليه كان
ستعطيك واجهة تبدو مقفلة وليست كذلك. أما الحقل المحسوب `has_branch_pricelist`
فهو **منطقيٌّ بسيط** فيسأله Odoo دون تقليب، وإذ لم يكن مخزَّنًا وجب أن يكون
**محمّلًا في الفورم** ليقرأه المُعدِّل — ومن ثم أضفناه صراحةً
`<field name="has_branch_pricelist" invisible="1" readonly="1"/>` داخل
`order_details`.

العقدتان اللتين أُصِيبتا في `views/sale_order_views.xml` هما:

```xml
<xpath expr="//field[@name='pricelist_id' and not(@invisible)]" position="attributes">
<xpath expr="//field[@name='pricelist_id' and @invisible]"        position="attributes">
```

ومع `groups="product.group_product_pricelist"` على إحداهما، يظهر **إحداهما
فقط** في كل حساب — ومن ثم وجبت العقدتان معًا: بمعزل عن واحدة منهما كان
مستخدم لا يملك المجموعة يرى الحقل غير مقفل (وهو بالضبط ما ظهر في الفحص
الحيّ: العقدة المُخفية ثم الظاهرة تبًا).

**الطبقة الثالثة — الحارس:**

```python
def write(self, vals):
    res = super().write(vals)
    if 'pricelist_id' in vals:
        self._check_pricelist_written(vals)   # يتجاوز state in ('sale','cancel')
    return res
```

الحارس يتجاوز ثلاثة أحوال فلا يرفع خطأ فيها:

1. **الطلب المؤكَّد أو المُلغى** — قاعدة Odoo نفسها تحميه (الحقل غير قابل
   للتغيير بعد التأكيد)، فلا نضاعف الحظر.
2. **قائمة أسعار لا تُقترح أصلًا** (`company_id` في الشركة الأخرى) —
   `_compute_pricelist_id` لا تضعها، فلا معنى لقفلها على قاعدة لا تصل
   إليها أبدًا.
3. **الكتابة بنفس القيمة** — لا تغيير فلا خطأ.

وحين يتحرّك الفرع إلى فرع بلا قائمة، يعود `has_branch_pricelist` `False`
**لحظيًّا** (الحساب غير مخزَّن) ويصبح تغيير القائمة ممكنًا من جديد.

### 20.3 القرار الثاني: `Many2many` غير مخزَّن بدل `One2many`

حقل جديد على `product.pricelist`:

```python
branch_ids = fields.Many2many(
    'branch.branch', string='Branches',
    compute='_compute_branch_ids',
    inverse='_inverse_branch_ids',
    search='_search_branch_ids',   # إلزامي — انظر 20.4(5)
)
```

**لماذا `Many2many` لا `One2many`؟** فرق سلوكي مُتحقَّق منه في المصدر:

| | `One2many` (قبل) | `Many2many` (الآن) |
|---|---|---|
| زر «Add» | يفتح **نموذج إنشاء** | يفتح **نافذة البحث** (`x2many_field.js:292` → `isMany2Many` → `selectCreate`) |
| حذف سطر | **يحذف الفرع** من قاعدة البيانات | يفكّ الارتباط فقط، الفرع يبقى |
| عدد النسخ من الرابط | عمود على الفرع | **عمود واحد على الفرع** (لأن الحقل غير مخزَّن) |

**وإذن «فرع واحد في قائمة واحدة» لا يزال محفوظًا** — لا لأنه في هذا
الحقل، بل لأن العمود الوحيد هو `branch.pricelist_id` (ملتى-أون). وحين
تضيف فرعًا لقائمة يحمله آخر بالفعل، فإن النتيجة أنه **ينتقل**: عكس الحقل
يكتب على الفرع نفسه.

```python
@api.depends('branch_ids.pricelist_id')
def _compute_branch_ids(self):        # يقرأ من الأعمدة

def _inverse_branch_ids(self):        # قبل = فروع تشير إلينا، بعد = ما وصل
    # gone   = (before - after) المُصرَّة على أنها لا تزال تشير إلينا
    # arrived = after → نكتب pricelist_id
```

شروط الحارس في `write()` لا تغيّر: `state in ('sale','cancel')` محفوظ،
والشركة الأجنبية مُستثناة.

**الفرع المؤرشف لا يظهر في التبويب ولا يخسر قائمته:** `Branch.search`
يستخدم `active_test` الافتراضي، فيخرج الفرع المؤرشف من القراءة **ومن
مجموعة `before` معًا** — فلا يدخل ضمن `gone` فلا يُمسَح.

### 20.4 نقاط الخطر — لو أسقطت أيًّا منها لم تعمل المرحلة 20

1. **`search='_search_branch_ids'` إلزامي لا تحسين.** بدونه يرفض Odoo
   الاعتماد المعلن:
   `Field 'product.pricelist.branch_ids' in dependency of ... should be
   searchable` (`orm/fields.py:964`)، لأن `_description_searchable`
   يساوي `bool(store or search)` (`:1030`). والبحث ضروري أيضًا عمليًّا:
   من دونه لا يعرف Odoo أي من قوائم الأسعار يُعاد حسابها حين يتحرّك
   `branch.pricelist_id` — وهو بالضبط ما يجعل التبويب صحيحًا بعد تعديل
   من مكان آخر.
2. **`('branch_ids', '=', False)` يعود إلى Odoo على شكل
   `('branch_ids', 'in', [False])`** لحقل علائقي، وقيم `in` قد تصل
   `OrderedSet`. المُطبِّق يعالج الحالتين؛ وإلا انحرف البحث (أو انهار
   بـ `TypeError: unhashable type: 'OrderedSet'`).
3. **`store=False` على `Many2many` مسموح** في Odoo 20
   (`write_batch` يفرّق على `self.store`)، والكتابة بـ inverse غير
   مخزَّن مدعومة في `orm/models.py` (مسار الإنشاء والكتابة مع إبطال
   الذاكرة بعد العكس ثم `_validate_fields`).
4. **`<list>` لا تُستبدل بـ `<list create="0">` ولا تُحذف** — بقاء
   القائمة هو ما يجعل زر «Add» يستدعي `selectCreate` (حوار البحث)،
   وحذف السطر يفكّ ارتباطًا ولا يمسّ الفرع.
5. **نطاق الشركة يُكتب شرطًا لا بمنطق منطقي:**
   `domain="company_id and [('company_id', '=', company_id)] or []"`
   — دوال `BoolOp` مدعومة صراحةً في `tools/view_validation.py`،
   وهو يكرّر سلوك `check_company` بالضبط: قائمة بلا شركة تقبل **كل**
   الفروع، لا لا شيء.
6. **`has_branch_pricelist` يُضاف صراحةً إلى `order_details`**
   (`<field invisible="1" readonly="1"/>`) — حتى لا يبقى الاسم في
   مُعدِّل والحقول المستدعاة لقراءته غير محمّلة في الفورم. (الحقيقة أن
   `_add_missing_fields` في `ir_ui_view.py:1546` كان يدفعها وحده — وهذا
   ما يفعله Odoo مع `has_active_pricelist` التي ليس لها عقدة في العرض
   أصلًا — لكننا أبقينها صريحة حتى لا تعتمد الحالة على خطوة مساعدة.)
7. **`@api.depends('branch_ids.pricelist_id')` يشبه التوالي المتأقلم** —
   لو ظهرت النذير `should be declared with recursive=True` فهو تشبيه لا
   تكرار: مسار الاعتماد `branch_ids ← pricelist_id` يمرّ من جانبين
   مختلفين، وسجل Odoo لا يكتشف دورة حساب (`grep cyclic` صفر في `orm`).

### 20.5 ما الذي لم يتغيّر

* **صفر تعديل على نواة Odoo** — `_inherit` فقط، و`dpkg -V odoo` لا يظهر
  إلا `/etc/odoo/odoo.conf`.
* **لا حاجة لمجلّد `migrations/`** — لم نُضِف عمودًا مخزَّنًا واحدًا:
  `has_branch_pricelist` و`branch_ids` كلاهما غير مخزَّن.
* **`state in ('sale','cancel')` لا تُلمس** — أمر بيع مؤكَّد يبقى كما هو.
* **`ir.access` 19 صفًا كما هي**، ولا مجموعات جديدة، ولا `attrs`/`states`/
  `<tree>` — `invisible="expr"` و`<list>` فقط.
* **لا ربط لسعر السطر بـ `pricelist_id`** (تعليق Odoo الممنوع في
  `sale/models/sale_order.py:1357`).

### 20.6 التحقق

```bash
cd /home/admin/dev_addons/branch_management/test_suite
./run_tests.sh 20        # 12 passed, 0 failed
./run_tests.sh           # 250 passed, 0 failed, 1 skipped
```

الـ 12 اختبارًا في `test_phase20.py`:

| # | ماذا يثبت |
|---|---|
| T1 | شكل الحقول: `Many2one` على الفرع (المصدر الوحيد) + `Many2many` غير مخزَّن بـ `compute`/`inverse`/`search` |
| T2 | إضافة **فرع موجود** من تبويب القائمة لا تنشئ فرعًا (عدّاد الفروع ثابت) |
| T3 | فرع لا يكون في قائمتين: يُضاف لقائمة أخرى ← **ينتقل** والأولى تفقده |
| T4 | حذف سطر يفكّ الارتباط فقط: القائمة تُشط من الفرع والفرع **يبقى** |
| T5 | قائمة واحدة تحمل فروعًا متعدّدة |
| T6 | التبويب **قراءة** للعمود: تعديل من جهة الفرع يظهر فورًا، والبحث بالفروع يجد القائمة |
| T7 | تأريف الفرع لا يخسره قائمته (يخرج من التبويب ومن مجموعة `before` معًا) |
| T8 | **فورم الطلب يرسم القفل**: العقدتان تحملان `has_branch_pricelist` والحقل موجود في الفورم |
| T9 | **الحارس يعمل**: `ValidationError` عند تغيير القائمة، ومجانية الحقل حين لا يحمل الفرع قائمة، وقائمة شركة أخرى لا تُقفل شيئًا، وتغيير الفرع ينقل القائمة |
| T10 | القاعدة تنجو في **فورم Odoo** الذي يتخطّى الحقول للقراءة فقط |
| T11 | تبويب `Branches`: `<list>` بأعمدتها، والنطاق يقيّم `[('company_id','=',X)]` للقائمة المشركة و`[]` لقائمة بلا شركة |
| T12 | إنشاء قائمة **مع فروعها في نداء واحد** يعمل كالإضافة لاحقًا |

**ملاحظة بيئية:** مثل المرحلة 19، تُفعِّل الحزمة
`product.group_product_pricelist` لأن Odoo لا يحسب قائمة العميل وهي
مطفأة. وهذا لا علاقة له بالقفل: `has_branch_pricelist` تسأل `branch_id.pricelist_id`
وهي عمود مخزَّن لا يحتاج الميزة.

### 20.7 طريقة التطبيق على test20

```bash
diff -r /home/admin/dev_addons/branch_management \
        /home/admin/custom_addons/branch_management   # لا فرق

sudo -u odoo /usr/bin/odoo -c /etc/odoo/odoo.conf -d test20 \
     -u branch_management --stop-after-init --no-http --log-level=warn
```

بعد الترقية جرّب شيئين: (1) أمر بيع لفرع له قائمة أسعار ← جرّب تغيير
القائمة من القائمة المنسدلة (لا يتغيّر)؛ (2) بطاقة قائمة أسعار ← تبويب
`Branches` ← «Add» ← تظهر **نافذة البحث عن فرع موجود** لا نموذج إنشاء،
واحذف السطر ← الفرع لا يُحذف بل يُشط فقط.
