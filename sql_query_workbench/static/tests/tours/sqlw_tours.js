import { registry } from "@web/core/registry";
import { stepUtils } from "@web_tour/tour_utils";

registry.category("web_tour.tours").add("sqlw_console_tour", {
    url: "/odoo/action-sql_query_workbench.action_sql_workbench_console",
    steps: () => [
        { trigger: ".o_sqlw_ace.ace_editor", content: "editor loaded" },
        { trigger: ".o_sqlw_ace[data-mode=sql]", content: "SQL highlighting mode active" },
        { trigger: ".o_sqlw_raw_warning:contains(record rules)", content: "raw data warning shown" },
        { trigger: ".o_sqlw_saved_btn", run: "click" },
        { trigger: ".dropdown-item:contains(Installed modules)", run: "click" },
        { trigger: ".o_sqlw_main span:contains(Editing) b:contains(Installed modules)" },
        { trigger: ".o_sqlw_run", run: "click" },
        { trigger: ".o_sqlw_ok", content: "query ran" },
        { trigger: ".o_sqlw_table tbody td a[href^='/odoo/ir.module.module/']", content: "id column links to the module" },
        { trigger: ".o_sqlw_filter", run: "edit sql_query_workbench" },
        { trigger: ".o_sqlw_table tbody tr:first-child:last-child td:contains(sql_query_workbench)", content: "filter keeps one row" },
        { trigger: ".o_sqlw_explain_btn", run: "click" },
        { trigger: ".dropdown-item:contains(Plan (estimates))", run: "click" },
        { trigger: ".o_sqlw_plan_table td b:contains(Scan)", content: "plan tree shown" },
        { trigger: ".o_sqlw_schema_search", run: "edit res_country" },
        { trigger: ".o_sqlw_table_item span.fw-semibold:text(res_country)", run: "click" },
        { trigger: ".o_sqlw_detail_name:contains(res_country)" },
        { trigger: ".o_sqlw_column_item:contains(code)", content: "columns listed" },
        { trigger: ".o_sqlw_insert_select", run: "click" },
        { trigger: ".o_sqlw_run", run: "click" },
        { trigger: ".o_sqlw_ok:contains(rows)" },
        { trigger: ".o_sqlw_table th:contains(code)", content: "inserted SELECT ran" },
    ],
});

registry.category("web_tour.tours").add("sqlw_run_screen_tour", {
    url: "/odoo",
    steps: () => [
        stepUtils.showAppsMenuItem(),
        { trigger: ".o_app[data-menu-xmlid='sql_query_workbench.menu_sql_reports_root']", run: "click" },
        { trigger: ".o_sqlw_run_head h2:contains(Tour report)" },
        { trigger: ".o_sqlw_param[data-param=login_like] input", run: "edit adm%" },
        { trigger: ".o_sqlw_run", run: "click" },
        { trigger: ".o_sqlw_ok" },
        { trigger: ".o_sqlw_table tbody td:contains(admin)" },
        {
            trigger: "body:not(:has(.o_sqlw_ace))",
            content: "no SQL editor on the run screen for run-only users",
        },
    ],
});
