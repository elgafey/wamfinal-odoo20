import base64
import datetime
import json

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import SqlwCase


@tagged('post_install', '-at_install')
class TestSavedQueries(SqlwCase):

    def test_validation_dry_run(self):
        q = self.make_query(sql="SELECT id, login FROM res_users WHERE create_date >= :since")
        self.assertEqual(q.state, 'draft')
        q.action_validate()  # detects :since, declares it as a date and dry-runs the SQL
        self.assertEqual(q.state, 'valid')
        self.assertEqual(q.param_ids.name, 'since')
        self.assertEqual(q.param_ids.ptype, 'date')
        bad = self.make_query(sql="SELECT nope FROM res_users")
        with self.assertRaises(UserError):
            bad.action_validate()
        self.assertEqual(bad.state, 'draft')
        blocked = self.make_query(sql="DELETE FROM res_users")
        with self.assertRaises(UserError):
            blocked.action_validate()

    def test_sharing_requires_validation(self):
        q = self.make_query()
        with self.assertRaises(ValidationError):
            q.group_ids = [(4, self.share_group.id)]
        with self.assertRaises(ValidationError):
            q.write({'digest_active': True, 'digest_user_ids': [(4, self.manager.id)]})
        q.action_validate()
        q.group_ids = [(4, self.share_group.id)]
        self.assertEqual(q.state, 'valid')

    def test_edit_shared_revalidates_unshared_goes_draft(self):
        q = self.make_query()
        q.action_validate()
        q.sql = "SELECT id FROM res_users"
        self.assertEqual(q.state, 'draft')
        q.action_validate()
        q.group_ids = [(4, self.share_group.id)]
        q.sql = "SELECT id, login FROM res_users"
        self.assertEqual(q.state, 'valid')
        with self.assertRaises(UserError):
            q.sql = "SELECT broken FROM res_users"

    def test_change_tracking_in_chatter(self):
        q = self.make_query()
        self.env.flush_all()
        self.env.cr.precommit.run()  # end of the creating transaction
        q.sql = "SELECT 1 AS one"
        q.write({'param_ids': [(0, 0, {'name': 'limit_rows', 'ptype': 'integer', 'label': 'Rows'})]})
        self.env.flush_all()
        self.env.cr.precommit.run()
        body = ' '.join(self.env['mail.message'].sudo().search([
            ('model', '=', 'sql.query'), ('res_id', '=', q.id), ('message_type', '=', 'tracking')]).mapped('body'))
        self.assertIn('(%s)' % q._fields['sql'].string, body)
        self.assertIn('(%s)' % q._fields['param_signature'].string, body)

    def test_typed_parameters_and_dynamic_defaults(self):
        partner_model = self.env.ref('base.model_res_partner')
        q = self.make_query(sql=(
            "SELECT :d::date AS d, :dt::timestamp AS dt, :i AS i, :f AS f, :t AS t, :b AS b, :s AS s, "
            ":rec AS rec, array_length(:recs::int[], 1) AS n"), param_ids=[
            (0, 0, {'name': 'd', 'ptype': 'date', 'default_kind': 'start_of_month', 'required': True}),
            (0, 0, {'name': 'dt', 'ptype': 'datetime', 'default_kind': 'today'}),
            (0, 0, {'name': 'i', 'ptype': 'integer', 'default_kind': 'fixed', 'default_value': '12'}),
            (0, 0, {'name': 'f', 'ptype': 'float'}),
            (0, 0, {'name': 't', 'ptype': 'char'}),
            (0, 0, {'name': 'b', 'ptype': 'boolean', 'default_kind': 'fixed', 'default_value': 'true'}),
            (0, 0, {'name': 's', 'ptype': 'selection', 'selection_options': 'a:Alpha\nb:Beta'}),
            (0, 0, {'name': 'rec', 'ptype': 'many2one', 'model_id': partner_model.id,
                    'default_kind': 'current_company'}),
            (0, 0, {'name': 'recs', 'ptype': 'many2many', 'model_id': partner_model.id}),
        ])
        q.action_validate()
        screen = q.get_run_screen()
        by_name = {p['name']: p for p in screen['params']}
        today = fields.Date.context_today(q)
        self.assertEqual(by_name['d']['value'], today.replace(day=1).isoformat())
        self.assertEqual(by_name['i']['value'], 12)
        self.assertEqual(by_name['s']['options'], [['a', 'Alpha'], ['b', 'Beta']])
        self.assertEqual(by_name['rec']['model'], 'res.partner')
        res = q.run_query({'f': '2.5', 't': 'hello', 's': 'b', 'recs': [1, 2, 3], 'd': '2026-02-03'})
        self.assertTrue(res['ok'], res)
        row = dict(zip([c['name'] for c in res['columns']], res['rows'][0]))
        self.assertEqual(row['d'], '2026-02-03')
        self.assertEqual(row['i'], 12)
        self.assertEqual(row['f'], 2.5)
        self.assertEqual(row['t'], 'hello')
        self.assertIs(row['b'], True)
        self.assertEqual(row['s'], 'b')
        self.assertEqual(row['rec'], self.env.company.id)
        self.assertEqual(row['n'], 3)
        bad = q.run_query({'i': 'twelve'})
        self.assertEqual(bad['status'], 'blocked')

    def test_required_parameter(self):
        q = self.make_query(sql="SELECT :x AS x", param_ids=[(0, 0, {'name': 'x', 'ptype': 'char', 'required': True})])
        q.action_validate()
        res = q.run_query({})
        self.assertEqual(res['status'], 'blocked')
        self.assertTrue(q.run_query({'x': 'ok'})['ok'])

    def test_parameter_definition_checks(self):
        with self.assertRaises(ValidationError):
            self.make_query(param_ids=[(0, 0, {'name': 'user_id', 'ptype': 'integer'})])
        with self.assertRaises(ValidationError):
            self.make_query(param_ids=[(0, 0, {'name': '1bad', 'ptype': 'integer'})])
        with self.assertRaises(ValidationError):
            self.make_query(param_ids=[(0, 0, {'name': 'r', 'ptype': 'many2one'})])
        with self.assertRaises(ValidationError):
            self.make_query(param_ids=[(0, 0, {'name': 's', 'ptype': 'selection'})])

    def test_undeclared_placeholder_blocks_saved_query(self):
        q = self.make_query(sql="SELECT :undeclared AS u")
        with self.assertRaises(UserError):
            q._validate_sql()
        self.assertEqual(q.run_query({})['status'], 'blocked')

    def test_fiscal_year_default_without_accounting(self):
        start = self.ws._dynamic_default('start_of_fiscal_year')
        self.assertIsInstance(start, datetime.date)
        self.assertLessEqual(start, fields.Date.context_today(self.ws))

    def test_column_link_override(self):
        q = self.make_query(sql="SELECT u.partner_id AS customer, 3 AS other FROM res_users u WHERE u.login = 'admin'",
                            column_model_ids=[(0, 0, {'column_name': 'other',
                                                      'model_id': self.env.ref('base.model_res_country').id})])
        res = q.run_query({})
        models = {c['name']: c['model'] for c in res['columns']}
        self.assertEqual(models['customer'], 'res.partner')  # detected from the source column
        self.assertEqual(models['other'], 'res.country')  # override

    def test_run_log_fields(self):
        q = self.make_query(sql="SELECT id FROM res_users WHERE id = :uid_param",
                            param_ids=[(0, 0, {'name': 'uid_param', 'ptype': 'integer', 'default_kind': 'fixed',
                                               'default_value': '2'})])
        q.action_validate()
        res = q.with_user(self.manager).run_query({})
        run = self.env['sql.query.run'].browse(res['run_id'])
        self.assertEqual(run.query_id, q)
        self.assertEqual(run.user_id, self.manager)
        self.assertEqual(run.origin, 'saved')
        self.assertEqual(run.status, 'success')
        self.assertEqual(json.loads(run.params_text)['uid_param'], 2)
        self.assertEqual(run.company_id, self.manager.company_id)
        self.assertEqual(q.run_count, 2)  # validation + run

    def test_retention_cron(self):
        res = self.ws.with_user(self.sql_user).console_run("SELECT 1")
        old = self.env['sql.query.run'].browse(res['run_id'])
        self.env.flush_all()
        self.env.cr.execute("UPDATE sql_query_run SET create_date = %s WHERE id = %s",
                            [fields.Datetime.now() - relativedelta(days=200), old.id])
        recent = self.env['sql.query.run'].browse(self.ws.with_user(self.sql_user).console_run("SELECT 2")['run_id'])
        self.env['sql.query.run']._cron_purge()
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())
        self.set_param('retention_days', 0)
        self.env['sql.query.run']._cron_purge()
        self.assertTrue(recent.exists())

    def test_publish_menu(self):
        q = self.make_query()
        with self.assertRaises(UserError):
            q.action_publish_menu()
        q.action_validate()
        with self.assertRaises(UserError):
            q.action_publish_menu()  # not shared yet
        q.group_ids = [(4, self.share_group.id)]
        q.action_publish_menu()
        self.assertTrue(q.menu_id)
        self.assertEqual(q.menu_id.parent_id, self.env.ref('sql_query_workbench.menu_sql_reports_root'))
        self.assertIn(self.share_group, q.menu_id.group_ids)
        self.assertEqual(q.client_action_id.tag, 'sql_query_workbench.run')
        self.assertEqual(q.client_action_id.params, {'query_id': q.id})
        q.name = 'Renamed report'
        self.assertEqual(q.menu_id.name, 'Renamed report')
        visible = self.env['ir.ui.menu'].with_user(self.reader)._visible_menu_ids()
        self.assertIn(q.menu_id.id, visible)
        self.assertNotIn(q.menu_id.id, self.env['ir.ui.menu'].with_user(self.employee)._visible_menu_ids())
        menu, action = q.menu_id, q.client_action_id
        q.action_unpublish_menu()
        self.assertFalse(menu.exists())
        self.assertFalse(action.exists())

    def test_unlink_removes_menu(self):
        q = self.make_query()
        q.action_validate()
        q.group_ids = [(4, self.share_group.id)]
        q.action_publish_menu()
        menu = q.menu_id
        q.unlink()
        self.assertFalse(menu.exists())

    def test_reset_draft_unshares(self):
        q = self.make_query()
        q.action_validate()
        q.write({'group_ids': [(4, self.share_group.id)]})
        q.action_publish_menu()
        q.action_reset_draft()
        self.assertEqual(q.state, 'draft')
        self.assertFalse(q.group_ids or q.menu_id)

    def test_email_digest(self):
        q = self.make_query(sql="SELECT id, login FROM res_users WHERE login = 'admin'")
        q.action_validate()
        q.write({'digest_active': True, 'digest_interval': 'weekly', 'digest_format': 'csv',
                 'digest_user_ids': [(4, self.manager.id)],
                 'digest_partner_ids': [(4, self.env['res.partner'].create({'name': 'Ext', 'email': 'ext@example.com'}).id)]})
        self.assertTrue(q.digest_next)
        q.digest_next = fields.Datetime.now() - relativedelta(minutes=5)
        before = self.env['mail.mail'].search_count([])
        self.env['sql.query']._cron_send_digests()
        mails = self.env['mail.mail'].search([], order='id desc', limit=1)
        self.assertEqual(self.env['mail.mail'].search_count([]), before + 1)
        self.assertEqual(set(mails.recipient_ids.ids), set((self.manager.partner_id | q.digest_partner_ids).ids))
        self.assertEqual(mails.attachment_ids.mimetype, 'text/csv')
        self.assertIn(b'admin', mails.attachment_ids.raw.content)
        self.assertGreater(q.digest_next, fields.Datetime.now() + relativedelta(days=6))
        self.assertTrue(q.digest_last)
        self.assertEqual(self.env['sql.query.run'].search([('query_id', '=', q.id)], limit=1).origin, 'digest')
        # not due: nothing sent
        self.env['sql.query']._cron_send_digests()
        self.assertEqual(self.env['mail.mail'].search_count([]), before + 1)

    def test_email_digest_skips_empty(self):
        q = self.make_query(sql="SELECT id FROM res_users WHERE false")
        q.action_validate()
        q.write({'digest_active': True, 'digest_user_ids': [(4, self.manager.id)], 'digest_skip_empty': True,
                 'digest_next': fields.Datetime.now() - relativedelta(minutes=1)})
        before = self.env['mail.mail'].search_count([])
        self.env['sql.query']._cron_send_digests()
        self.assertEqual(self.env['mail.mail'].search_count([]), before)
        self.assertEqual(self.env['sql.query.run'].search([('query_id', '=', q.id)], limit=1).origin, 'digest')
        q.action_send_digest_now()  # manual send ignores "skip empty"
        self.assertEqual(self.env['mail.mail'].search_count([]), before + 1)
        with self.assertRaises(ValidationError):
            q.digest_user_ids = [(5, 0, 0)]

    def test_library_roundtrip(self):
        group_xmlid = 'base.group_user'
        q = self.make_query(name='Lib query', description='notes', sql="SELECT :n::int AS n",
                            tag_ids=[(0, 0, {'name': 'LibTag'})],
                            param_ids=[(0, 0, {'name': 'n', 'ptype': 'integer', 'default_kind': 'fixed',
                                               'default_value': '4', 'label': 'N'})],
                            column_model_ids=[(0, 0, {'column_name': 'n',
                                                      'model_id': self.env.ref('base.model_res_partner').id})])
        q.action_validate()
        q.group_ids = [(4, self.env.ref(group_xmlid).id)]
        wiz = self.env['sql.query.library'].with_user(self.manager).create({'mode': 'export', 'query_ids': [(6, 0, q.ids)]})
        wiz.action_export()
        data = json.loads(wiz.file.content)
        self.assertEqual(data['format'], 'sql_query_workbench.library')
        entry = data['queries'][0]
        self.assertEqual(entry['groups'], [group_xmlid])
        self.assertEqual(entry['parameters'][0]['default_value'], '4')
        entry['name'] = 'Imported query'
        imp = self.env['sql.query.library'].with_user(self.sql_user).create({
            'mode': 'import', 'file': base64.b64encode(json.dumps(data).encode()).decode()})
        action = imp.action_import()
        new = self.env['sql.query'].browse(action['domain'][0][2])
        self.assertEqual(new.name, 'Imported query')
        self.assertEqual(new.user_id, self.sql_user)
        self.assertEqual(new.param_ids.default_value, '4')
        self.assertEqual(new.column_model_ids.model_id.model, 'res.partner')
        self.assertEqual(new.tag_ids.name, 'LibTag')
        self.assertEqual(new.state, 'valid')
        self.assertEqual(new.group_ids, self.env.ref(group_xmlid))
        bad = self.env['sql.query.library'].with_user(self.sql_user).create({
            'mode': 'import', 'file': base64.b64encode(b'{"queries": []}').decode()})
        with self.assertRaises(UserError):
            bad.action_import()

    def test_examples_are_valid(self):
        examples = self.env['sql.query'].search([('example', '=', True)])
        self.assertGreaterEqual(len(examples), 10)
        for q in examples:
            q._validate_sql()
            self.assertEqual(q.state, 'valid', q.name)

    def test_demo_queries_are_valid(self):
        demo = self.env.ref('sql_query_workbench.demo_query_contacts_period', raise_if_not_found=False)
        if not demo:
            return  # installed without demo data
        demo._validate_sql()
        res = demo.run_query({'countries': [], 'address_type': ''})
        self.assertTrue(res['ok'], res)
        res = demo.run_query({'countries': [self.env.ref('base.us').id], 'companies_only': True,
                              'address_type': 'contact'})
        self.assertTrue(res['ok'], res)

    def test_console_save(self):
        res = self.ws.with_user(self.sql_user).console_save("SELECT :limit_rows AS x", 'Saved from console')
        q = self.env['sql.query'].browse(res['id'])
        self.assertEqual(q.user_id, self.sql_user)
        self.assertEqual(q.param_ids.name, 'limit_rows')
        self.assertEqual(q.param_ids.ptype, 'integer')
        self.ws.with_user(self.sql_user).console_save("SELECT 2", None, q.id)
        self.assertEqual(q.sql, "SELECT 2")
        with self.assertRaises(UserError):
            self.ws.with_user(self.sql_user).console_save("DROP TABLE res_users", 'x')
