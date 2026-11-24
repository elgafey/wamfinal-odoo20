from odoo.tests import TransactionCase, new_test_user


class SqlwCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ws = cls.env['sql.workbench']
        cls.Query = cls.env['sql.query']
        cls.company_b = cls.env['res.company'].create({'name': 'Second Company Test'})
        cls.employee = new_test_user(cls.env, 'sqlw_employee', groups='base.group_user', name='Plain Employee')
        cls.sql_user = new_test_user(cls.env, 'sqlw_user', groups='sql_query_workbench.group_sqlw_user',
                                     name='Workbench User')
        cls.sql_user2 = new_test_user(cls.env, 'sqlw_user2', groups='sql_query_workbench.group_sqlw_user',
                                      name='Other Workbench User')
        cls.manager = new_test_user(cls.env, 'sqlw_manager', groups='sql_query_workbench.group_sqlw_manager',
                                    name='Workbench Manager')
        cls.admin = cls.env.ref('base.user_admin')
        cls.share_group = cls.env['res.groups'].create({'name': 'SQLW report readers'})
        cls.reader = new_test_user(cls.env, 'sqlw_reader', groups='base.group_user', name='Report Reader')
        cls.reader.group_ids = [(4, cls.share_group.id)]

    def make_query(self, user=None, **vals):
        vals.setdefault('name', 'Test query')
        vals.setdefault('sql', "SELECT id, login FROM res_users WHERE id = :user_id")
        return self.Query.with_user(user or self.manager).create(vals)

    def set_param(self, key, value):
        self.env['ir.config_parameter'].sudo().set_str('sql_query_workbench.' + key, value)
