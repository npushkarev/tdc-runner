#!/usr/bin/env bash
#
#   ./make_bundle.sh [выходной файл]        по умолчанию dist/tdc.pyz
#
# Собирает пускалку в ОДИН исполняемый файл. Нужен, когда отдаёшь тесты
# человеку, которому неоткуда клонировать этот репозиторий: закрытый контур,
# чужая команда, разовая проверка.
#
# Работает потому, что у пакета tdc нет зависимостей, только stdlib. Любой
# python 3.8 и новее запускает файл как есть:
#
#   python3 tdc.pyz validate --repo <checkout>
#   python3 tdc.pyz run --mode local --repo <checkout> --config <набор> \
#                       --slot lin-x64 --out <checkout>/.tdc-out
#
# Чего в файле НЕТ: вендорного compose из vendor/compose. Это отдельный бинарь
# на 60 МБ, класть его внутрь бессмысленно — из архива он всё равно не
# запустится. Если на машине нет плагина compose (так на агентах Astra),
# положи бинарь рядом и укажи путь:
#
#   TDC_COMPOSE_BIN=./docker-compose-linux-x86_64 python3 tdc.pyz ...
set -euo pipefail

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${1:-$SELF/dist/tdc.pyz}"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# зеркалим пакет без кэша интерпретатора: .pyc от другой версии python внутри
# архива не помогают, а размер удваивают
cp -R "$SELF/tdc" "$STAGE/tdc"
find "$STAGE/tdc" -name '__pycache__' -type d -exec rm -rf {} +

# точка входа архива: сам пакет запускается как tdc/__main__.py, но в zipapp
# корнем становится каталог, поэтому нужен свой запускающий файл
cat > "$STAGE/__main__.py" <<'PY'
import sys

from tdc.cli import main

sys.exit(main())
PY

mkdir -p "$(dirname "$OUT")"
python3 -m zipapp "$STAGE" -o "$OUT" -p "/usr/bin/env python3"
chmod +x "$OUT"

echo "собрано: $OUT ($(wc -c < "$OUT" | tr -d ' ') байт)"
echo "проверка: python3 $OUT validate --repo <checkout>"
