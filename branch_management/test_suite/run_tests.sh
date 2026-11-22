#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# branch_management - full test suite for Odoo 20
# ---------------------------------------------------------------------------
# Runs every phase harness in its OWN `odoo shell` transaction, because each
# script creates its own fixtures and rolls the transaction back at the end
# (running them in a single session would make one phase erase the data of
# the previous one).
#
# Usage:
#   ./run_tests.sh                 run everything + the core integrity check
#   ./run_tests.sh 4 7             run only phase 4 and phase 7
#   ./run_tests.sh --no-upgrade    do not upgrade the module before testing
#
# Environment overrides:
#   ODOO_BIN        default /usr/bin/odoo
#   ODOO_DB         default balance_mod   (scratch database, NOT test20)
#   ODOO_PG_HOST    default 127.0.0.1
#   ODOO_PG_PORT    default 55432
#   ODOO_PG_USER    default admin
#   ODOO_ADDONS     default <parent of this module>,core addons
#   ODOO_HTTP_PORT  default 8097           (production uses 8069)
#   ODOO_CORE       set to 0 to skip the Odoo core integrity check
#
# Exit code: 0 when everything passed, 1 otherwise (CI friendly), 2 bad
# argument, 3 refused target database.
# ---------------------------------------------------------------------------
set -u

SUITE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_DIR="$(cd "${SUITE_DIR}/.." && pwd)"
ADDONS_DIR="$(dirname "${MODULE_DIR}")"

ODOO_BIN="${ODOO_BIN:-/usr/bin/odoo}"
ODOO_DB="${ODOO_DB:-balance_mod}"
ODOO_PG_HOST="${ODOO_PG_HOST:-127.0.0.1}"
ODOO_PG_PORT="${ODOO_PG_PORT:-55432}"
ODOO_PG_USER="${ODOO_PG_USER:-admin}"
ODOO_HTTP_PORT="${ODOO_HTTP_PORT:-8097}"
ODOO_CORE="${ODOO_CORE:-1}"
ODOO_ADDONS="${ODOO_ADDONS:-/usr/lib/python3/dist-packages/odoo/addons,${ADDONS_DIR}}"
ODOO_EXTRA_ARGS="${ODOO_EXTRA_ARGS:-}"

UPGRADE=1
SELECTED=()

declare -A TITLE=(
    [2]="core model         "
    [3]="security           "
    [4]="sales              "
    [5]="inventory          "
    [6]="accounting/analytic"
    [7]="reports & buttons  "
    [9]="payments           "
    [10]="contacts          "
    [11]="access tightening  "
    [12]="invoice analysis   "
    [13]="pivot measures     "
    [14]="every line carries "
    [15]="partner ledger     "
    [16]="branch journals    "
    [17]="sales journal      "
    [18]="stock visibility   "
    [19]="price list         "
    [20]="locked price list  "
)

usage() { sed -n '2,27p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

for arg in "$@"; do
    case "$arg" in
        --no-upgrade) UPGRADE=0 ;;
        -h|--help)    usage; exit 0 ;;
        [0-9]|[0-9][0-9])  SELECTED+=("$arg") ;;
        *)            echo "unknown argument: $arg" >&2; usage; exit 2 ;;
    esac
