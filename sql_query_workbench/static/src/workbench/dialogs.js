import { Component, proxy, t, useProps } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class CsvExportDialog extends Component {
    static template = "sql_query_workbench.CsvExportDialog";
    static components = { Dialog };
    props = useProps({ close: t.function(), defaultName: t.string(), onConfirm: t.function() });

    setup() {
        this.state = proxy({
            filename: this.props.defaultName,
            separator: "comma",
            quote: "double",
            header: true,
            bom: false,
            line_ending: "crlf",
        });
    }

    async confirm() {
        await this.props.onConfirm({ ...this.state });
        this.props.close();
    }
}

export class SaveQueryDialog extends Component {
    static template = "sql_query_workbench.SaveQueryDialog";
    static components = { Dialog };
    props = useProps({ close: t.function(), onConfirm: t.function() });

    setup() {
        this.state = proxy({ name: "" });
    }

    async confirm() {
        if (!this.state.name.trim()) {
            return;
        }
        await this.props.onConfirm(this.state.name.trim());
        this.props.close();
    }
}
