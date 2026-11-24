import { Component, t, useProps } from "@odoo/owl";

/** EXPLAIN plan as an indented tree with cost share and sequential-scan flags. */
export class PlanView extends Component {
    static template = "sql_query_workbench.PlanView";
    props = useProps({ plan: t.object(), analyze: t.boolean() });

    num(v, digits = 0) {
        if (v === null || v === undefined) {
            return "";
        }
        return Number(v).toLocaleString(undefined, { maximumFractionDigits: digits });
    }

    share(n) {
        return Math.max(0, Math.min(n.cost_share || 0, 100));
    }

    get warnings() {
        return this.props.plan.nodes.filter((n) => n.seq_scan_warning).length;
    }
}
