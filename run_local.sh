#!/usr/bin/env bash
# Локальная пускалка: тот же код, что в CI (шаги валидация → staging →
# генерация → pull → up/wait → сбор → down). Запускать из репозитория
# компонента (или указать --repo).
#
#   ./run_local.sh <config_name> [--repo DIR] [--slot lin-x64]
#                  [--artifacts DIR] [--secrets DIR] [--out DIR]
#                  [--dry-run] [-- <extra tdc args>]
set -euo pipefail

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    sed -n '2,7p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 2
}

[ $# -ge 1 ] || usage
CFG="$1"; shift

REPO="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
SLOT="lin-x64"
OUT=""
ART=""
SECRETS=""
EXTRA=()
while [ $# -gt 0 ]; do
    case "$1" in
        --repo)      REPO="$2"; shift 2 ;;
        --slot)      SLOT="$2"; shift 2 ;;
        --artifacts) ART="$2"; shift 2 ;;
        --secrets)   SECRETS="$2"; shift 2 ;;
        --out)       OUT="$2"; shift 2 ;;
        --dry-run)   EXTRA+=(--dry-run); shift ;;
        --)          shift; EXTRA+=("$@"); break ;;
        *)           usage ;;
    esac
done
OUT="${OUT:-$REPO/.tdc-out}"

ARGS=(run --mode local --repo "$REPO" --config "$CFG" --slot "$SLOT" --out "$OUT")
[ -n "$ART" ] && ARGS+=(--artifacts "$ART")
[ -n "$SECRETS" ] && ARGS+=(--secrets "$SECRETS")

exec env PYTHONPATH="$SELF" python3 -m tdc "${ARGS[@]}" ${EXTRA[@]+"${EXTRA[@]}"}
