#!/usr/bin/env bash
# Показ для разработчиков: весь путь от шаблона до зелёного прогона.
#
#   ./smoke/demo_from_template.sh [dotnet|cpp]
#
# Что происходит: создаётся пустой «репозиторий разработчика», в него копируется
# шаблон, заменяется одна строка (образ), и всё это запускается БОЕВОЙ пускалкой,
# той самой, которой будет запускать TeamCity.
#
# Образ для показа притворяется dotnet: принимает те же аргументы, что стоят в
# шаблоне, и пишет такие же отчёты. Поэтому команда в шаблоне не меняется.
set -euo pipefail

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SELF/.." && pwd)"
STACK="${1:-dotnet}"
BASE_IMAGE="${DEMO_BASE_IMAGE:-proget.inc.elara.local/main/library/postgres:18.1}"
DEMO_IMAGE="proget.inc.elara.local/demo/component-tests:1.0.0"

step() { echo; echo "======== $1"; }
fail() { echo "ПОКАЗ: не получилось. $1" >&2; exit 1; }

[ -d "$ROOT/templates/$STACK" ] || fail "нет шаблона для стека '$STACK'"
docker info >/dev/null 2>&1 || fail "docker не запущен"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
REPO="$WORK/my_component"
mkdir -p "$REPO"

step "1. У разработчика есть репозиторий. Тестов в нём мы не трогаем"
echo "   $REPO"

step "2. Копируем шаблон ($STACK)"
cp -r "$ROOT/templates/$STACK/test_docker_config" "$REPO/"
find "$REPO" -type f | sed "s|$REPO/|   |"

step "3. Смотрим, что надо заменить"
grep -rn "ЗАМЕНИТЬ" "$REPO/test_docker_config" | sed "s|$REPO/|   |" || true

step "4. Заменяем образ на свой"
echo "   в жизни здесь будет образ с вашими тестами из ProGet"
echo "   для показа собираем заглушку, которая ведёт себя как dotnet"
docker build -q --build-arg "BASE_IMAGE=$BASE_IMAGE" \
    -t "$DEMO_IMAGE" "$SELF/demo_image" >/dev/null
CFG="$REPO/test_docker_config/post_commit/integration"
sed -i.bak "s|image: .*|image: $DEMO_IMAGE|" "$CFG/docker-compose.yml"
rm -f "$CFG/docker-compose.yml.bak"
echo "   строка image заменена, больше в шаблоне ничего не трогали"
grep -n "image:" "$CFG/docker-compose.yml" | sed 's/^/   /'

step "5. Проверяем файлы. Контейнеры не поднимаются"
(cd "$ROOT" && python3 -m tdc validate --repo "$REPO") | sed 's/^/   /'

step "6. Прогон боевой пускалкой, той же, что запустит TeamCity"
OUT="$WORK/out"
set +e
TDC_REPO="$REPO" TDC_SLOT=lin-x64 TDC_OUT="$OUT" TDC_BUILD_ID=demo1 \
    "$ROOT/ci/run_tests.sh"
RC=$?
set -e

step "7. Что осталось на диске"
find "$OUT/reports" -type f 2>/dev/null | sed "s|$OUT/reports/|   |" || echo "   ничего"

step "8. Машина чистая"
echo "   контейнеров с меткой: $(docker ps -aq --filter label=tc.in662 | wc -l | tr -d ' ')"
echo "   томов с меткой:       $(docker volume ls -q --filter label=tc.in662 | wc -l | tr -d ' ')"

echo
if [ "$RC" = "0" ]; then
    echo "ПОКАЗ: готово. Разработчику нужно повторить шаги 2, 4 и 6 у себя."
else
    echo "ПОКАЗ: прогон вернул $RC. Смотрите вывод выше."
fi
docker rmi "$DEMO_IMAGE" >/dev/null 2>&1 || true
exit "$RC"
