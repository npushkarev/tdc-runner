# tdc-runner

Раннер/валидатор `test_docker_config/` (IN-662): исполняемое ядро шаблонной
TC-конфигурации запуска интеграционных тестов в docker-compose окружении,
заданном разработчиком. Один и тот же код гоняет тесты в CI и локально.

Python 3.8+, только stdlib. Требует docker + Compose v2 (`docker compose`).

## Использование

```sh
# проверить все конфигурации репозитория (без запуска)
python3 -m tdc validate --repo <repo_root>

# CI: все конфигурации слота
python3 -m tdc run --mode ci --repo <repo_root> --slot lin-x64 \
    --artifacts <artifact_tree> --out <reports_dir> --build-id <N>

# локально: одна конфигурация
python3 -m tdc run --mode local --repo <repo_root> --config <name> \
    --slot lin-x64 --artifacts <dir> --out <dir> [--dry-run]
```

## Документация

| Кому | Что читать |
|---|---|
| разработчику компонента | **[docs/HOWTO.md](docs/HOWTO.md)** — как подключить свои тесты: маршрут из четырёх шагов, готовые шаблоны в `templates/`, рецепты и разбор ошибок |
| тому, кто принимает решения | **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — устройство, обоснования, что уже проверено, границы и открытые вопросы |
| при работе с контрактом | `docs/test_cfg.xsd` — формат манифеста (документация; исполняемая валидация — код) |
| командам, чьи компоненты тестируются | **[docs/confluence_article.md](docs/confluence_article.md)** — статья для Confluence: требования к репозиторию, что запрещено, что вы получите |

Схемы — `docs/in662_*.png`, рядом лежат редактируемые `.excalidraw` и генераторы
(`diagen.py` + `make_diagrams.py` для архитектурных, `in662_howto_overview.py`
для обзорной).

## Тесты

```sh
python3 -m unittest discover -s tests
```

Интеграционные кейсы (реальный `docker compose config`, без контейнеров)
включаются автоматически при наличии docker.

## Compose

Ставить compose на машину не нужно: пин версии лежит в `vendor/compose/`
и выбирается автоматически (`tdc/composebin.py`), системный плагин —
запасной путь, `TDC_COMPOSE_BIN` — override. Подробности и как добавить
другую архитектуру — `vendor/compose/README.md`.

## Смоук на реальном docker

Юниты не поднимают контейнеров. Сквозной прогон — `smoke/`: собирает
образ-заглушку из postgres в ProGet (сеть наружу не нужна), гоняет профиль,
копирующий пилотный MVP-профиль OpenIde, и проверяет критерии готовности.

```sh
./smoke/run_smoke.sh              # ожидается PASSED: trx + cobertura + чистый агент
./smoke/run_smoke.sh --negative   # ожидается FAILED: без <privileges> postgres не стартует
```

Предусловия проверяет сам скрипт: python3, docker-демон, compose.
`SMOKE_BASE_IMAGE` подменяет базовый образ, если ProGet недоступен
(например на маке: `SMOKE_BASE_IMAGE=postgres:17-alpine`).
