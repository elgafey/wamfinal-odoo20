import { Component, onWillStart, proxy, t, useProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

/**
 * Schema browser: tables from pg_catalog joined to Odoo models, columns with SQL
 * type and Odoo field label/type, row estimates, sizes, indexes and foreign keys.
 * Clicking a name inserts it into the editor.
 */
export class SchemaBrowser extends Component {
    static template = "sql_query_workbench.SchemaBrowser";
    props = useProps({ onInsert: t.function() });

    setup() {
        this.orm = useService("orm");
        this.state = proxy({ tables: [], search: "", detail: null, loading: false, showAll: false });
        onWillStart(async () => {
            this.state.tables = await this.orm.call("sql.workbench", "schema_tables", []);
        });
    }

    get filtered() {
        const s = this.state.search.trim().toLowerCase();
        let tables = this.state.tables;
        if (s) {
            tables = tables.filter(
                (t) =>
                    t.name.includes(s) ||
                    t.model.includes(s) ||
                    (t.model_name || "").toLowerCase().includes(s)
            );
        }
        return this.state.showAll || s ? tables.slice(0, 400) : tables.slice(0, 150);
    }

    formatRows(n) {
        if (n >= 1e6) {
            return (n / 1e6).toFixed(1) + "M";
        }
        if (n >= 1e3) {
            return (n / 1e3).toFixed(1) + "k";
        }
        return String(n);
    }

    async open(name) {
        this.state.loading = true;
        try {
            this.state.detail = await this.orm.call("sql.workbench", "schema_table", [name]);
        } finally {
            this.state.loading = false;
        }
    }

    back() {
        this.state.detail = null;
    }

    insert(text) {
        this.props.onInsert(text);
    }

    insertSelect(table) {
        this.props.onInsert(`SELECT *\n  FROM ${table}\n LIMIT 100`, true);
    }

    insertColumns() {
        const d = this.state.detail;
        const cols = d.columns.filter((c) => !c.denied).map((c) => c.name);
        this.props.onInsert(`SELECT ${cols.join(",\n       ")}\n  FROM ${d.name}\n LIMIT 100`, true);
    }
}
