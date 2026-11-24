import datetime
import io
import zipfile

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import SqlwCase


@tagged('post_install', '-at_install')
class TestEngine(SqlwCase):

    def run_sql(self, sql, values=None, mode='run', user=None):
        return self.ws.with_user(user or self.sql_user).console_run(sql, values or {}, mode)

    def test_run_returns_typed_columns_and_rows(self):
        res = self.run_sql("SELECT id, login, create_date, active, 1.5::numeric AS n FROM res_users "
                           "WHERE login = 'admin'")
        self.assertTrue(res['ok'], res)
        self.assertEqual(res['row_count'], 1)
        self.assertEqual(res['rows'][0][:2], [self.admin.id, 'admin'])
        cols = {c['name']: c for c in res['columns']}
        self.assertEqual(cols['id']['type'], 'integer')
        self.assertTrue(cols['id']['numeric'])
        self.assertEqual(cols['active']['type'], 'boolean')
        self.assertTrue(cols['n']['numeric'])
        self.assertIsInstance(res['rows'][0][4], float)
        self.assertGreaterEqual(res['duration_ms'], 0)
        self.assertTrue(res['run_id'])

    def test_separate_read_only_connection(self):
        """The statement runs outside the request transaction: test data is invisible
        and nothing the statement does can write (nextval needs write access)."""
        partner = self.env['res.partner'].create({'name': 'Invisible Uncommitted Partner'})
        res = self.run_sql("SELECT count(*) FROM res_partner WHERE id = :pid", {'pid': partner.id})
        self.assertEqual(res['rows'][0][0], 0)
        res = self.run_sql("SELECT nextval('res_partner_id_seq')")
        self.assertFalse(res['ok'])
        self.assertEqual(res['status'], 'blocked')  # the guard stops it; the engine test covers layer 2

    def test_engine_refuses_writes_even_without_the_guard(self):
        """Second layer: statements that slip past the guard still cannot write,
        because the connection runs a READ ONLY transaction that is rolled back."""
        from ..services import engine
        db = self.env.cr.dbname
        for sql in ("UPDATE res_partner SET name = 'hacked' WHERE id = 1",
                    "INSERT INTO res_partner_category (name) VALUES ('{}')",
                    "DELETE FROM res_partner_category",
                    "CREATE TABLE sqlw_should_not_exist (a int)",
                    "DROP TABLE res_partner_category",
                    "TRUNCATE res_partner_category",
                    "SELECT nextval('res_partner_id_seq')",
                    "SELECT setval('res_partner_id_seq', 1)",
                    "SELECT set_config('transaction_read_only', 'off', true)",
                    "SELECT * FROM res_partner FOR UPDATE"):
            with self.assertRaises(engine.QueryFailed, msg=sql):
                engine.run(db, sql, {}, 5000, 10)
        self.env.cr.execute("SELECT to_regclass('sqlw_should_not_exist')")
        self.assertIsNone(self.env.cr.fetchone()[0])

    def test_side_effect_functions_refused_in_console(self):
        for sql in ("SELECT nextval('res_partner_id_seq')", "SELECT setval('res_partner_id_seq', 1)",
                    "SELECT pg_terminate_backend(pg_backend_pid())", "SET ROLE postgres",
                    "SELECT 1; UPDATE res_partner SET name = 'x'", "SELECT lo_import('/etc/passwd')",
                    "SELECT pg_read_file('/etc/passwd')", "SELECT * FROM pg_stats"):
            self.assertEqual(self.run_sql(sql)['status'], 'blocked', sql)

    def test_row_cap(self):
        self.set_param('row_limit', 3)
        res = self.run_sql("SELECT g FROM generate_series(1, 10) g")
        self.assertEqual(res['row_count'], 3)
        self.assertTrue(res['truncated'])
        run = self.env['sql.query.run'].browse(res['run_id'])
        self.assertTrue(run.truncated)

    def test_statement_timeout(self):
        self.set_param('timeout', 1)
        res = self.run_sql("SELECT pg_sleep(3)")
        self.assertFalse(res['ok'])
        self.assertEqual(res['status'], 'timeout')
        self.assertEqual(self.env['sql.query.run'].browse(res['run_id']).status, 'timeout')

    def test_error_inline_with_line(self):
        res = self.run_sql("SELECT id\n  FROM res_partner\n WHERE nope = 1")
        self.assertFalse(res['ok'])
        self.assertEqual(res['status'], 'error')
        self.assertIn('nope', res['message'])
        self.assertEqual(res['line'], 3)
        run = self.env['sql.query.run'].browse(res['run_id'])
        self.assertEqual(run.status, 'error')
        self.assertIn('nope', run.error)

    def test_blocked_statement_is_logged(self):
        res = self.run_sql("DELETE FROM res_partner")
        self.assertFalse(res['ok'])
        self.assertEqual(res['status'], 'blocked')
        self.assertEqual(self.env['sql.query.run'].browse(res['run_id']).status, 'blocked')

    def test_denied_table_and_column(self):
        res = self.run_sql("SELECT key FROM ir_config_parameter")
        self.assertEqual(res['status'], 'blocked')
        res = self.run_sql("SELECT login, password FROM res_users")
        self.assertEqual(res['status'], 'blocked')
        self.set_param('denied_tables', 'res_country')
        self.assertEqual(self.run_sql("SELECT id FROM res_country")['status'], 'blocked')

    def test_masking(self):
        res = self.run_sql("SELECT * FROM res_users WHERE login = 'admin'")
        cols = [c['name'] for c in res['columns']]
        i = cols.index('password')
        self.assertTrue(res['columns'][i]['masked'])
        self.assertIn(res['rows'][0][i], ('********', None))
        self.set_param('mask_enabled', '0')
        res = self.run_sql("SELECT 'x'::text AS api_key")
        self.assertEqual(res['rows'][0][0], 'x')
        self.set_param('mask_enabled', '1')
        res = self.run_sql("SELECT 'x'::text AS api_key, 7 AS payment_token_id")
        self.assertEqual(res['rows'][0], ['********', 7])

    def test_record_links(self):
        res = self.run_sql("SELECT u.id, u.partner_id, u.company_id, u.login, 5 AS computed "
                           "FROM res_users u WHERE u.id = :user_id")
        models = {c['name']: c['model'] for c in res['columns']}
        self.assertEqual(models, {'id': 'res.users', 'partner_id': 'res.partner', 'company_id': 'res.company',
                                  'login': False, 'computed': False})

    def test_console_params_and_builtins(self):
        names = self.ws.with_user(self.sql_user).console_params(
            "SELECT 1 WHERE :user_id > 0 AND :company_id = ANY(:company_ids) AND :x IS NOT NULL")
        self.assertEqual(names, ['x'])
        res = self.run_sql("SELECT :user_id AS u, :company_id AS c, :today::date AS d, :x AS x", {'x': 'hi'})
        self.assertTrue(res['ok'], res)
        self.assertEqual(res['rows'][0][0], self.sql_user.id)
        self.assertEqual(res['rows'][0][1], self.sql_user.company_id.id)
        self.assertEqual(res['rows'][0][3], 'hi')
        res = self.run_sql("SELECT :x AS x")
        self.assertEqual(res['status'], 'blocked')
        self.assertIn('x', res['message'])

    def test_console_uses_declared_types_of_loaded_query(self):
        q = self.make_query(user=self.sql_user, sql="SELECT :n + 1 AS n, :d AS d", param_ids=[
            (0, 0, {'name': 'n', 'ptype': 'integer'}),
            (0, 0, {'name': 'd', 'ptype': 'datetime'})])
        res = self.ws.with_user(self.sql_user).console_run(
            "SELECT :n + 1 AS n, :d::timestamp AS d, :free AS free",
            {'n': '41', 'd': '2026-03-01 10:00', 'free': 'x'}, 'run', q.id)
        self.assertTrue(res['ok'], res)
        self.assertEqual(res['rows'][0][0], 42)
        self.assertEqual(res['rows'][0][2], 'x')
        with self.assertRaises(AccessError):
            other = self.make_query(user=self.sql_user2)
            self.ws.with_user(self.sql_user).console_run("SELECT 1", {}, 'run', other.id)

    def test_values_are_bound_not_formatted(self):
        evil = "'); DROP TABLE res_partner; --"
        res = self.run_sql("SELECT :v::text AS v", {'v': evil})
        self.assertTrue(res['ok'])
        self.assertEqual(res['rows'][0][0], evil)

    def test_explain_and_analyze(self):
        self.set_param('seq_scan_rows', 0)
        res = self.run_sql("SELECT p.id FROM res_partner p JOIN res_users u ON u.partner_id = p.id", mode='explain')
        self.assertTrue(res['ok'], res)
        self.assertEqual(res['kind'], 'plan')
        nodes = res['plan']['nodes']
        self.assertEqual(nodes[0]['depth'], 0)
        self.assertEqual(nodes[0]['cost_share'], 100.0)
        self.assertTrue(any(n['depth'] > 0 for n in nodes))
        self.assertIsNone(nodes[0]['actual_rows'])
        res = self.run_sql("SELECT count(*) FROM res_users", mode='explain_analyze')
        self.assertTrue(res['ok'])
        self.assertIsNotNone(res['plan']['execution_ms'])
        self.assertIsNotNone(res['plan']['nodes'][0]['actual_rows'])
        seq = [n for n in res['plan']['nodes'] if n['node_type'] == 'Seq Scan']
        if seq:
            self.assertTrue(seq[0]['seq_scan_warning'])
        # EXPLAIN ANALYZE still runs read-only
        res = self.run_sql("SELECT nextval('res_partner_id_seq')", mode='explain_analyze')
        self.assertFalse(res['ok'])
        self.assertEqual(self.run_sql("EXPLAIN SELECT 1", mode='explain')['status'], 'blocked')

    def test_group_limits_override(self):
        self.set_param('row_limit', 2)
        self.assertEqual(self.ws.with_user(self.sql_user)._limits()['row_limit'], 2)
        self.env['sql.query.limit'].create({'group_id': self.share_group.id, 'row_limit': 7, 'timeout': 5})
        self.sql_user.group_ids = [(4, self.share_group.id)]
        limits = self.ws.with_user(self.sql_user)._limits()
        self.assertEqual(limits['row_limit'], 7)
        self.assertEqual(limits['timeout'], 5)
        self.assertEqual(self.ws.with_user(self.sql_user2)._limits()['row_limit'], 2)

    def test_schema_browser(self):
        tables = {t['name']: t for t in self.ws.with_user(self.sql_user).schema_tables()}
        self.assertEqual(tables['res_partner']['model'], 'res.partner')
        self.assertTrue(tables['ir_config_parameter']['denied'])
        detail = self.ws.with_user(self.sql_user).schema_table('res_users')
        cols = {c['name']: c for c in detail['columns']}
        self.assertEqual(cols['partner_id']['field_type'], 'many2one')
        self.assertEqual(cols['partner_id']['relation'], 'res.partner')
        self.assertTrue(cols['password']['denied'])
        self.assertIn('res_partner', [fk['ref_table'] for fk in detail['foreign_keys']])
        self.assertTrue(detail['indexes'])
        with self.assertRaises(UserError):
            self.ws.with_user(self.sql_user).schema_table('no_such_table_xyz')

    def test_csv_export_options(self):
        content, name, mime = self.ws.with_user(self.sql_user).export_file({
            'sql': "SELECT 1 AS a, 'x;y' AS b", 'format': 'csv',
            'options': {'separator': 'semicolon', 'bom': True, 'header': True, 'filename': 'my file',
                        'line_ending': 'lf'}})
        self.assertEqual(name, 'my file.csv')
        self.assertTrue(content.startswith(b'\xef\xbb\xbf'))
        self.assertEqual(content[3:].decode(), 'a;b\n1;"x;y"\n')
        content, _n, _m = self.ws.with_user(self.sql_user).export_file({
            'sql': "SELECT 1 AS a", 'format': 'csv', 'options': {'header': False, 'quote': 'single'}})
        self.assertEqual(content, b'1\r\n')

    def test_xlsx_export_is_typed(self):
        content, name, mime = self.ws.with_user(self.sql_user).export_file({
            'sql': "SELECT 1 AS n, 2.5::numeric AS f, DATE '2026-01-31' AS d, true AS b, 'txt' AS t",
            'format': 'xlsx'})
        self.assertTrue(name.endswith('.xlsx'))
        self.assertIn('spreadsheetml', mime)
        sheet = zipfile.ZipFile(io.BytesIO(content)).read('xl/worksheets/sheet1.xml').decode()
        self.assertIn('autoFilter', sheet)
        self.assertIn('<pane', sheet)  # frozen header
        self.assertIn('t="b"', sheet)  # real boolean cell
        try:
            import openpyxl  # noqa: PLC0415
        except ImportError:
            return
        ws = openpyxl.load_workbook(io.BytesIO(content)).active
        header_row = next(r for r in range(1, 10) if ws.cell(r, 1).value == 'n')
        self.assertEqual(ws.cell(header_row + 1, 1).value, 1)
        self.assertEqual(ws.cell(header_row + 1, 2).value, 2.5)
        self.assertEqual(ws.cell(header_row + 1, 3).value, datetime.datetime(2026, 1, 31))
        self.assertIs(ws.cell(header_row + 1, 4).value, True)
        self.assertEqual(ws.cell(2, 1).value.split(' - ')[0], self.env.company.name)

    def test_export_respects_export_limit_and_masking(self):
        self.set_param('export_limit', 4)
        content, _n, _m = self.ws.with_user(self.sql_user).export_file({
            'sql': "SELECT g, 'secret' AS api_key FROM generate_series(1, 10) g", 'format': 'csv'})
        lines = content.decode().strip().split('\r\n')
        self.assertEqual(len(lines), 5)
        self.assertEqual(lines[1], '1,********')
        with self.assertRaises(UserError):
            self.ws.with_user(self.sql_user).export_file({'sql': "DELETE FROM res_partner", 'format': 'csv'})

    def test_pdf_print(self):
        action = self.ws.with_user(self.sql_user).print_pdf({'sql': "SELECT id, login FROM res_users LIMIT 2"},
                                                           'landscape', 'My report')
        self.assertEqual(action['type'], 'ir.actions.report')
        self.assertEqual(action['report_name'], 'sql_query_workbench.report_sql_result_landscape')
        report = self.env['ir.actions.report']._get_report(action['report_name'])
        self.assertEqual(report.paperformat_id.orientation, 'Landscape')
        portrait = self.ws.with_user(self.sql_user).print_pdf({'sql': "SELECT 1"}, 'portrait')
        self.assertEqual(self.env['ir.actions.report']._get_report(portrait['report_name'])
                         .paperformat_id.orientation, 'Portrait')
        rec = self.env['sql.query.print'].browse(action['context']['active_ids'])
        self.assertEqual(rec.orientation, 'landscape')
        self.assertEqual(rec.name, 'My report')
        html = self.env['ir.actions.report']._render_qweb_html(
            'sql_query_workbench.action_report_result_landscape', rec.ids)[0].decode()
        self.assertIn('My report', html)
        self.assertIn('login', html)
        self.assertEqual(self.env.ref('sql_query_workbench.action_report_result_landscape')
                         .paperformat_id.orientation, 'Landscape')

    def test_history_recall(self):
        self.run_sql("SELECT 42 AS answer")
        boot = self.ws.with_user(self.sql_user).console_bootstrap()
        self.assertEqual(boot['recent'][0]['sql'], "SELECT 42 AS answer")
        run = self.env['sql.query.run'].browse(boot['recent'][0]['id'])
        self.assertEqual(run.with_user(self.sql_user).console_sql(), "SELECT 42 AS answer")
        # history is per user
        self.assertNotIn("SELECT 42 AS answer",
                         [r['sql'] for r in self.ws.with_user(self.sql_user2).console_bootstrap()['recent']])
