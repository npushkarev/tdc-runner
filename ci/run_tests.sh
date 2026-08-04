#!/usr/bin/env bash
# Универсальная пускалка тестов test_docker_config для TC-шаблона (IN-662).
# Один и тот же шаг билда для любого компонента и любого слота; вся
# параметризация — через окружение (задаётся шаблоном TC):
#   TDC_SLOT              слот вида lin-x64 (шаблон: env.TDC_SLOT = %slot.os%-%slot.arch%)
#   TDC_ARTIFACTS         каталог скачанных артефактов сборки (artifact dependency)
#   TDC_SECRETS           каталог с файлами-секретами (готовит шаг «Секреты»)
#   TDC_OUT               куда класть отчёты (публикуется артефактами билда)
#   TDC_REPO              корень checkout'а тестируемого репо (дефолт: текущий каталог)
#   TDC_BUILD_ID          уникальный id рана для compose project name
#                         (дефолт: BUILD_NUMBER от TC, иначе "local")
#   TDC_REGISTRY_PREFIXES разрешённые префиксы registry через пробел (опционально)
#   TDC_EXTRA_ARGS        дополнительные аргументы tdc run (например --dry-run)
set -euo pipefail

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # корень tdc-runner
REPO="${TDC_REPO:-$(pwd)}"
SLOT="${TDC_SLOT:-lin-x64}"
OUT="${TDC_OUT:-$REPO/.tdc-out}"
BUILD_ID="${TDC_BUILD_ID:-${BUILD_NUMBER:-local}}"

tc_problem() { echo "##teamcity[buildProblem description='$1']"; }

PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
    tc_problem "tdc preflight: python3 not found on agent"; exit 1
fi
if ! docker info >/dev/null 2>&1; then
    tc_problem "tdc preflight: docker daemon unavailable on agent"; exit 1
fi
# compose берётся из vendor/compose (пин контракта); системный плагин —
# запасной путь. Требовать плагин на агенте больше не нужно.
COMPOSE_INFO="$(cd "$SELF" && "$PY" -c 'from tdc import composebin
b, s = composebin.resolve()
print(("%s | %s" % (" ".join(b), s)) if b else "ERROR: %s" % s)' 2>&1)"
case "$COMPOSE_INFO" in
    ERROR:*) tc_problem "tdc preflight: ${COMPOSE_INFO#ERROR: }"; exit 1 ;;
esac

# Свободное место на разделе docker'а. Исчерпание диска на агенте выглядит как
# падение тестов: контейнер БД умирает с "No space left on device" в initdb, а
# наверх приходит лишь "dependency failed to start" (поймано на dev-стенде).
DOCKER_ROOT="$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || echo /var/lib/docker)"
FREE_MB="$(df -Pm "$DOCKER_ROOT" 2>/dev/null | awk 'NR==2 {print $4}' || true)"
if [ -n "${FREE_MB:-}" ] && [ "$FREE_MB" -lt "${TDC_MIN_FREE_MB:-5120}" ]; then
    tc_problem "tdc preflight: на $DOCKER_ROOT свободно ${FREE_MB} МБ (нужно минимум ${TDC_MIN_FREE_MB:-5120})"
    exit 1
fi

echo "tdc-runner: slot=$SLOT repo=$REPO build_id=$BUILD_ID out=$OUT"
echo "  $("$PY" --version 2>&1) | $(docker --version) | compose $COMPOSE_INFO"
echo "  свободно на $DOCKER_ROOT: ${FREE_MB:-?} МБ"

ARGS=(run --mode ci --repo "$REPO" --slot "$SLOT" --out "$OUT" --build-id "$BUILD_ID")
if [ -n "${TDC_ARTIFACTS:-}" ] && [ -d "${TDC_ARTIFACTS}" ]; then
    ARGS+=(--artifacts "$TDC_ARTIFACTS")
fi
if [ -n "${TDC_SECRETS:-}" ] && [ -d "${TDC_SECRETS}" ]; then
    ARGS+=(--secrets "$TDC_SECRETS")
fi
for p in ${TDC_REGISTRY_PREFIXES:-}; do
    ARGS+=(--registry-prefix "$p")
done
if [ -n "${TDC_EXTRA_ARGS:-}" ]; then
    # осознанное word-splitting: TDC_EXTRA_ARGS — список аргументов
    # shellcheck disable=SC2086
    set -- ${TDC_EXTRA_ARGS}
    ARGS+=("$@")
fi

exec env PYTHONPATH="$SELF" "$PY" -m tdc "${ARGS[@]}"
