import json

from odoo.tests import tagged

from ..services import engine
from ..services.sql_guard import SqlGuardError, analyse, check_protected
from .common import SqlwCase

# whole-row and expression forms that used to return res_users.password
BYPASSES = [
    "SELECT u FROM res_users u",
    "SELECT row_to_json(u) FROM res_users u",
    "SELECT to_json(u) FROM res_users u",
    "SELECT to_jsonb(u) FROM res_users u",
    "SELECT json_agg(u) FROM res_users u",
    "SELECT jsonb_agg(u) FROM res_users u",
    "SELECT array_to_json(array_agg(u)) FROM res_users u",
    "SELECT row(u.*) FROM res_users u",
    "SELECT u::text FROM res_users u",
    "SELECT format('%s', u) FROM res_users u",
    "SELECT string_agg(u::text, ',') FROM res_users u",
    "SELECT row_to_json(u) FROM \"res_users\" u",
    "SELECT x.* FROM res_partner p, LATERAL (SELECT * FROM res_users u WHERE u.partner_id = p.id) x",
    "SELECT x FROM (SELECT * FROM res_users) x",
    "WITH t AS (SELECT * FROM res_users) SELECT t FROM t",
    "WITH t AS (SELECT u FROM res_users u) SELECT row_to_json(t) FROM t",
    "SELECT login FROM res_users UNION ALL SELECT password FROM res_users",
    "SELECT password, totp_secret FROM res_users",
    "SELECT length(password), md5(password), substr(password, 1, 20) FROM res_users",
    "SELECT password::int FROM res_users",
    "SELECT (SELECT array_agg(r) FROM res_users r) AS all_users",
    "SELECT jsonb_each_text(to_jsonb(u)) FROM res_users u",
    "SELECT definition FROM pg_views WHERE viewname = 'res_users'",
    "SELECT column_name, column_default FROM information_schema.columns WHERE table_name = 'res_users'",
    "SELECT hstore(u) FROM res_users u",
]


