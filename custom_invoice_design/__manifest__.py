{
    'name': 'Custom Invoice Design',
    'version': '20.0.1.0.0',
    'summary': 'Custom professional ZATCA-compliant invoice PDF report (bilingual Arabic/English)',
    'description': """
Custom Invoice Design Module
============================

Small Custom QWeb Report Module for Customer Invoices (account.move)
- Professional bilingual design (Arabic/English) matching ZATCA requirements
- Dynamic QR code (supports standard Saudi/GCC localization fields)
- Binds to Customer Invoices Print menu (account.move)
- Credit Note support (out_refund)
- Standalone: does NOT modify standard Odoo reports

Ported to Odoo 20.0:
- QWeb `t-esc` / `t-raw` directives removed upstream -> migrated to `t-out`
- New `tax_totals` JSON structure (subtotals -> tax_groups -> group_name/tax_amount_currency)
- `res.bank` model removed -> bank details read from `res.partner.bank`
  (`account_number`, `holder_name`, `bank_name`, `bank_bic`)
- Partner commercial registration moved to `additional_identifiers` (SA_CRN)
- Invoice lines: `display_type` is now an explicit value ('product' / 'line_subsection')
- ZATCA QR taken from `l10n_sa_qr_code_str` and URL-encoded with `quote_plus`
    """,
    'author': 'Islam Elgafey',
    'category': 'Accounting/Accounting',
    'license': 'LGPL-3',
    'depends': ['base', 'account'],
    'data': [
        'report/invoice_report.xml',
        'report/invoice_report_template.xml',
    ],
    # No global report assets: all styling lives in the embedded <style> block
    # of report.invoice_report_document. Injecting into web.report_assets_common
    # (the bundle shared by EVERY report) from a path outside static/ broke the
    # whole report bundle and unstyled all printouts.
    'installable': True,
    'application': False,
    'auto_install': False,
}