done
[ ${#SELECTED[@]} -eq 0 ] && SELECTED=(2 3 4 5 6 7 9 10 11 12 13 14 15 16 17 18 19 20)

# The suite is only allowed on a scratch database: it upgrades the module and
# creates fixtures (rolled back, but the upgrade is not).
if [ "${ODOO_DB}" = "test20" ]; then
    echo "refusing to run the test suite on the production database 'test20'." >&2
    echo "point ODOO_DB at a scratch database, e.g.  ODOO_DB=balance_mod $0" >&2
    exit 3
fi

shell() {                        # run one harness through `odoo shell`
    "${ODOO_BIN}" shell \
        -d "${ODOO_DB}" \
        --db_host="${ODOO_PG_HOST}" --db_port="${ODOO_PG_PORT}" \
        --db_user="${ODOO_PG_USER}" \
        --addons-path="${ODOO_ADDONS}" \
        --max-cron-threads=0 --log-level=error \
        --http-port="${ODOO_HTTP_PORT}" ${ODOO_EXTRA_ARGS} < "$1" 2>&1
}

count() { printf '%s\n' "$1" | grep -cE "$2"; }
tail_of() { printf '%s\n' "$1" | grep -E '^(FAIL|FATAL|Traceback|odoo\.|  File)' | tail -12 | sed 's/^/        /'; }

echo "=================================================================="
echo " branch_management test suite  -  database: ${ODOO_DB}"
echo "=================================================================="

# --------------------------------------------------------------- upgrade --
if [ "${UPGRADE}" = "1" ]; then
    printf 'upgrading branch_management ... '
    up_out=$("${ODOO_BIN}" -d "${ODOO_DB}" \
        --db_host="${ODOO_PG_HOST}" --db_port="${ODOO_PG_PORT}" \
        --db_user="${ODOO_PG_USER}" --addons-path="${ODOO_ADDONS}" \
        --max-cron-threads=0 --log-level=warn \
        --http-port="${ODOO_HTTP_PORT}" ${ODOO_EXTRA_ARGS} \
        -u branch_management --stop-after-init 2>&1)
    up_rc=$?
    if [ "${up_rc}" -ne 0 ]; then
        echo "FAILED"
        printf '%s\n' "${up_out}" | tail -25
        echo "==== TOTAL: the upgrade failed ===="
        exit 1
    fi
    echo "ok"
fi

# ------------------------------------------------------------------ tests --
TOTAL_PASS=0
TOTAL_FAIL=0
TOTAL_SKIP=0
FAILED_PHASES=()

for phase in "${SELECTED[@]}"; do
    script="${SUITE_DIR}/test_phase${phase}.py"
    if [ ! -f "${script}" ]; then
        printf '[MISS] phase %s - %s (file not found)\n' \
            "${phase}" "${TITLE[$phase]:-}"
        TOTAL_FAIL=$((TOTAL_FAIL + 1))
        FAILED_PHASES+=("${phase}")
        continue
    fi

    out="$(shell "${script}")"

    p="$(count "${out}" '^PASS[ |]')"
    f="$(count "${out}" '^(FAIL[ |]|FATAL)')"
    s="$(count "${out}" '^SKIP[ |]')"

    if [ "${p}" -eq 0 ] && [ "${f}" -eq 0 ]; then
        # the harness never reached its summary: odoo crashed before it
        printf '[ERR ] phase %s - %-19s no result\n' \
            "${phase}" "${TITLE[$phase]:-}"
        tail_of "${out}"
        TOTAL_FAIL=$((TOTAL_FAIL + 1))
        FAILED_PHASES+=("${phase}")
        continue
    fi

    TOTAL_PASS=$((TOTAL_PASS + p))
    TOTAL_FAIL=$((TOTAL_FAIL + f))
    TOTAL_SKIP=$((TOTAL_SKIP + s))

    if [ "${f}" -eq 0 ]; then
        printf '[PASS] phase %s - %-19s %s passed, %s failed, %s skipped\n' \
            "${phase}" "${TITLE[$phase]:-}" "${p}" "${f}" "${s}"
    else
        printf '[FAIL] phase %s - %-19s %s passed, %s failed, %s skipped\n' \
            "${phase}" "${TITLE[$phase]:-}" "${p}" "${f}" "${s}"
        tail_of "${out}"
        FAILED_PHASES+=("${phase}")
    fi
done

# ---------------------------------------------------- Odoo core integrity --
# The module only uses the standard extension mechanisms, so no file of the
# Odoo package may be modified and no core file may reference the module or
# one of its own symbols.
if [ "${ODOO_CORE}" = "1" ]; then
    core_files="$(dpkg -V odoo 2>/dev/null \
        | grep -E '/usr/lib/python3/dist-packages/odoo' || true)"
    core_refs="$(grep -rl 'branch_management\|branch_visible_ids\|branch_analytic_auto' \
        /usr/lib/python3/dist-packages/odoo/addons \
        --include='*.py' --include='*.xml' --include='*.csv' 2>/dev/null || true)"

    if [ -z "${core_files}" ] && [ -z "${core_refs}" ]; then
        printf '[PASS] odoo core integrity    0 modified file, 0 reference to the module\n'
    else
        printf '[FAIL] odoo core integrity\n'
        [ -n "${core_files}" ] && printf '%s\n' "${core_files}" | sed 's/^/        /'
        [ -n "${core_refs}" ]  && printf '%s\n' "${core_refs}"  | sed 's/^/        /'
        TOTAL_FAIL=$((TOTAL_FAIL + 1))
    fi
fi

# ------------------------------------------------------------------ total --
echo "=================================================================="
echo "==== TOTAL: ${TOTAL_PASS} passed, ${TOTAL_FAIL} failed, ${TOTAL_SKIP} skipped ===="
if [ "${TOTAL_FAIL}" -eq 0 ]; then
    exit 0
fi
echo "==== failed phases: ${FAILED_PHASES[*]} ===="
exit 1
