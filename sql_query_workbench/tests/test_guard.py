from odoo.tests import BaseCase, tagged

from ..services.sql_guard import SqlGuardError, analyse, mask_match, split_list, to_driver_sql, tokenize


@tagged('post_install', '-at_install')
class TestSqlGuard(BaseCase):

    def ok(self, sql, **kw):
        return analyse(sql, **kw)

    def refused(self, sql, fragment, **kw):
        with self.assertRaises(SqlGuardError) as cm:
            analyse(sql, **kw)
        self.assertIn(fragment, str(cm.exception))

    def test_accepts_read_statements(self):
        self.assertEqual(self.ok("SELECT 1")['kind'], 'select')
        self.assertEqual(self.ok("  with x as (select 1) select * from x;")['kind'], 'select')
        self.assertEqual(self.ok("(SELECT 1) UNION (SELECT 2)")['kind'], 'select')
        self.assertEqual(self.ok("EXPLAIN (ANALYZE, FORMAT JSON) SELECT 1")['kind'], 'explain')
        self.assertEqual(self.ok("explain analyze verbose select 1")['kind'], 'explain')
        self.assertEqual(self.ok("-- comment\n/* block /* nested */ */ select 1 ;; ")['kind'], 'select')

    def test_refuses_non_read_statements(self):
        for sql in ("UPDATE res_partner SET name = 'x'", "delete from res_partner", "INSERT INTO t VALUES (1)",
                    "CREATE TABLE t (a int)", "DROP TABLE res_partner", "VACUUM", "SET statement_timeout = 0",
                    "BEGIN", "COMMIT", "COPY res_partner TO STDOUT", "values (1)", "TABLE res_partner", ""):
            with self.assertRaises(SqlGuardError, msg=sql):
                analyse(sql)

    def test_explain_must_wrap_select(self):
        self.refused("EXPLAIN DELETE FROM res_partner", "EXPLAIN")
        self.refused("EXPLAIN ANALYZE UPDATE res_partner SET name = 'x'", "EXPLAIN")

    def test_single_statement(self):
        self.refused("SELECT 1; SELECT 2", "one statement")
        self.refused("SELECT 1; DROP TABLE res_partner", "one statement")
        # a semicolon inside a literal, quoted name or comment is not a separator
        self.ok("SELECT 'a;b', \"we;ird\" FROM res_partner -- ;\n")

    def test_forbidden_words_outside_literals_only(self):
        self.refused("WITH d AS (DELETE FROM res_partner RETURNING id) SELECT * FROM d", "DELETE")
        self.refused("SELECT * FROM res_partner FOR UPDATE", "UPDATE")
        self.refused("SELECT id INTO tmp_copy FROM res_partner", "INTO")
        self.ok("SELECT 'delete from x; update y' AS text, $$drop$$ AS d, e'it\\'s' AS e")
        self.ok("SELECT create_date, write_uid, \"update\" FROM res_partner")

    def test_forbidden_functions(self):
        for sql in ("SELECT pg_read_file('/etc/passwd')", "SELECT pg_terminate_backend(1)",
                    "SELECT set_config('statement_timeout', '0', false)", "SELECT pg_advisory_lock(1)",
                    "SELECT query_to_xml('select 1', true, true, '')", "SELECT * FROM dblink('x', 'y')",
                    "SELECT lo_import('/tmp/x')", "SELECT ts_stat('select 1')", "SELECT pg_ls_dir('.')"):
            with self.assertRaises(SqlGuardError, msg=sql):
                analyse(sql)

    def test_denylists(self):
        self.refused("SELECT key, value FROM ir_config_parameter", "ir_config_parameter",
                     denied_tables={'ir_config_parameter'})
        self.refused('SELECT * FROM public."IR_CONFIG_PARAMETER"', "denylist", denied_tables={'ir_config_parameter'})
        self.refused("SELECT login, password FROM res_users", "password", denied_columns={'password'})
        # a table name inside a string is data, not a table reference
        self.ok("SELECT relname FROM pg_class WHERE relname = 'ir_config_parameter'",
                denied_tables={'ir_config_parameter'})

    def test_params_and_driver_sql(self):
        sql = "SELECT id::text, '50%' AS pct, ':not_a_param' FROM res_partner WHERE create_date >= :date_from AND id = ANY(:ids) AND x = :date_from;"
        a = analyse(sql)
        self.assertEqual(a['params'], ['date_from', 'ids'])
        driver = to_driver_sql(sql, a)
        self.assertEqual(driver, "SELECT id::text, '50%%' AS pct, ':not_a_param' FROM res_partner "
                                 "WHERE create_date >= %(date_from)s AND id = ANY(%(ids)s) AND x = %(date_from)s")
        self.assertNotIn(';', driver)

    def test_tokenizer_errors(self):
        for sql in ("SELECT 'open", 'SELECT "open', "SELECT /* open", "SELECT $x$ open"):
            with self.assertRaises(SqlGuardError, msg=sql):
                tokenize(sql)

    def test_helpers(self):
        self.assertEqual(split_list("a, B\nc;d"), {'a', 'b', 'c', 'd'})
        patterns = ['password', 'token']
        self.assertTrue(mask_match('password', patterns))
        self.assertTrue(mask_match('google_calendar_token', patterns))
        self.assertFalse(mask_match('payment_token_id', patterns))
        self.assertFalse(mask_match('name', patterns))

    def test_role_and_settings_escapes(self):
        for sql in ("SET ROLE postgres", "SELECT 1; SET ROLE postgres", "RESET ROLE",
                    "SELECT set_config('role', 'postgres', true)",
                    "SELECT set_config('transaction_read_only', 'off', true)",
                    "SET SESSION CHARACTERISTICS AS TRANSACTION READ WRITE",
                    "SELECT ts_rewrite('a'::tsquery, 'SELECT ''a''::tsquery, ''b''::tsquery')",
                    "SELECT pg_reload_conf()", "SELECT pg_cancel_backend(1)", "LISTEN x", "NOTIFY x"):
            with self.assertRaises(SqlGuardError, msg=sql):
                analyse(sql)

    def test_comment_and_quoting_tricks(self):
        for sql in ("SELECT 1 /* harmless */; DELETE FROM res_partner",
                    "SELECT 1 -- comment\n; DROP TABLE res_partner",
                    "/* SELECT */ DELETE FROM res_partner",
                    "-- SELECT\nUPDATE res_partner SET name = 'x'",
                    "SELECT 1 /* unterminated ; DELETE FROM res_partner",
                    "SELECT $q$;$q$; DELETE FROM res_partner",
                    "SELECT 'it''s'; TRUNCATE res_partner",
                    "SELECT 1 /* /* nested */ ; */ ; DROP TABLE x",
                    "WITH x AS (SELECT 1) INSERT INTO t SELECT * FROM x",
                    "EXPLAIN ANALYZE DELETE FROM res_partner",
                    'SELECT * FROM U&"ir_config_p\\0061rameter"',
                    "COPY (SELECT 1) TO PROGRAM 'id'"):
            with self.assertRaises(SqlGuardError, msg=sql):
                analyse(sql, denied_tables={'ir_config_parameter'})
