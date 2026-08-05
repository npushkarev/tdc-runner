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

| Кому | Что |
|---|---|
| разработчику компонента | **[docs/HOWTO.md](docs/HOWTO.md)** |
| ему же, живой пример | [docs/case_dotnet_openide.md](docs/case_dotnet_openide.md) |
| принимающему решение | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| при работе с контрактом | `templates/test_cfg.xsd` |

Показать, как это работает, ничего не настраивая:
`./smoke/demo_from_template.sh`. Он копирует шаблон в пустой репозиторий,
меняет одну строку и запускает боевой пускалкой.

`templates/` это то, что копируют себе команды. `profiles/` это готовые
профили, подготовленные для конкретных репозиториев. Схемы и генераторы в `schemes/`, черновики в `drafts/`.

## Тесты

```sh
python3 -m unittest discover -s tests
```

Интеграционные кейсы (реальный `docker compose config`, без контейнеров)
включаются автоматически при наличии docker.

## Compose

Ставить compose на машину не нужно: пин версии лежит в `vendor/compose/`
и выбирается автоматически (`tdc/composebin.py`). Системный плагин это
запасной путь. `TDC_COMPOSE_BIN` перебивает выбор. Подробности и как добавить
другую архитектуру: `vendor/compose/README.md`.

## Смоук на реальном docker

Юниты не поднимают контейнеров. Сквозной прогон это `smoke/`. Он собирает
образ-заглушку из postgres в ProGet (сеть наружу не нужна), гоняет профиль,
копирующий пилотный MVP-профиль OpenIde, и проверяет критерии готовности.

```sh
./smoke/run_smoke.sh              # ожидается PASSED: trx + cobertura + чистый агент
./smoke/run_smoke.sh --negative   # ожидается FAILED: без <privileges> postgres не стартует
```

Предусловия проверяет сам скрипт: python3, docker-демон, compose.
`SMOKE_BASE_IMAGE` подменяет базовый образ, если ProGet недоступен
(например на маке: `SMOKE_BASE_IMAGE=postgres:17-alpine`).
