/** @odoo-module **/

import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { getReportUrl } from "@web/webclient/actions/reports/utils";
import { PdfOptionsModal } from "./PdfOptionsModal";

let iframeForReport;

function printPdf(url, callback) {
    let iframe = iframeForReport;
    if (!iframe) {
        iframe = iframeForReport = document.createElement("iframe");
        iframe.className = "pdfIframe";
        document.body.appendChild(iframe);
        iframe.style.display = "none";
        iframe.onload = function () {
            setTimeout(function () {
                iframe.focus();
                iframe.contentWindow.print();
                callback();
            }, 1);
        };
    }
    iframe.src = url;
}

/**
 * Odoo 20 can render pdfs with several engines ("qweb-pdf", "qweb-pdf-wkhtmltopdf",
 * "qweb-pdf-paper-muncher", ...), the state of the engine used by the report has to
 * be checked on the server before trying to print or open the pdf directly.
 * The state is asked only once per engine.
 */
const engineStates = new Map();

function getEngineName(reportType) {
    // "qweb-pdf" -> undefined (default engine), "qweb-pdf-wkhtmltopdf" -> "wkhtmltopdf"
    const type = reportType.slice(5);
    return type.startsWith("pdf-") ? type.slice(4) : undefined;
}

async function getPdfEngineState(engineName) {
    const key = engineName || "";
    if (!engineStates.has(key)) {
        const params = engineName ? { engine_name: engineName } : {};
        const stateProm = rpc("/report/get_pdf_engine_state", params).catch((error) => {
            // do not keep a failed request in cache, the next report will retry it
            engineStates.delete(key);
            throw error;
        });
        engineStates.set(key, stateProm);
    }
    return engineStates.get(key);
}

registry
    .category("ir.actions.report handlers")
    .add("pdf_report_options_handler", async function (action, options, env) {
        const { report_type } = action;
        if (!report_type?.startsWith("qweb-pdf")) {
            return false;
        }

        let defaultPrintOption = action.default_print_option;
        if (!defaultPrintOption) {
            let removeDialog;
            const option = await new Promise((resolve) => {
                removeDialog = env.services.dialog.add(
                    PdfOptionsModal,
                    { onSelectOption: resolve },
                    { onClose: () => resolve("close") }
                );
            });
            removeDialog();
            if (option === "close") {
                return true;
            }
            defaultPrintOption = option;
        }
        if (defaultPrintOption !== "print" && defaultPrintOption !== "open") {
            // "download" (or no option chosen): let the standard handler do its job
            return false;
        }

        let state;
        try {
            state = await getPdfEngineState(getEngineName(report_type));
        } catch {
            // let the standard handler display the error
            return false;
        }
        if (!["ok", "upgrade"].includes(state)) {
            // No usable pdf engine: returning false lets the standard handler display
            // a notification and open the report in the client action (html).
            return false;
        }

        const url = getReportUrl(action, "pdf");
        if (defaultPrintOption === "print") {
            env.services.ui.block();
            printPdf(url, () => {
                env.services.ui.unblock();
            });
        } else if (defaultPrintOption === "open") {
            window.open(url);
        }
        return true;
    });
