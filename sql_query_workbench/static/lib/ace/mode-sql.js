/* SQL Query Workbench - PostgreSQL highlighting mode for the ace editor shipped with Odoo.
 * Copyright Viyug Infotech. License LGPL-3. */
ace.define(
    "ace/mode/sql",
    ["require", "exports", "module", "ace/lib/oop", "ace/mode/text", "ace/mode/text_highlight_rules"],
    function (require, exports) {
        "use strict";
        const oop = require("ace/lib/oop");
        const TextMode = require("ace/mode/text").Mode;
        const TextHighlightRules = require("ace/mode/text_highlight_rules").TextHighlightRules;

        const KEYWORDS = [
            "select", "from", "where", "and", "or", "not", "in", "is", "null", "as", "on", "join",
            "inner", "left", "right", "full", "outer", "cross", "lateral", "natural", "using",
            "group", "by", "order", "having", "limit", "offset", "fetch", "first", "next", "rows",
            "only", "union", "intersect", "except", "all", "distinct", "with", "recursive", "case",
            "when", "then", "else", "end", "between", "like", "ilike", "similar", "to", "exists",
            "any", "some", "asc", "desc", "nulls", "last", "over", "partition", "window", "filter",
            "within", "explain", "analyze", "verbose", "format", "json", "values", "interval",
            "at", "time", "zone", "escape", "collate", "array", "row", "tablesample", "materialized",
            "insert", "update", "delete", "create", "drop", "alter", "truncate", "grant", "revoke",
        ].join("|");
        const TYPES = [
            "int", "integer", "bigint", "smallint", "numeric", "decimal", "real", "double", "precision",
            "float", "text", "varchar", "char", "character", "varying", "boolean", "bool", "date",
            "timestamp", "timestamptz", "jsonb", "uuid", "bytea", "regclass", "oid",
        ].join("|");
        const FUNCTIONS = [
            "count", "sum", "avg", "min", "max", "coalesce", "nullif", "greatest", "least", "now",
            "date_trunc", "date_part", "extract", "to_char", "to_date", "age", "round", "abs",
            "lower", "upper", "length", "substring", "trim", "concat", "string_agg", "array_agg",
            "jsonb_agg", "json_agg", "jsonb_build_object", "row_number", "rank", "dense_rank", "lag",
            "lead", "unnest", "generate_series", "cast", "pg_size_pretty", "pg_total_relation_size",
            "pg_relation_size", "format_type", "current_date", "current_timestamp",
        ].join("|");

        function SqlHighlightRules() {
            const keywordMapper = this.createKeywordMapper(
                {
                    "keyword": KEYWORDS,
                    "storage.type": TYPES,
                    "support.function": FUNCTIONS,
                    "constant.language": "true|false",
                },
                "identifier",
                true
            );
            this.$rules = {
                start: [
                    { token: "comment", regex: "--.*$" },
                    { token: "comment", regex: "\\/\\*", next: "comment" },
                    { token: "string", regex: "[eE]?'", next: "string" },
                    { token: "variable", regex: '"(?:[^"]|"")*"' },
                    { token: "keyword.operator", regex: "::" },
                    { token: "variable.parameter", regex: ":[A-Za-z_][A-Za-z0-9_]*" },
                    { token: "constant.numeric", regex: "\\b\\d+(?:\\.\\d+)?(?:[eE][+-]?\\d+)?\\b" },
                    { token: keywordMapper, regex: "[A-Za-z_][A-Za-z0-9_$]*\\b" },
                    { token: "keyword.operator", regex: "[+\\-*/<>=!~|%^&]+" },
                    { token: "paren.lparen", regex: "[(\\[]" },
                    { token: "paren.rparen", regex: "[)\\]]" },
                    { token: "punctuation", regex: "[,;.]" },
                    { token: "text", regex: "\\s+" },
                ],
                comment: [
                    { token: "comment", regex: "\\*\\/", next: "start" },
                    { defaultToken: "comment" },
                ],
                string: [
                    { token: "constant.character.escape", regex: "''" },
                    { token: "string", regex: "'", next: "start" },
                    { defaultToken: "string" },
                ],
            };
            this.normalizeRules();
        }
        oop.inherits(SqlHighlightRules, TextHighlightRules);

        function Mode() {
            this.HighlightRules = SqlHighlightRules;
            this.$behaviour = this.$defaultBehaviour;
        }
        oop.inherits(Mode, TextMode);
        (function () {
            this.lineCommentStart = "--";
            this.blockComment = { start: "/*", end: "*/" };
            this.$id = "ace/mode/sql";
        }).call(Mode.prototype);

        exports.Mode = Mode;
    }
);
