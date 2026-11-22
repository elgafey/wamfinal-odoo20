# -*- coding: utf-8 -*-
# اختبارات المرحلة 2 لوحدة branch_management (odoo shell)
# ملاحظة: أخطاء UNIQUE ترفع IntegrityError في Odoo 20 (سلوك core نفسه)،
# ولذلك يُغلَف كل "متوقع الفشل" في savepoint حتى لا تنكسر المعاملة.
results = {'PASS': [], 'FAIL': [], 'SKIP': []}


def check(name, cond, extra=''):
    key = 'PASS' if cond else 'FAIL'
    results[key].append(name)
    print('%s | %s%s' % (key, name, ('   -> ' + str(extra)) if (extra and not cond) else ''))
    return cond


def skip(name, why=''):
    results['SKIP'].append(name)
    print('SKIP | %s   -> %s' % (name, why))


def expect_failure(fn):
    """شغّل fn المتوقَّع فشلها داخل savepoint؛ تعيد الاستثناء أو None."""
    try:
        with env.cr.savepoint():
            fn()
        env.invalidate_all()
        return None
    except Exception as e:
        env.invalidate_all()
        return e


# ---------------- T0: التثبيت وقيود قاعدة البيانات ----------------
mod = env['ir.module.module'].sudo().search([('name', '=', 'branch_management')])
check('T0  module installed', mod.state == 'installed', mod.state)

env.cr.execute("""SELECT pg_get_constraintdef(oid) FROM pg_constraint
                  WHERE conrelid = 'branch_branch'::regclass AND contype = 'u'""")
defs = [r[0] for r in env.cr.fetchall()]
check('T0b UNIQUE(company_id, code) exists in DB',
      any('company_id' in d and 'code' in d for d in defs), defs)

env.cr.execute("""SELECT c.name, c.message->>'en_US' FROM ir_model_constraint c
                  WHERE c.name = 'branch_branch_code_company_unique'""")
row = env.cr.fetchone()
check('T0c constraint message reflected in ir.model.constraint',
      bool(row) and 'unique inside its company' in (row[1] or ''), row)

company = env.company
WH = env['stock.warehouse'].search([('company_id', '=', company.id)], limit=1)
check('T0d main company has a warehouse', bool(WH))

Branch = env['branch.branch'].with_context(active_test=False)

# ---------------- T1 / T2: إنشاء فرع + حساب تحليلي تلقائي ----------------
b1 = Branch.create({
    'name': 'Riyadh Branch', 'code': 'BR-RYD',
    'company_id': company.id, 'warehouse_id': WH.id,
})
check('T1  branch created and active', bool(b1.id) and b1.active)
check('T2  analytic account auto-created', bool(b1.analytic_account_id), 'no account')
check('T2b analytic name = "[code] - name"',
      b1.analytic_account_id.name == 'BR-RYD - Riyadh Branch',
      b1.analytic_account_id.name)
check('T2c analytic code copied', b1.analytic_account_id.code == 'BR-RYD',
      b1.analytic_account_id.code)
check('T2d analytic plan = Branches plan',
      b1.analytic_account_id.plan_id == env.ref('branch_management.analytic_plan_branches'),
      b1.analytic_account_id.plan_id.display_name)
check('T2e analytic company = branch company', b1.analytic_account_id.company_id == company)
check('T3  default stock location = warehouse stock location',
      b1.default_stock_location_id == WH.lot_stock_id,
      '%s vs %s' % (b1.default_stock_location_id, WH.lot_stock_id))
check('T3b warehouse linked', b1.warehouse_id == WH)

# ---------------- T4: تفرّد الكود داخل الشركة ----------------
err = expect_failure(lambda: Branch.create(
    {'name': 'Duplicate', 'code': 'BR-RYD', 'company_id': company.id}))
check('T4  duplicate code rejected inside same company', err is not None,
      'no error raised')
if err is not None:
    print('     (%s: %s)' % (type(err).__name__, str(err).split('\n')[0][:100]))
    msg = env['branch.branch']._sql_error_to_message(err)
    check('T4c message shown to the user = our constraint message',
          'unique inside its company' in msg, msg)

# ---------------- T5: المخزن يخص فرعًا واحدًا ----------------
err = expect_failure(lambda: Branch.create(
    {'name': 'Other Branch', 'code': 'BR-OTH',
     'company_id': company.id, 'warehouse_id': WH.id}))
check('T5  warehouse cannot be linked to two branches', err is not None,
      'no error raised')

# ---------------- T4b / T6: شركة ثانية ----------------
company2 = b2 = None
try:
    company2 = env['res.company'].create({'name': 'Branch Test Company'})
except Exception as e:
    skip('T4b/T6 tests needing a second company', 'res.company.create: %s' % e)

if company2:
    err = expect_failure(lambda: None)  # placeholder no-op
    err = expect_failure(lambda: Branch.create(
        {'name': 'Second Company Branch', 'code': 'BR-RYD', 'company_id': company2.id}))
    check('T4b same code allowed in another company', err is None,
          err and '%s: %s' % (type(err).__name__, err))
    if err is None:
        b2 = Branch.with_context(active_test=False).search(
            [('code', '=', 'BR-RYD'), ('company_id', '=', company2.id)], limit=1)

# ---------------- T5b: إعداد "مخزن واحد = فرع واحد" ----------------
company.branch_warehouse_exclusive = False
b3 = None
err = expect_failure(lambda: Branch.create(
    {'name': 'Shared WH Branch', 'code': 'BR-SHR',
     'company_id': company.id, 'warehouse_id': WH.id}))
check('T5b shared warehouse allowed when company setting is off', err is None,
      err and '%s: %s' % (type(err).__name__, err))
