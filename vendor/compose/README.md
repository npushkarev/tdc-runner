# Пин Docker Compose

Контракт IN-662 требует **одной версии compose везде** — на TC-агентах, на
dev-стенде и у разработчика локально. Поэтому бинарь лежит здесь, а не ставится
на каждой машине руками: на Astra-стенде docker есть (28.3.3, astra build), а
плагина compose нет, и без пина «у меня работает» неизбежно.

| Файл | Версия | sha256 |
|---|---|---|
| `docker-compose-linux-x86_64` | v5.3.1 | `f9ebc6ebdb19d769b793c245a736caaeb198c62587f13b25c660c13b4987f959` |

Источник: `https://github.com/docker/compose/releases/download/v5.3.1/`,
контрольная сумма сверена с `.sha256` релиза при добавлении в репозиторий.

## Как это выбирается

`tdc/composebin.py`, порядок:

1. `$TDC_COMPOSE_BIN` — явный override, ничем не перебивается;
2. `vendor/compose/docker-compose-linux-<arch>` — этот пин (только linux);
3. системный плагин `docker compose` — запасной путь (так работает на маке,
   где linux-бинарь не подходит).

## Как добавить другую архитектуру

Для arm/arm64-агентов положить рядом файл с тем же именем и своим суффиксом —
код подхватит его сам, менять ничего не нужно:

```sh
V=v5.3.1
curl -sSLO https://github.com/docker/compose/releases/download/$V/docker-compose-linux-aarch64
curl -sSL  https://github.com/docker/compose/releases/download/$V/docker-compose-linux-aarch64.sha256 \
  | awk '{print $1"  docker-compose-linux-aarch64"}' | sha256sum -c -
chmod +x docker-compose-linux-aarch64
```

Имена архитектур в `ARCH_ALIASES`: `x86_64` (он же amd64), `aarch64` (он же arm64).
