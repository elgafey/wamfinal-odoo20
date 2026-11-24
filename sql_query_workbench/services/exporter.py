# Part of SQL Query Workbench. Copyright Viyug Infotech. License LGPL-3.
"""CSV and XLSX files from query results (plain python, no Odoo imports)."""
import csv
import datetime
import decimal
import io

import xlsxwriter

from .engine import jsonable

SEPARATORS = {'comma': ',', 'semicolon': ';', 'tab': '\t', 'pipe': '|'}
QUOTES = {'double': '"', 'single': "'"}
LINE_ENDINGS = {'crlf': '\r\n', 'lf': '\n'}


def _cell_text(value):
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, float):
        return repr(value)
    v = jsonable(value)
    return v if isinstance(v, str) else str(v)


def to_csv(columns, rows, separator='comma', quote='double', header=True, bom=False, line_ending='crlf'):
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=SEPARATORS.get(separator, ','), quotechar=QUOTES.get(quote, '"'),
                        lineterminator=LINE_ENDINGS.get(line_ending, '\r\n'), quoting=csv.QUOTE_MINIMAL)
    if header:
        writer.writerow(columns)
    for row in rows:
        writer.writerow([_cell_text(v) for v in row])
    data = buf.getvalue().encode('utf-8')
    return (b'\xef\xbb\xbf' + data) if bom else data


def to_xlsx(columns, rows, title, company, run_date, param_lines=(), header=True):
    """Typed workbook: numbers, dates and booleans as real cells, styled and frozen
    header row with an autofilter, title block with company and run date."""
    out = io.BytesIO()
    wb = xlsxwriter.Workbook(out, {'in_memory': True, 'remove_timezone': True})
    ws = wb.add_worksheet((title or 'Result')[:31].translate(str.maketrans('[]:*?/\\', '       ')))
    f_title = wb.add_format({'bold': True, 'font_size': 14, 'font_color': '#1B2A41'})
    f_meta = wb.add_format({'font_color': '#5B6475'})
    f_head = wb.add_format({'bold': True, 'font_color': '#FFFFFF', 'bg_color': '#1B2A41',
                            'border': 1, 'border_color': '#1B2A41', 'text_wrap': True, 'valign': 'top'})
    f_date = wb.add_format({'num_format': 'yyyy-mm-dd'})
    f_dt = wb.add_format({'num_format': 'yyyy-mm-dd hh:mm:ss'})
    f_num = wb.add_format({'num_format': '#,##0.00'})
    r = 0
    ws.write(r, 0, title or 'Query result', f_title)
    r += 1
    ws.write(r, 0, f"{company} - {run_date}", f_meta)
    r += 1
    for line in param_lines:
        ws.write(r, 0, line, f_meta)
        r += 1
    r += 1
    widths = [max(len(str(c)), 6) for c in columns]
    head_row = r
    if header:
        for c, name in enumerate(columns):
            ws.write_string(r, c, str(name), f_head)
        r += 1
    for row in rows:
        for c, v in enumerate(row):
            if v is None:
                continue
            if isinstance(v, bool):
                ws.write_boolean(r, c, v)
            elif isinstance(v, int):
                ws.write_number(r, c, v)
            elif isinstance(v, (float, decimal.Decimal)):
                fv = float(v)
                if fv == fv and fv not in (float('inf'), float('-inf')):
                    ws.write_number(r, c, fv, f_num)
                else:
                    ws.write_string(r, c, str(v))
            elif isinstance(v, datetime.datetime):
                ws.write_datetime(r, c, v.replace(tzinfo=None), f_dt)
                widths[c] = max(widths[c], 19)
                continue
            elif isinstance(v, datetime.date):
                ws.write_datetime(r, c, datetime.datetime.combine(v, datetime.time()), f_date)
                widths[c] = max(widths[c], 10)
                continue
            else:
                text = _cell_text(v)
                ws.write_string(r, c, text[:32767])
                widths[c] = max(widths[c], min(len(text), 60))
                continue
            widths[c] = max(widths[c], min(len(str(v)), 20))
        r += 1
    for c, w in enumerate(widths):
        ws.set_column(c, c, w + 2)
    if header and columns:
        ws.freeze_panes(head_row + 1, 0)
        ws.autofilter(head_row, 0, max(r - 1, head_row), len(columns) - 1)
    wb.close()
    return out.getvalue()
