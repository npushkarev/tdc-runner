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

Контракт репозитория (`test_docker_config/post_commit/<name>/` с
`docker-compose.yml` + `.env.default` + `test_cfg.xml`), белый список
compose-полей и регламент выходных артефактов — в
`docs/confluence_article_draft.md`; формат манифеста — `docs/test_cfg.xsd`
(документация; исполняемая валидация — код).

## Тесты

```sh
python3 -m unittest discover -s tests
```

Интеграционные кейсы (реальный `docker compose config`, без контейнеров)
включаются автоматически при наличии docker.