@tagged('post_install', '-at_install')
class TestProtectedColumns(SqlwCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.cr.execute("SELECT password FROM res_users WHERE password IS NOT NULL")
        cls.hashes = [r[0] for r in cls.env.cr.fetchall()]

    def setUp(self):
        super().setUp()
        # switch off the name-based layers: protection must hold by itself
        self.set_param('denied_columns', ' ')
        self.set_param('mask_enabled', '0')

    def run_sql(self, sql):
        return self.ws.with_user(self.manager).console_run(sql, {})

    def assertNoSecret(self, res, sql):
        blob = json.dumps(res, default=str)
        for h in self.hashes:
            self.assertNotIn(h, blob, sql)
            self.assertNotIn(h[:24], blob, sql)
        self.assertNotIn('$pbkdf2', blob, sql)

    def test_demo_has_password_hashes(self):
        self.assertTrue(self.hashes, "fresh database should store the admin password hash")

    def test_whole_row_and_expression_reads_hide_passwords(self):
        for sql in BYPASSES:
            res = self.run_sql(sql)
            self.assertNoSecret(res, sql)
            if 'hstore' not in sql:
                self.assertTrue(res['ok'] or 'password::int' in sql, (sql, res))

    def test_password_reads_as_mask(self):
        res = self.run_sql("SELECT login, password, totp_secret, length(password) FROM res_users WHERE login = 'admin'")
        self.assertTrue(res['ok'], res)
        self.assertEqual(res['rows'], [['admin', '********', '********', 8]])
        res = self.run_sql("SELECT row_to_json(u) ->> 'password' FROM res_users u WHERE login = 'admin'")
        self.assertEqual(res['rows'], [['********']])

    def test_boolean_and_comparison_oracles_learn_nothing(self):
        real = self.hashes[0]
        for sql in ("SELECT login FROM res_users WHERE password LIKE '$pbkdf2%'",
                    "SELECT login FROM res_users WHERE substr(password, 1, 1) = '$'",
                    "SELECT login FROM res_users WHERE password = '%s'" % real,
                    "SELECT login FROM res_users WHERE md5(password) = md5('%s')" % real,
                    "SELECT login FROM res_users WHERE length(password) = %d" % len(real),
                    "SELECT CASE WHEN password LIKE '$%' THEN 'hit' END FROM res_users WHERE login = 'admin'"):
            res = self.run_sql(sql)
            self.assertTrue(res['ok'], (sql, res))
            self.assertFalse([r for r in res['rows'] if r[0] is not None], sql)

    def test_ways_around_the_shadow_view_are_refused(self):
        for sql in ("SELECT * FROM public.res_users",
                    'SELECT row_to_json(u) FROM "public"."res_users" u',
                    "SELECT u FROM public . res_users u",
                    "SELECT u FROM public/**/.res_users u",
                    "SELECT * FROM pg_temp.res_users",
                    "SELECT * FROM pg_temp_3.res_users",
                    "SELECT * FROM \"pg_temp\".res_users",
                    "SELECT * FROM pg_toast.pg_toast_1255",
                    "SET search_path = public",
                    "SELECT set_config('search_path', 'public', true)",
                    "SELECT * FROM pg_catalog.pg_authid",
                    "SELECT nextval('res_partner_id_seq')",
                    "SELECT setval('res_partner_id_seq', 1)",
                    "SELECT currval('res_partner_id_seq')"):
            res = self.run_sql(sql)
            self.assertFalse(res['ok'], sql)
            self.assertEqual(res['status'], 'blocked', (sql, res))

    def test_postgres_role_passwords_are_hidden(self):
        for sql in ("SELECT rolname, rolpassword FROM pg_authid", "SELECT usename, passwd FROM pg_shadow",
                    "SELECT a FROM pg_authid a"):
            res = self.run_sql(sql)
            self.assertNotIn('SCRAM-SHA-256$', json.dumps(res), sql)
            self.assertNotIn('"md5', json.dumps(res), sql)
            if res['ok'] and 'a FROM' not in sql:  # superuser connections only
                self.assertFalse([r for r in res['rows'] if r[1] not in (None, '********')], sql)

    def test_blocked_columns_setting_adds_protected_columns(self):
        res = self.run_sql("SELECT login FROM res_users WHERE login = 'admin'")
        self.assertEqual(res['rows'], [['admin']])
        self.set_param('denied_columns', 'res_users.login')
        res = self.run_sql("SELECT row_to_json(u) ->> 'login' FROM res_users u WHERE id = %d" % self.admin.id)
        self.assertEqual(res['rows'], [['********']])
        self.set_param('denied_columns', 'share')  # bare name: that column in every table
        self.assertEqual(self.run_sql("SELECT share FROM res_users")['status'], 'blocked')
        res = self.run_sql("SELECT to_jsonb(u) -> 'share' FROM res_users u WHERE id = %d" % self.admin.id)
        self.assertEqual(res['rows'], [[None]])

    def test_masked_words_protect_text_columns_by_construction(self):
        self.set_param('mask_enabled', '1')
        self.set_param('mask_patterns', 'lang')
        res = self.run_sql("SELECT to_jsonb(p) ->> 'lang' FROM res_partner p WHERE id = %d"
                           % self.admin.partner_id.id)
        self.assertEqual(res['rows'], [['********']])

    def test_normal_queries_still_work(self):
        res = self.run_sql("SELECT u.id, u.login, u.active, p.name FROM res_users u "
                           "JOIN res_partner p ON p.id = u.partner_id WHERE u.login = 'admin'")
        self.assertTrue(res['ok'], res)
        self.assertEqual(res['rows'], [[self.admin.id, 'admin', True, self.admin.partner_id.name]])
        self.assertEqual(res['columns'][0]['model'], 'res.users')  # id still links through the view
        res = self.run_sql("SELECT count(*) FROM res_users WHERE active")
        self.assertGreater(res['rows'][0][0], 0)
        res = self.run_sql("SELECT code, name->>'en_US' FROM res_country WHERE code = 'BE'")
        self.assertEqual(res['rows'], [['BE', 'Belgium']])
        res = self.ws.with_user(self.manager).console_run("SELECT * FROM res_users", {}, 'explain')
        self.assertTrue(res['ok'], res)
        q = self.make_query(sql="SELECT u FROM res_users u WHERE id = :user_id")
        q.action_validate()
        self.assertEqual(q.state, 'valid')

    def test_shadow_views_do_not_outlive_the_run(self):
        for sql in ("SELECT u FROM res_users u", "SELECT password::int FROM res_users"):
            self.run_sql(sql)
        self.env.cr.execute("""
            SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname LIKE 'pg\\_temp\\_%%' AND c.relname = 'res_users'""")
        self.assertEqual(self.env.cr.fetchone()[0], 0)
        self.env.cr.execute("SELECT to_regclass('res_users') = 'public.res_users'::regclass")
        self.assertTrue(self.env.cr.fetchone()[0])

    def test_engine_stays_read_only_with_shadow_views(self):
        shadow = self.ws._protection({'res_users'})[0]
        self.assertTrue(shadow)
        db = self.env.cr.dbname
        for sql in ("CREATE TEMP TABLE sqlw_x (a int)", "SET LOCAL transaction_read_only = off",
                    "SELECT set_config('transaction_read_only', 'off', true)",
                    "UPDATE res_partner SET name = 'hacked' WHERE id = 1",
                    "DROP VIEW res_users"):
            with self.assertRaises(engine.QueryFailed, msg=sql):
                engine.run(db, sql, {}, 5000, 10, shadow=shadow)
        res = engine.run(db, "SELECT row_to_json(u) FROM res_users u", {}, 5000, 10, shadow=shadow)
        self.assertNoSecret(res, 'engine')

    def test_guard_check_protected(self):
        a = analyse("SELECT * FROM res_users u JOIN res_partner p ON p.id = u.partner_id")
        check_protected(a, {'res_users'})
        for sql in ("SELECT * FROM public.res_users", 'SELECT * FROM x."res_users"'):
            with self.assertRaises(SqlGuardError, msg=sql):
                check_protected(analyse(sql), {'res_users'})
        with self.assertRaises(SqlGuardError):
            check_protected(analyse("SELECT * FROM user_secrets_view"), set(), {'user_secrets_view'})
