import { Component, onWillUpdateProps, proxy, t, usePlugin, useProps } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { _t } from "@web/core/l10n/translation";
import { browser } from "@web/core/browser/browser";
import { NotificationPlugin } from "@web/core/notifications/notification_plugin";

const PAGE_SIZES = [50, 100, 250, 1000];

function compare(a, b) {
    if (a === b) {
        return 0;
    }
    if (a === null || a === undefined) {
        return 1; // NULLs last
    }
    if (b === null || b === undefined) {
        return -1;
    }
    if (typeof a === "number" && typeof b === "number") {
        return a - b;
    }
    return String(a).localeCompare(String(b), undefined, { numeric: true });
}

export function cellText(value) {
    if (value === null || value === undefined) {
        return "";
    }
    if (typeof value === "boolean") {
        return value ? "true" : "false";
    }
    return String(value);
}

/**
 * Result grid: row numbers, sticky header, sort, pagination, quick filter,
 * hide/reorder columns, NULL highlighting, totals/averages for numeric columns
 * and click-through to Odoo records.
 */
export class ResultGrid extends Component {
    static template = "sql_query_workbench.ResultGrid";
    static components = { Dropdown };
    props = useProps({
        result: t.object(),
    });

    setup() {
        this.notification = usePlugin(NotificationPlugin);
        this.state = proxy(this.initialState(this.props.result));
        onWillUpdateProps((next) => {
            if (next.result !== this.props.result) {
                Object.assign(this.state, this.initialState(next.result));
            }
        });
    }

    initialState(result) {
        return {
            sortCol: null,
            sortDir: 1,
            page: 0,
            pageSize: 50,
            filter: "",
            order: result.columns.map((_, i) => i),
            hidden: {},
            highlightNull: true,
        };
    }

    get pageSizes() {
        return PAGE_SIZES;
    }

    get visibleColumns() {
        return this.state.order.filter((i) => !this.state.hidden[i]);
    }

    get filteredRows() {
        const key = [this.props.result, this.state.filter, this.state.sortCol, this.state.sortDir,
            JSON.stringify(this.state.hidden), this.state.order.join(",")];
        if (this._memo && this._memo.key.every((k, i) => k === key[i])) {
            return this._memo.rows;
        }
        const rows = this.props.result.rows;
        const needle = this.state.filter.trim().toLowerCase();
        let out = rows.map((row, idx) => ({ row, idx }));
        if (needle) {
            const cols = this.visibleColumns;
            out = out.filter(({ row }) =>
                cols.some((c) => cellText(row[c]).toLowerCase().includes(needle))
            );
        }
        if (this.state.sortCol !== null) {
            const c = this.state.sortCol;
            const dir = this.state.sortDir;
            out = [...out].sort((a, b) => dir * compare(a.row[c], b.row[c]) || a.idx - b.idx);
        }
        this._memo = { key, rows: out };
        return out;
    }

    get pageCount() {
        return Math.max(1, Math.ceil(this.filteredRows.length / this.state.pageSize));
    }

    get pageRows() {
        const start = this.state.page * this.state.pageSize;
        return this.filteredRows.slice(start, start + this.state.pageSize);
    }

    get pageStart() {
        return this.state.page * this.state.pageSize;
    }

    get footer() {
        const rows = this.filteredRows;
        const out = {};
        for (const c of this.visibleColumns) {
            const col = this.props.result.columns[c];
            if (!col.numeric || col.masked || col.model) {
                continue;
            }
            let sum = 0;
            let n = 0;
            for (const { row } of rows) {
                const v = row[c];
                if (typeof v === "number") {
                    sum += v;
                    n++;
                }
            }
            out[c] = n ? { sum, avg: sum / n } : null;
        }
        return out;
    }

    get hasFooter() {
        return Object.values(this.footer).some(Boolean);
    }

    formatNumber(v) {
        if (typeof v !== "number") {
            return "";
        }
        return Number.isInteger(v)
            ? v.toLocaleString()
            : v.toLocaleString(undefined, { maximumFractionDigits: 2 });
    }

    recordUrl(col, value) {
        if (!col.model || typeof value !== "number" || !Number.isInteger(value) || value <= 0) {
            return false;
        }
        return `/odoo/${col.model}/${value}`;
    }

    text(value) {
        return cellText(value);
    }

    isLong(value) {
        return typeof value === "string" && value.length > 120;
    }

    sortBy(c) {
        if (this.state.sortCol === c) {
            if (this.state.sortDir === 1) {
                this.state.sortDir = -1;
            } else {
                this.state.sortCol = null;
                this.state.sortDir = 1;
            }
        } else {
            this.state.sortCol = c;
            this.state.sortDir = 1;
        }
        this.state.page = 0;
    }

    onFilter(ev) {
        this.state.filter = ev.target.value;
        this.state.page = 0;
    }

    setPage(p) {
        this.state.page = Math.min(Math.max(p, 0), this.pageCount - 1);
    }

    setPageSize(ev) {
        this.state.pageSize = parseInt(ev.target.value, 10);
        this.state.page = 0;
    }

    toggleColumn(c) {
        this.state.hidden[c] = !this.state.hidden[c];
    }

    moveColumn(c, delta) {
        const order = [...this.state.order];
        const i = order.indexOf(c);
        const j = i + delta;
        if (j < 0 || j >= order.length) {
            return;
        }
        [order[i], order[j]] = [order[j], order[i]];
        this.state.order = order;
    }

    showAll() {
        this.state.hidden = {};
        this.state.order = this.props.result.columns.map((_, i) => i);
    }

    /** Tab separated text of the filtered/sorted rows and visible columns. */
    asTsv() {
        const cols = this.visibleColumns;
        const clean = (v) => cellText(v).replace(/[\t\r\n]+/g, " ");
        const lines = [cols.map((c) => this.props.result.columns[c].name).join("\t")];
        for (const { row } of this.filteredRows) {
            lines.push(cols.map((c) => clean(row[c])).join("\t"));
        }
        return lines.join("\n");
    }

    async copyResult() {
        await browser.navigator.clipboard.writeText(this.asTsv());
        this.notification.add(_t("%s rows copied (tab separated).", this.filteredRows.length), {
            type: "success",
        });
    }

    get sortLabel() {
        return this.state.sortDir === 1 ? _t("ascending") : _t("descending");
    }
}
