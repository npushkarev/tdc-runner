#!/usr/bin/env bash
# Смоук ядра tdc на реальном docker: собирает образ-заглушку, гоняет профиль,
# проверяет критерии готовности MVP и печатает вердикт. Ничего не тянет из сети,
# кроме базового образа postgres из ProGet.
#
#   ./smoke/run_smoke.sh              обычный прогон (ожидается PASSED)
#   ./smoke/run_smoke.sh --negative   без <privileges> (ожидается FAILED)
#
# Переменные:
#   SMOKE_BASE_IMAGE  база для заглушки (по умолчанию postgres:18.1 из ProGet)
#   SMOKE_OUT         куда класть отчёты (по умолчанию smoke/.out)
set -euo pipefail

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SELF/.." && pwd)"
BASE_IMAGE="${SMOKE_BASE_IMAGE:-proget.inc.elara.local/main/library/postgres:18.1}"
STUB_IMAGE="proget.inc.elara.local/test-images/tdc-smoke-tests:1.0.0"
OUT="${SMOKE_OUT:-$SELF/.out}"
NEGATIVE=0
[ "${1:-}" = "--negative" ] && NEGATIVE=1

fail() { echo "SMOKE: ПРОВАЛ — $1" >&2; exit 1; }

echo "== [1/5] предусловия"
command -v python3 >/dev/null || fail "python3 не найден"
docker info >/dev/null 2>&1 || fail "docker-демон недоступен"
COMPOSE_INFO="$(cd "$ROOT" && python3 -c 'from tdc import composebin
b, s = composebin.resolve()
print(("%s | %s" % (" ".join(b), s)) if b else "ERROR: %s" % s)' 2>&1)"
case "$COMPOSE_INFO" in ERROR:*) fail "${COMPOSE_INFO#ERROR: }" ;; esac
echo "  $(python3 --version 2>&1) | $(docker --version)"
echo "  compose: $COMPOSE_INFO"

echo "== [2/5] образ-заглушка из $BASE_IMAGE"
docker build --build-arg "BASE_IMAGE=$BASE_IMAGE" -t "$STUB_IMAGE" "$SELF" >/dev/null
echo "  собран $STUB_IMAGE"
# Профиль намеренно один в один с production и жёстко называет postgres из ProGet.
# Если смоук гоняют с другой базой (например на маке, где ProGet недоступен) —
# вешаем локальный алиас, чтобы не расходиться с профилем.
PG_IMAGE="proget.inc.elara.local/main/library/postgres:18.1"
if [ "$BASE_IMAGE" != "$PG_IMAGE" ]; then
    docker tag "$BASE_IMAGE" "$PG_IMAGE"
    echo "  алиас $BASE_IMAGE -> $PG_IMAGE (только локально, не пушится)"
fi

REPO="$SELF/repo"
CFG="$REPO/test_docker_config/post_commit/postgres_integration/test_cfg.xml"
RESTORE=""
if [ "$NEGATIVE" = "1" ]; then
    RESTORE="$(mktemp)"; cp "$CFG" "$RESTORE"
    trap 'cp "$RESTORE" "$CFG"; rm -f "$RESTORE"' EXIT
    python3 - "$CFG" <<'PY'
import re, sys
p = sys.argv[1]
t = open(p, encoding='utf-8').read()
open(p, 'w', encoding='utf-8').write(
    re.sub(r'\n  <!-- postgres initdb.*?</privileges>\n', '\n', t, flags=re.S))
PY
    echo "  негативный режим: <privileges> временно убран"
fi

echo "== [3/5] валидация профиля"
python3 -m tdc validate --repo "$REPO"

echo "== [4/5] прогон"
rm -rf "$OUT"
set +e
(cd "$ROOT" && python3 -m tdc run --repo "$REPO" --slot lin-x64 --mode local \
     --config postgres_integration --out "$OUT" --build-id smoke) 2>&1 | tee "$SELF/.last.log"
RC=${PIPESTATUS[0]}
set -e

echo "== [5/5] проверка критериев"
R="$OUT/reports/postgres_integration"
LEFT_C="$(docker ps -aq --filter label=tc.in662 | wc -l | tr -d ' ')"
LEFT_V="$(docker volume ls -q --filter label=tc.in662 | wc -l | tr -d ' ')"
[ "$LEFT_C" = "0" ] || fail "после прогона осталось контейнеров: $LEFT_C"
[ "$LEFT_V" = "0" ] || fail "после прогона осталось томов: $LEFT_V"
[ -s "$R/_infra/compose-logs.txt" ] || fail "не собран _infra/compose-logs.txt"

if [ "$NEGATIVE" = "1" ]; then
    [ "$RC" != "0" ] || fail "негативный прогон обязан падать, а вернул 0"
    grep -q "operation not permitted" "$R/_infra/compose-logs.txt" \
        || echo "SMOKE: предупреждение — ожидал 'operation not permitted' в логах"
    echo "SMOKE: ОК (негативный) — без <privileges> прогон падает, уборка чистая"
    exit 0
fi

[ "$RC" = "0" ] || fail "прогон вернул $RC (лог: $SELF/.last.log)"
ls "$R"/tests/results/*.trx >/dev/null 2>&1 || fail "не собран trx"
ls "$R"/coverage/results/*.cobertura.xml >/dev/null 2>&1 || fail "не собран cobertura"
grep -q "importData type='mstest'" "$SELF/.last.log" || fail "нет importData для trx"
grep -q "CodeCoverageL" "$SELF/.last.log" || fail "нет статистики покрытия"
echo "SMOKE: ОК — отчёты собраны, импорт и статистика отправлены, агент чист"
echo "  отчёты: $R"
