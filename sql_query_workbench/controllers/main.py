# Part of SQL Query Workbench. Copyright Viyug Infotech. License LGPL-3.
import json

from werkzeug.exceptions import InternalServerError

from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import request
from odoo.http.stream import content_disposition
from odoo.http.dispatcher import serialize_exception
from odoo.tools import html_escape


class SqlWorkbenchController(http.Controller):

    @http.route('/sql_query_workbench/export', type='http', auth='user', methods=['POST'])
    def export(self, data, **kw):
        try:
            payload = json.loads(data)
            content, filename, mimetype = request.env['sql.workbench'].export_file(payload)
        except (UserError, AccessError, ValueError) as e:
            error = {'code': 0, 'message': "Odoo Server Error", 'data': serialize_exception(e)}
            raise InternalServerError(response=request.make_response(html_escape(json.dumps(error)))) from e
        return request.make_response(content, headers=[
            ('Content-Type', mimetype),
            ('Content-Disposition', content_disposition(filename)),
        ])
