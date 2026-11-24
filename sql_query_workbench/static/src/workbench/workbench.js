import { Component, onMounted, onWillStart, onWillUnmount, proxy, signal, usePlugin, useProps } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { CodeEditor } from "@web/core/code_editor/code_editor";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { _t } from "@web/core/l10n/translation";
import { download } from "@web/core/network/download";
import { NotificationPlugin } from "@web/core/notifications/notification_plugin";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { Layout } from "@web/search/layout";
import { ActionPlugin, standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { CsvExportDialog, SaveQueryDialog } from "./dialogs";
import { ParamForm } from "./param_form";
import { PlanView } from "./plan_view";
import { ResultGrid } from "./result_grid";
import { SchemaBrowser } from "./schema_browser";

if (!CodeEditor.MODES.includes("sql")) {
    CodeEditor.MODES.push("sql");
}

const DEFAULT_SQL = `-- Read-only: one SELECT, WITH or EXPLAIN statement.
-- Ctrl+Enter runs the query (or only the selected text).
SELECT p.id, p.name, p.email, p.create_date
  FROM res_partner p
 WHERE p.active
 ORDER BY p.create_date DESC
 LIMIT 100`;

/**
 * SQL Workbench client action. Two modes:
 * - console (tag sql_query_workbench.console): editor, schema browser, history,
 *   saved queries, run / explain, results, exports;
 * - run screen (tag sql_query_workbench.run): parameter form, results and
 *   exports of one saved query, for the groups it is shared with.
 */
export class SqlWorkbench extends Component {
    static template = "sql_query_workbench.Workbench";
    static components = {
        CodeEditor,
        Dropdown,
        DropdownItem,
        Layout,
        ParamForm,
        PlanView,
        ResultGrid,
        SchemaBrowser,
    };
    props = useProps(standardActionServiceProps);
    editorRef = signal.ref();

    setup() {
        this.orm = useService("orm");
        this.action = usePlugin(ActionPlugin);
        this.dialog = useService("dialog");
        this.notification = usePlugin(NotificationPlugin);
                this.isRun = this.props.action.tag === "sql_query_workbench.run";
        const params = this.props.action.params || this.props.action.context?.params || {};
        this.draftKey = `sql_query_workbench.draft.${user.userId}`;
        this.state = proxy({
            sql: "",
            query: null, // {id, name, can_edit}
            screen: null, // run screen data
            boot: { recent: [], saved: [], tags: [], limits: {} },
            consoleParams: [],
            values: {},
            result: null,
            running: false,
            showSchema: !useService("ui").isSmall,
            tagFilter: "",
            lastMode: "run",
        });
        this.lineOffset = 0;

        onWillStart(async () => {
            if (this.isRun) {
                const queryId = params.query_id;
                const screen = await this.orm.call("sql.query", "get_run_screen", [[queryId]]);
                this.state.screen = screen;
                this.state.query = { id: screen.id, name: screen.name, can_edit: screen.can_edit };
                for (const p of screen.params) {
                    this.state.values[p.name] = p.value;
                }
                this.env.config.setDisplayName(screen.name);
                return;
            }
            this.state.boot = await this.orm.call("sql.workbench", "console_bootstrap", []);
            if (params.query_id) {
                await this.loadQuery(params.query_id);
            } else if (params.run_id) {
                this.state.sql = await this.orm.call("sql.query.run", "console_sql", [[params.run_id]]);
            } else {
                let draft = null;
                try {
                    draft = browser.localStorage.getItem(this.draftKey);
                } catch {
                    draft = null;
                }
                this.state.sql = draft || DEFAULT_SQL;
            }
            await this.refreshConsoleParams();
        });

        onMounted(() => this.bindEditor());
        onWillUnmount(() => browser.clearTimeout(this.paramTimer));
    }

    // ------------------------------------------------------------------ editor
    get ace() {
        const el = this.editorRef()?.querySelector(".ace_editor");
        return el && window.ace ? window.ace.edit(el) : null;
    }

    bindEditor(attempt = 0) {
        if (this.isRun) {
            return;
        }
        const ace = this.ace;
        if (!ace) {
            if (attempt < 20) {
                browser.setTimeout(() => this.bindEditor(attempt + 1), 100);
            }
            return;
        }
        ace.commands.addCommand({
            name: "sqlwRun",
            bindKey: { win: "Ctrl-Enter", mac: "Command-Enter" },
            exec: () => this.run("run"),
        });
        ace.commands.addCommand({
            name: "sqlwExplain",
            bindKey: { win: "Ctrl-Shift-E", mac: "Command-Shift-E" },
            exec: () => this.run("explain"),
        });
        ace.focus();
    }

    onSqlChange(value) {
        this.state.sql = value;
        try {
            browser.localStorage.setItem(this.draftKey, value);
        } catch {
            // private mode or storage full: the draft simply is not kept
        }
        browser.clearTimeout(this.paramTimer);
        this.paramTimer = browser.setTimeout(() => this.refreshConsoleParams(), 500);
    }

    async refreshConsoleParams() {
        if (this.isRun) {
            return;
        }
        const names = await this.orm.call("sql.workbench", "console_params", [this.state.sql]);
        const typed = Object.fromEntries((this.state.query?.params || []).map((p) => [p.name, p]));
        this.state.consoleParams = names.map(
            (n) =>
                typed[n] || {
                    name: n,
                    label: n,
                    ptype: "char",
                    required: true,
                    options: [],
                    help: "",
                }
        );
    }

    insertText(text, replace = false) {
        if (replace) {
            this.state.query = null;
            this.setSql(text);
            return;
        }
        const ace = this.ace;
        if (!ace) {
            this.state.sql = `${this.state.sql}\n${text}`;
            return;
        }
        ace.insert(text);
        ace.focus();
    }

    setSql(sql) {
        this.state.sql = sql;
        this.onSqlChange(sql);
    }

    // ------------------------------------------------------------------ run
    get selectedSql() {
        const ace = this.ace;
        if (!ace) {
            return { sql: this.state.sql, offset: 0 };
        }
        const text = ace.getSelectedText();
        if (text && text.trim()) {
            return { sql: text, offset: ace.getSelectionRange().start.row };
        }
        return { sql: this.state.sql, offset: 0 };
    }

    get params() {
        return this.isRun ? this.state.screen.params : this.state.consoleParams;
    }

    async run(mode = "run") {
        if (this.state.running) {
            return;
        }
        this.state.running = true;
        this.state.lastMode = mode;
        try {
            let res;
            if (this.isRun) {
                res = await this.orm.call("sql.query", "run_query", [[this.state.query.id], this.state.values, mode], {
                    context: { sqlw_from_menu: true },
                });
                this.lineOffset = 0;
            } else {
                const { sql, offset } = this.selectedSql;
                this.lineOffset = offset;
                await this.refreshConsoleParams();
                res = await this.orm.call("sql.workbench", "console_run", [
                    sql,
                    this.state.values,
                    mode,
                    this.state.query?.id || false,
                ]);
                this.markError(res);
            }
            this.state.result = res;
        } finally {
            this.state.running = false;
        }
    }

    markError(res) {
        const ace = this.ace;
        if (!ace) {
            return;
        }
        if (!res.ok && res.line) {
            const row = res.line - 1 + this.lineOffset;
            ace.session.setAnnotations([{ row, column: 0, text: res.message, type: "error" }]);
            ace.gotoLine(row + 1, 0, true);
        } else {
            ace.session.clearAnnotations();
        }
    }

    get errorLine() {
        const r = this.state.result;
        return r && !r.ok && r.line ? r.line + this.lineOffset : null;
    }

    // ------------------------------------------------------------------ saved queries / history
    async loadQuery(id) {
        const q = await this.orm.call("sql.workbench", "console_load_query", [id]);
        this.state.query = { id: q.id, name: q.name, can_edit: q.can_edit, params: q.params };
        for (const p of q.params) {
            this.state.values[p.name] = p.value;
        }
        this.setSql(q.sql);
        this.state.result = null;
    }

    loadRecent(item) {
        this.state.query = null;
        this.setSql(item.sql);
    }

    newQuery() {
        this.state.query = null;
        this.state.result = null;
        this.setSql("SELECT ");
    }

    get savedFiltered() {
        const tag = this.state.tagFilter;
        return this.state.boot.saved.filter((q) => !tag || q.tags.includes(tag));
    }

    async save() {
        const q = this.state.query;
        if (q && q.can_edit) {
            await this.orm.call("sql.workbench", "console_save", [this.state.sql, null, q.id]);
            this.notification.add(_t("Saved to “%s”.", q.name), { type: "success" });
            return;
        }
        this.dialog.add(SaveQueryDialog, {
            onConfirm: async (name) => {
                const res = await this.orm.call("sql.workbench", "console_save", [this.state.sql, name]);
                this.state.query = { id: res.id, name: res.name, can_edit: true };
                this.state.boot.saved.push({ id: res.id, name: res.name, tags: [], state: "draft" });
                this.notification.add(_t("Saved as draft “%s”.", res.name), { type: "success" });
            },
        });
    }

    openQueryForm() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "sql.query",
            res_id: this.state.query.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openInConsole() {
        this.action.doAction({
            type: "ir.actions.client",
            tag: "sql_query_workbench.console",
            name: _t("SQL Workbench"),
            params: { query_id: this.state.query.id },
        });
    }

    async copySql() {
        const sql = this.isRun ? this.state.screen.sql : this.state.sql;
        await browser.navigator.clipboard.writeText(sql || "");
        this.notification.add(_t("SQL copied."), { type: "success" });
    }

    // ------------------------------------------------------------------ files
    payload(format, options = {}) {
        const base = { values: this.state.values, format, options };
        if (this.isRun) {
            return { ...base, query_id: this.state.query.id };
        }
        return { ...base, sql: this.selectedSql.sql };
    }

    get exportName() {
        return this.state.query?.name || "query";
    }

    async exportFile(format, options = {}) {
        try {
            await download({
                url: "/sql_query_workbench/export",
                data: { data: JSON.stringify(this.payload(format, options)) },
            });
        } catch (e) {
            const message = e?.data?.message || e?.message || _t("Export failed.");
            this.notification.add(message, { type: "danger" });
        }
    }

    exportCsv() {
        this.dialog.add(CsvExportDialog, {
            defaultName: this.exportName,
            onConfirm: (options) => this.exportFile("csv", options),
        });
    }

    exportXlsx() {
        return this.exportFile("xlsx", { filename: this.exportName, header: true });
    }

    async printPdf(orientation) {
        const action = await this.orm.call("sql.workbench", "print_pdf", [
            this.payload("pdf"),
            orientation,
            this.state.query?.name || false,
        ]);
        await this.action.doAction(action);
    }

    // ------------------------------------------------------------------ misc
    toggleSchema() {
        this.state.showSchema = !this.state.showSchema;
    }

    get statusText() {
        const r = this.state.result;
        if (!r || !r.ok) {
            return "";
        }
        if (r.kind === "plan") {
            return _t("Plan in %s ms", r.duration_ms);
        }
        return _t("%(rows)s rows in %(ms)s ms", { rows: r.row_count, ms: r.duration_ms });
    }

    get display() {
        return { controlPanel: {} };
    }
}

registry.category("actions").add("sql_query_workbench.console", SqlWorkbench);
registry.category("actions").add("sql_query_workbench.run", SqlWorkbench);
