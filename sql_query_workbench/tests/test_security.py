from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import SqlwCase


@tagged('post_install', '-at_install')
class TestSecurity(SqlwCase):

    def test_admin_is_workbench_administrator_by_default(self):
        self.assertTrue(self.admin.has_group('sql_query_workbench.group_sqlw_manager'))
        self.assertFalse(self.employee.has_group('sql_query_workbench.group_sqlw_user'))

    def test_employee_has_no_console_access(self):
        ws = self.ws.with_user(self.employee)
        for call in (lambda: ws.console_run("SELECT 1"),
                     lambda: ws.console_bootstrap(),
                     lambda: ws.console_params("SELECT :x"),
                     lambda: ws.schema_tables(),
                     lambda: ws.schema_table('res_partner'),
                     lambda: ws.export_file({'sql': "SELECT 1", 'format': 'csv'}),
                     lambda: ws.print_pdf({'sql': "SELECT 1"}),
                     lambda: ws.console_save("SELECT 1", 'x')):
            with self.assertRaises(AccessError):
                call()

    def test_employee_has_no_menu(self):
        visible = self.env['ir.ui.menu'].with_user(self.employee)._visible_menu_ids(debug=True)
        for xmlid in ('menu_sqlw_root', 'menu_sqlw_console', 'menu_sqlw_technical', 'menu_sqlw_runs'):
            self.assertNotIn(self.env.ref('sql_query_workbench.' + xmlid).id, visible, xmlid)
        visible_user = self.env['ir.ui.menu'].with_user(self.sql_user)._visible_menu_ids()
        self.assertIn(self.env.ref('sql_query_workbench.menu_sqlw_console').id, visible_user)
        self.assertNotIn(self.env.ref('sql_query_workbench.menu_sqlw_runs').id, visible_user)

    def test_employee_cannot_read_unshared_queries_or_logs(self):
        q = self.make_query()
        q.action_validate()
        with self.assertRaises(AccessError):
            q.with_user(self.employee).read(['name'])
        with self.assertRaises(AccessError):
            q.with_user(self.employee).get_run_screen()
        with self.assertRaises(AccessError):
            q.with_user(self.employee).run_query({})
        with self.assertRaises(AccessError):
            self.env['sql.query.run'].with_user(self.employee).search([])
        with self.assertRaises(AccessError):
            self.Query.with_user(self.employee).create({'name': 'x', 'sql': 'SELECT 1'})

    def test_shared_group_member_runs_but_cannot_edit(self):
        q = self.make_query(sql="SELECT id, login FROM res_users WHERE login = 'admin'")
        q.action_validate()
        q.group_ids = [(4, self.share_group.id)]
        as_reader = q.with_user(self.reader)
        screen = as_reader.get_run_screen()
        self.assertFalse(screen['can_edit'])
        self.assertFalse(screen['sql'])  # run-only members do not see the SQL
        res = as_reader.run_query({})
        self.assertTrue(res['ok'], res)
        self.assertEqual(res['rows'][0][1], 'admin')
        self.assertEqual(self.env['sql.query.run'].browse(res['run_id']).user_id, self.reader)
        with self.assertRaises(AccessError):
            as_reader.write({'name': 'hijack'})
        with self.assertRaises(AccessError):
            as_reader.unlink()
        with self.assertRaises(AccessError):
            as_reader.run_query({}, mode='explain')  # plans are for workbench users
        with self.assertRaises(AccessError):
            as_reader.action_duplicate_draft()
        # exporting a shared query works, the SQL cannot be swapped
        content, _n, _m = self.ws.with_user(self.reader).export_file(
            {'query_id': q.id, 'sql': 'SELECT 1 AS injected', 'format': 'csv'})
        self.assertIn(b'admin', content)
        self.assertNotIn(b'injected', content)

    def test_shared_with_single_user(self):
        q = self.make_query(sql="SELECT 1 AS one")
        q.action_validate()
        q.user_ids = [(4, self.employee.id)]
        self.assertTrue(q.with_user(self.employee).run_query({})['ok'])
        with self.assertRaises(AccessError):
            q.with_user(self.reader).run_query({})

    def test_draft_query_not_visible_to_share_targets(self):
        q = self.make_query()
        q.action_validate()
        q.group_ids = [(4, self.share_group.id)]
        self.env.flush_all()
        self.env.cr.execute("UPDATE sql_query SET state = 'draft' WHERE id = %s", [q.id])
        q.invalidate_recordset()
        with self.assertRaises(AccessError):
            q.with_user(self.reader).run_query({})

    def test_workbench_user_owns_queries(self):
        mine = self.make_query(user=self.sql_user, name='Mine')
        self.assertEqual(mine.user_id, self.sql_user)
        mine.with_user(self.sql_user).write({'description': 'ok'})
        other = self.make_query(user=self.sql_user2, name='Other')
        with self.assertRaises(AccessError):
            other.with_user(self.sql_user).read(['name'])
        other.action_validate()
        other.group_ids = [(4, self.env.ref('base.group_user').id)]
        with self.assertRaises(AccessError):
            other.with_user(self.sql_user).write({'name': 'x'})
        # duplicate a shared query as a private draft
        action = other.with_user(self.sql_user).action_duplicate_draft()
        copy = self.Query.browse(action['res_id'])
        self.assertEqual(copy.user_id, self.sql_user)
        self.assertEqual(copy.state, 'draft')
        self.assertFalse(copy.group_ids)
        self.assertEqual(copy.sql, other.sql)
        copy.with_user(self.sql_user).write({'name': 'my copy'})
        # managers edit everything
        other.with_user(self.manager).write({'description': 'checked'})

    def test_params_follow_query_owner(self):
        other = self.make_query(user=self.sql_user2, param_ids=[(0, 0, {'name': 'p', 'ptype': 'char'})])
        with self.assertRaises(AccessError):
            other.param_ids.with_user(self.sql_user).write({'label': 'x'})
        with self.assertRaises(AccessError):
            self.env['sql.query.param'].with_user(self.sql_user).create(
                {'query_id': other.id, 'name': 'q', 'ptype': 'char'})

    def test_run_log_visibility(self):
        mine = self.ws.with_user(self.sql_user).console_run("SELECT 1")['run_id']
        theirs = self.ws.with_user(self.sql_user2).console_run("SELECT 2")['run_id']
        visible = self.env['sql.query.run'].with_user(self.sql_user).search([]).ids
        self.assertIn(mine, visible)
        self.assertNotIn(theirs, visible)
        with self.assertRaises(AccessError):
            self.env['sql.query.run'].browse(theirs).with_user(self.sql_user).console_sql()
        self.assertIn(theirs, self.env['sql.query.run'].with_user(self.manager).search([]).ids)
        with self.assertRaises(AccessError):
            self.env['sql.query.run'].browse(mine).with_user(self.sql_user).unlink()

    def test_settings_and_limits_are_admin_only(self):
        with self.assertRaises(AccessError):
            self.env['sql.query.limit'].with_user(self.sql_user).create({'group_id': self.share_group.id})
        with self.assertRaises(AccessError):
            self.env['res.config.settings'].with_user(self.sql_user).create({})

    def test_multi_company(self):
        self.manager.write({'company_ids': [(4, self.company_b.id)]})
        q_b = self.Query.create({'name': 'Company B query', 'sql': 'SELECT 1 AS one', 'user_id': self.manager.id,
                                 'company_id': self.company_b.id})
        q_b.action_validate()
        q_b.group_ids = [(4, self.share_group.id)]
        # reader only belongs to the main company
        with self.assertRaises(AccessError):
            q_b.with_user(self.reader).get_run_screen()
        self.reader.write({'company_ids': [(4, self.company_b.id)]})
        q_b.invalidate_recordset()
        screen = q_b.with_user(self.reader).with_context(allowed_company_ids=[self.company_b.id]).get_run_screen()
        self.assertEqual(screen['name'], 'Company B query')
        run = self.ws.with_user(self.sql_user).with_company(self.env.company).console_run("SELECT 1")
        log = self.env['sql.query.run'].browse(run['run_id'])
        self.assertEqual(log.company_id, self.env.company)
        self.assertNotIn(log.id, self.env['sql.query.run'].with_user(self.manager).with_context(
            allowed_company_ids=[self.company_b.id]).search([]).ids)
