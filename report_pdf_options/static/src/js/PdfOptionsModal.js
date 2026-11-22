/** @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { Dialog } from "@web/core/dialog/dialog";
import { Component, t, useProps } from "@odoo/owl";

export class PdfOptionsModal extends Component {
    static template = "report_pdf_options.ButtonOptions";
    static components = { Dialog };
    props = useProps({
        onSelectOption: t.function(),
        // injected by the dialog service
        close: t.function(),
    });

    setup() {
        this.title = _t("What do you want to do?");
    }

    executePdfAction(option) {
        this.props.onSelectOption(option);
    }
}
