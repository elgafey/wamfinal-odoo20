# -*- coding: utf-8 -*-
"""دوال مساعدة صغيرة مشتركة بين النموذج والنوافذ."""


def join_names(records):
    """اسم مقروء لكل سجل في قائمة.

    سبب وجودها: ``account.move.name`` يبقى ``False`` ما دامت الفاتورة مسودة,
    وكانت ``', '.join(records.mapped('name'))`` ترمي::

        TypeError: sequence item 0: expected str instance, bool found

    لذلك نمرّ عبر السلسلة: ``name`` ← ``display_name`` ← الرقم الوصفي.
    """
    return ', '.join(
        str(record.name or record.display_name or record.id)
        for record in records
    )


def remaining_by_move(env, moves):
    """``{move.id: الكمية المتبقية قابلة للإرجاع}`` لكل الحركات دفعة واحدة.

    تكافئ نداء ``move._prepare_return_data()['remaining_delivered_qty']``
    لكل حركة على حدة، لكن باستعلام واحد بدل ثلاثة أو أربعة لكل حركة
    (``ensure_one`` يجعل النداء الفردي حتميًا، وكل نداء يقرأ
    ``returned_move_ids`` و ``quantity`` من قاعدة البيانات).

    النواة تحسبها هكذا (sale_stock ``stock.move._prepare_return_data``)::

        returned_qty = sum(rm.quantity for rm in move.returned_move_ids
                           if rm.state == 'done')
        remaining = move.quantity - returned_qty

    و``returned_move_ids`` هو One2many على ``origin_returned_move_id``
    (Many2one مفهرس) و``quantity`` حقل مخزَّن — فيُجمع المرتجع لكل
    الحركات معًا في ``_read_group`` واحد. قاعدة الحفاظ على النتيجة:
    نفس شرط ``state == 'done'`` ونفس الجمع، فالرقم مطابق للنواة حرفيًا.

    * الحركة الموجودة في القاموس قيمتها = النواة تمامًا (حتى السالبة).
    * الحركة الغائبة عن القاموس: إمّا لا وجود لها (حُذفت من
      ``.exists()``) أو ليس لها أي مرتجع منجز — والمتبقي ``move.quantity``
      كما في النواة. تُقرأ ``quantity`` من المجموعة نفسها فتُحمَّل
      للحركات كلها بجلب مسبق واحد.
    """
    moves = moves.exists()
    if not moves:
        return {}
    groups = env['stock.move'].sudo()._read_group(
        [('origin_returned_move_id', 'in', moves.ids),
         ('state', '=', 'done')],
        ['origin_returned_move_id'],
        ['quantity:sum'],
    )
    returned = {move.id: qty for move, qty in groups}
    return {
        move.id: move.quantity - returned.get(move.id, 0.0)
        for move in moves
    }
