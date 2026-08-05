#!/usr/bin/env bash
# Эталонный прогон: запускает так, как это будет делать TeamCity.
#
#   ./smoke/run_as_ci.sh <путь к репозиторию> [слот]
#
# Отличия от run_local.sh, то есть от того, как запускает разработчик:
#   mode=ci          прогоняются ВСЕ наборы репозитория, подходящие слоту,
#                    а не один по имени
#   параметры        приходят переменными окружения TDC_*, как их задаёт
#                    шаблон сборки, а не ключами командной строки
#   preflight        python3, docker, compose, свободное место. Не сошлось,
#                    билд валится с buildProblem, а не падает посреди прогона
#   имя проекта      tc<номер сборки>, чтобы прогоны разных сборок на одном
#                    агенте не мешали друг другу
set -euo pipefail

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="${1:-}"
SLOT="${2:-lin-x64}"

[ -n "$REPO" ] || { echo "укажите путь к репозиторию" >&2; exit 2; }
[ -d "$REPO" ] || { echo "нет такого каталога: $REPO" >&2; exit 2; }

OUT="${TDC_OUT:-$(mktemp -d)/tdc-ci}"

echo "== так это будет запускаться на агенте"
echo "   репозиторий: $REPO"
echo "   слот:        $SLOT"
echo "   отчёты:      $OUT"
echo

# Эти переменные на агенте подставляет шаблон сборки.
export TDC_REPO="$REPO"
export TDC_SLOT="$SLOT"
export TDC_OUT="$OUT"
export TDC_BUILD_ID="${TDC_BUILD_ID:-9999}"          # на агенте это BUILD_NUMBER
export BUILD_NUMBER="${BUILD_NUMBER:-9999}"
export VCS_REVISION="${VCS_REVISION:-$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo unknown)}"
# TDC_ARTIFACTS и TDC_SECRETS задаются, только если наборы их требуют
[ -n "${TDC_ARTIFACTS:-}" ] && export TDC_ARTIFACTS
[ -n "${TDC_SECRETS:-}" ] && export TDC_SECRETS

set +e
"$SELF/ci/run_tests.sh"
RC=$?
set -e

echo
echo "== итог"
echo "   код возврата: $RC   (0 значит все наборы прошли или пропущены)"
for d in "$OUT"/reports/*/; do
    [ -d "$d" ] || continue
    name="$(basename "$d")"
    printf "   %-24s trx %s, cobertura %s\n" "$name" \
        "$(find "$d" -name '*.trx' 2>/dev/null | wc -l | tr -d ' ')" \
        "$(find "$d" -name '*.cobertura.xml' 2>/dev/null | wc -l | tr -d ' ')"
done
echo "   остатки: контейнеров $(docker ps -aq --filter label=tc.in662 | wc -l | tr -d ' ')," \
     "томов $(docker volume ls -q --filter label=tc.in662 | wc -l | tr -d ' ')"
echo "   отчёты:  $OUT"
exit "$RC"
