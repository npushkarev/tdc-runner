#!/usr/bin/env bash
#
#   ./run_local.sh <имя набора> [--repo DIR] [--slot lin-x64]
#                  [--artifacts DIR] [--secrets DIR] [--out DIR]
#                  [--dry-run] [-- <прочие аргументы tdc>]
#
# Запускает один набор тестов у вас на машине. Тем же кодом, что и сервер:
# отличается только режим, локально гоняется один набор по имени, а на сервере
# все наборы репозитория, подходящие слоту.
#
# Что делает, по шагам:
#   1. читает три файла набора из
#      <repo>/test_docker_config/post_commit/<имя набора>/
#   2. проверяет их: манифест, имена переменных, compose по белому списку.
#      Ошибка тут останавливает всё до запуска контейнеров
#   3. чистит рабочий каталог прошлого прогона, готовит каталоги для входных
#      файлов и отчётов
#   4. накладывает на compose ограничения: лимиты, снятие прав, отдельная сеть,
#      уникальное имя проекта, метки для уборки
#   5. поднимает сервисы, ждёт готовности зависимых по healthcheck
#   6. запускает главный сервис и ждёт его завершения, но не дольше таймаута
#   7. забирает отчёты и логи контейнеров. Всегда, даже если прогон упал
#   8. сносит контейнеры, тома и сеть
#
# Умолчания: репозиторий это корень текущего git-репозитория, слот lin-x64,
# отчёты в <repo>/.tdc-out.
#
# Ключи нужны не всем: --artifacts если в манифесте есть <inputs> с
# <artifact>, --secrets если есть <secrets>, --dry-run чтобы проверить всю
# подготовку, не запуская контейнеры.
#
# Код возврата: 0 тесты прошли, иначе нет.
set -euo pipefail

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    # только строки с вызовом, подробности читаются в самом файле
    sed -n '3,5p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
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
