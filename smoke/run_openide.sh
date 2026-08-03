#!/usr/bin/env bash
# Прогон НАСТОЯЩИХ интеграционных тестов OpenIde (postgres-набор) через ядро tdc.
# Только для dev-стенда: нужны bitbucket.inc.elara.local, proget.inc.elara.local
# и внутренний NuGet-фид. Образ собирается локально и в ProGet не публикуется —
# для проверки достаточно локального тега.
#
#   ./smoke/run_openide.sh /path/to/elara_openide_backend
#
# Предварительно (шаг 3 инструкции Голубевой, pageId=119770782):
#   в корне checkout'а должен лежать iw-proxy-root.crt — его забирает COPY *.crt.
set -euo pipefail

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SELF/.." && pwd)"
REPO="${1:-}"
OUT="${OPENIDE_OUT:-$SELF/.out-openide}"
IMAGE="proget.inc.elara.local/test-images/openide-postgres-integration-tests:1.0.0"
PROFILE="$SELF/openide_profile/test_docker_config"

fail() { echo "OPENIDE: ПРОВАЛ — $1" >&2; exit 1; }

[ -n "$REPO" ] || fail "укажи путь к checkout'у elara_openide_backend"
[ -d "$REPO/tests/Elara.OpenIde.Backend.Infrastructure.IntegrationTests" ] \
    || fail "$REPO не похож на elara_openide_backend"
[ -n "$(find "$REPO" -maxdepth 1 -name '*.crt')" ] \
    || fail "в корне репо нет *.crt — Dockerfile делает COPY *.crt (см. инструкцию Голубевой)"

echo "== [1/4] тестовый образ из postgres.Dockerfile"
docker build \
    -f "$REPO/tests/Elara.OpenIde.Backend.Infrastructure.IntegrationTests/postgres.Dockerfile" \
    -t "$IMAGE" "$REPO"
echo "  собран $IMAGE"

echo "== [2/4] профиль в checkout"
if [ -d "$PROFILE" ]; then
    cp -r "$PROFILE" "$REPO/"
    echo "  скопирован из $PROFILE"
else
    [ -d "$REPO/test_docker_config" ] \
        || fail "профиль не найден: положи test_docker_config/ в $REPO вручную"
    echo "  используется уже лежащий в репозитории"
fi

echo "== [3/4] валидация"
(cd "$ROOT" && python3 -m tdc validate --repo "$REPO")

echo "== [4/4] прогон"
rm -rf "$OUT"
set +e
(cd "$ROOT" && python3 -m tdc run --repo "$REPO" --slot lin-x64 --mode local \
     --config postgres_integration --out "$OUT" --build-id openide) 2>&1 \
     | tee "$SELF/.last-openide.log"
RC=${PIPESTATUS[0]}
set -e

R="$OUT/reports/postgres_integration"
echo
echo "== итог"
echo "  exit code: $RC"
echo "  trx:       $(find "$R/tests" -name '*.trx' 2>/dev/null | wc -l | tr -d ' ')"
echo "  cobertura: $(find "$R/coverage" -name '*.cobertura.xml' 2>/dev/null | wc -l | tr -d ' ')"
echo "  остатки:   контейнеров $(docker ps -aq --filter label=tc.in662 | wc -l | tr -d ' ')," \
     "томов $(docker volume ls -q --filter label=tc.in662 | wc -l | tr -d ' ')"
echo "  отчёты:    $R"
echo "  лог:       $SELF/.last-openide.log"
exit "$RC"
