import { Component, t, useProps } from "@odoo/owl";
import { RecordSelector } from "@web/core/record_selectors/record_selector";
import { MultiRecordSelector } from "@web/core/record_selectors/multi_record_selector";

/**
 * Typed parameter form. Each parameter becomes the matching input: date,
 * date and time, number, text, yes/no, selection, record or record list.
 * Values are sent to the server and bound as driver parameters there.
 */
export class ParamForm extends Component {
    static template = "sql_query_workbench.ParamForm";
    static components = { RecordSelector, MultiRecordSelector };
    props = useProps({
        params: t.array(),
        values: t.object(),
        onEnter: t.function().optional(),
    });

    set(name, value) {
        this.props.values[name] = value;
    }

    onInput(p, ev) {
        const t = ev.target;
        if (p.ptype === "boolean") {
            this.set(p.name, t.checked);
        } else if (p.ptype === "integer") {
            this.set(p.name, t.value === "" ? "" : parseInt(t.value, 10));
        } else if (p.ptype === "float") {
            this.set(p.name, t.value === "" ? "" : parseFloat(t.value));
        } else {
            this.set(p.name, t.value);
        }
    }

    onKeydown(ev) {
        if (ev.key === "Enter" && this.props.onEnter) {
            ev.preventDefault();
            this.props.onEnter();
        }
    }

    recordId(p) {
        const v = this.props.values[p.name];
        return typeof v === "number" && v > 0 ? v : false;
    }

    recordIds(p) {
        const v = this.props.values[p.name];
        return Array.isArray(v) ? v : [];
    }

    inputType(p) {
        return { date: "date", datetime: "datetime-local", integer: "number", float: "number" }[p.ptype] || "text";
    }
}