if err is None:
    b3 = Branch.with_context(active_test=False).search([('code', '=', 'BR-SHR')], limit=1)

if company2 and b2:
    # التفريد مُعطَّل ⇒ الخطأ هنا هو قيد الشركة حتمًا
    err = expect_failure(lambda: b2.write({'warehouse_id': WH.id}))
    check('T6  warehouse of another company rejected', err is not None, 'no error raised')
    if err is not None:
        print('     (%s)' % type(err).__name__)

    WH2 = env['stock.warehouse'].search([('company_id', '=', company2.id)], limit=1)
    if WH2:
        err = expect_failure(lambda: b1.write({'warehouse_id': WH2.id}))
        check('T6b warehouse of another company rejected (reverse)', err is not None,
              'no error raised')
        if err is None:
            b1.warehouse_id = WH  # استعادة
    else:
        skip('T6b reverse cross-company test', 'no auto warehouse for 2nd company')

if b3:
    b3.unlink()
company.branch_warehouse_exclusive = True

# ---------------- T7 / T16: الحساب التحليلي ----------------
plan = env.ref('branch_management.analytic_plan_branches')
shared = env['account.analytic.account'].create({
    'name': 'Shared Analytic Account', 'plan_id': plan.id, 'company_id': False,
})
err = expect_failure(lambda: b1.write({'analytic_account_id': shared.id}))
check('T7a branch may use a company-less analytic account', err is None,
      err and '%s: %s' % (type(err).__name__, err))

if b2:
    err = expect_failure(lambda: b2.write({'analytic_account_id': shared.id}))
    check('T7b same analytic account rejected on a second branch', err is not None,
          'no error raised')

if company2:
    acc2 = env['account.analytic.account'].create({
        'name': 'CO2 Analytic', 'plan_id': plan.id, 'company_id': company2.id,
    })
    err = expect_failure(lambda: b1.write({'analytic_account_id': acc2.id}))
    check('T16 analytic account of another company rejected', err is not None,
          'no error raised')

# ---------------- T8: الأرشفة ----------------
b1.active = False
hidden = env['branch.branch'].search([('id', '=', b1.id)])
check('T8  archived branch hidden by default', b1.id not in hidden.ids)
check('T8b archived branch visible with active_test=False',
      b1.id in Branch.search([('id', '=', b1.id)]).ids)
b1.active = True

# ---------------- T9: العروض ----------------
views = env['ir.ui.view'].sudo().search([('model', '=', 'branch.branch')])
types = set(views.mapped('type'))
check('T9  list/form/search views registered', {'list', 'form', 'search'} <= types, types)

# ---------------- T10: الأكشن والقوائم ----------------
action = env.ref('branch_management.branch_action')
check('T10 action model + view modes',
      action.res_model == 'branch.branch' and action.view_mode == 'list,form',
      action.view_mode)
for xid in ('menu_branch_sales', 'menu_branch_stock', 'menu_branch_account'):
    menu = env.ref('branch_management.' + xid)
    check('T10 %s linked to action' % xid, menu.action == action, menu.action)
    check('T10 %s has parent menu' % xid, bool(menu.parent_id), 'parent missing')

# ---------------- T11: صلاحيات branch.branch (استُكملت في المرحلة 3) ----------------
acl = env['ir.access'].sudo().search([('model_id.model', '=', 'branch.branch')])
perm = acl.filtered(lambda a: a.group_id)
restr = acl - perm
check('T11 4 ACL rows (3 permissions + 1 restriction)',
      len(acl) == 4 and len(perm) == 3 and len(restr) == 1,
      [(a.group_id.name, a.operation, a.domain) for a in acl])

# ---------------- T12: إعدادات الشركة ----------------
check('T12 branch_analytic_auto defaults to True', env.company.branch_analytic_auto is True)
check('T12b branch_warehouse_exclusive defaults to True',
      env.company.branch_warehouse_exclusive is True)

# ---------------- T13: auto_create_analytic ----------------
b4 = Branch.create({'name': 'No Auto Branch', 'code': 'BR-NON',
                    'company_id': company.id, 'auto_create_analytic': False})
check('T13 no analytic account when auto-create is off',
      not b4.analytic_account_id, b4.analytic_account_id.display_name)
b4.auto_create_analytic = True
check('T13b analytic created when auto-create switched on',
      bool(b4.analytic_account_id), 'not created')

# ---------------- T14: البحث بالكود ----------------
ns = env['branch.branch'].with_context(active_test=False).name_search('BR-RYD')
check('T14 name_search finds the branch by its code',
      b1.id in [i[0] for i in ns], ns)

# ---------------- T15: الإنشاء المتعدد ----------------
b5, b6 = Branch.create([
    {'name': 'Branch M1', 'code': 'BR-M1', 'company_id': company.id},
    {'name': 'Branch M2', 'code': 'BR-M2', 'company_id': company.id},
])
check('T15 multi-create gives both an analytic account',
      bool(b5.analytic_account_id) and bool(b6.analytic_account_id))

# ---------------- T4d: تفرّد الكود عند التعديل ----------------
err = expect_failure(lambda: b5.write({'code': 'BR-RYD'}))
check('T4d duplicate code rejected on write too', err is not None, 'no error raised')

print('')
print('==== SUMMARY ====')
print('PASS: %d | FAIL: %d | SKIP: %d' % (
    len(results['PASS']), len(results['FAIL']), len(results['SKIP'])))
for n in results['FAIL']:
    print('  FAILED :', n)
for n in results['SKIP']:
    print('  SKIPPED:', n)

env.cr.rollback()
print('rolled back (test data removed)')
