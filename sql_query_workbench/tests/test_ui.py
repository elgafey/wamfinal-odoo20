from odoo.tests import HttpCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestWorkbenchUi(HttpCase):

    def test_console_tour(self):
        self.start_tour("/odoo/action-sql_query_workbench.action_sql_workbench_console", "sqlw_console_tour", login="admin")
        runs = self.env['sql.query.run'].search([('user_id', '=', self.env.ref('base.user_admin').id),
                                                 ('origin', 'in', ('console', 'explain'))])
        self.assertTrue(runs.filtered(lambda r: r.origin == 'explain'))

    def test_run_screen_tour(self):
        group = self.env['res.groups'].create({'name': 'SQLW tour readers'})
        reader = new_test_user(self.env, 'sqlw_tour_reader', groups='base.group_user', name='Tour Reader')
        reader.group_ids = [(4, group.id)]
        q = self.env['sql.query'].create({
            'name': 'Tour report',
            'sql': "SELECT id, login FROM res_users WHERE login LIKE :login_like ORDER BY id",
            'param_ids': [(0, 0, {'name': 'login_like', 'ptype': 'char', 'required': True, 'label': 'Login'})],
        })
        q.action_validate()
        q.group_ids = [(4, group.id)]
        q.action_publish_menu()
        self.start_tour("/odoo", "sqlw_run_screen_tour", login="sqlw_tour_reader")
        run = self.env['sql.query.run'].search([('query_id', '=', q.id), ('user_id', '=', reader.id)])
        self.assertEqual(run.origin, 'menu')
        self.assertEqual(run.status, 'success')
