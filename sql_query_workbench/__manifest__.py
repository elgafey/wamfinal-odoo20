{
    'name': 'SQL Query Workbench: Read-only SQL Console, Saved Queries, Export CSV Excel PDF',
    'version': '20.0.1.0.0',
    'category': 'Extra Tools',
    'summary': 'Strictly read-only SQL console for administrators: saved queries with typed parameters, schema browser, EXPLAIN plans, CSV/Excel/PDF export, sharing, query menus and email digests. Keywords: SQL, SQL queries, SQL console, SQL editor, run SQL, execute SQL, database queries, read-only SQL, read only SQL, SQL reports, SQL to Excel, schema browser, EXPLAIN.',
    'description': """
SQL Query Workbench (read-only)
===============================

Run SQL against your Odoo database from the browser, without ever writing to it.

* Read-only by design: one SELECT, WITH or EXPLAIN statement, run on a separate connection
  in a READ ONLY transaction with a statement timeout and a row cap, always rolled back.
  Write keywords, server-side file and backend functions and denylisted tables are refused.
* Console with SQL highlighting, Ctrl+Enter to run, run the selected text only, recent
  queries, saved-query quick pick by tag and a draft kept per user.
* Results grid: row numbers, sticky header, sorting, pagination, filter box, hide and
  reorder columns, NULL highlighting, sum and average of numeric columns, links to the
  Odoo records behind id and many2one columns.
* Schema browser from the PostgreSQL catalog joined to Odoo models: tables, row estimates,
  sizes, columns with SQL type and Odoo field label, indexes and foreign keys.
* EXPLAIN plan view with cost share and sequential scans on large tables flagged;
  EXPLAIN ANALYZE inside the same read-only, timed-out, rolled-back transaction.
* Saved queries with notes, tags and typed parameters (date, date and time, number, text,
  yes/no, selection, record, record list) with dynamic defaults; values are bound by the
  database driver, never pasted into the SQL. Built-in :user_id, :company_id,
  :company_ids, :today and :lang.
* Validation (dry run) before sharing. Share with groups or users: they run, they do not
  edit. Publish a query as a menu entry with a parameter form and export buttons.
* Export CSV (separator, quote, header, BOM, line endings, file name), Excel with typed
  cells, frozen header and autofilter, PDF portrait or landscape. Copy result or SQL.
* Scheduled email digests (daily, weekly, monthly) with the CSV or Excel file.
* Run log with user, duration, rows, status, error and parameters; list, pivot and graph
  analysis; retention job. SQL changes tracked in the chatter.
* Settings: row cap, timeout, export limit, limits per group, blocked tables and columns,
  masking of credential-like columns. Administrators only by default.
* Query library import and export as JSON. Ten example queries included.
""",
    'author': 'Viyug Infotech',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'mail'],
    'data': [
        'security/security.xml',
        'data/sqlw_data.xml',
        'views/res_config_settings_views.xml',
        'views/sql_query_views.xml',
        'data/example_queries.xml',
    ],
    'demo': ['demo/demo.xml'],
    'assets': {
        'web.assets_backend': [
            'sql_query_workbench/static/src/workbench/**/*',
        ],
        'web.ace_lib': [
            'sql_query_workbench/static/lib/ace/mode-sql.js',
        ],
        'web.assets_tests': [
            'sql_query_workbench/static/tests/tours/**/*',
        ],
    },
    'images': ['static/description/cover.gif'],
    'installable': True,
    'application': True,
}
