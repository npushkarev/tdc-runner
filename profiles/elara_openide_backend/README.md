# Профиль для SCADA/elara_openide_backend

Три файла для набора интеграционных тестов слоя Infrastructure (PostgreSQL).
Прогнаны на dev-стенде 4 августа 2026: тесты проходят, отчёты собираются.

## Что положить и куда

Скопировать каталог в **корень** репозитория:

```sh
cp -r profiles/elara_openide_backend/test_docker_config <checkout>/
```

Получится:

```
elara_openide_backend/
    test_docker_config/post_commit/postgres_integration/
        docker-compose.yml
        .env.default
        test_cfg.xml
```

Больше в репозитории ничего не меняется. Код тестов, `.csproj`, существующие
`*-compose.yaml` в корне не трогаем.

## Три улучшения относительно того, что прогонялось на стенде

Профиль не копия проверенного. В него вложено то, что мы выяснили за эти дни.

**1. Цель `dotnet test` указана явно.** Раньше команда шла без пути, и цель
бралась из `.slnx` в `/app`. Работало, но результат зависел от содержимого
рабочего каталога образа. Теперь путь к тест-проекту прописан.

**2. Покрытие считается только по слоям, которые эти тесты проверяют.** На
стенде выходило 4.44%, потому что в знаменатель попадали все связанные сборки.
Добавлен фильтр области сбора (`Include=[…Infrastructure]*,[…Application]*`).
Проверено на стенде 5 августа: стало 238 из 4307, то есть 5.53%.

**3. Из манифеста убраны строки, которые ничего не делали.** Отчёт о снапшотах
и каталог логов выглядели как собираемая диагностика, но Snapshooter пишет
файлы внутрь образа, а `logs/` никто не наполняет. В файле объяснено, что
нужно сделать, чтобы они появились по-настоящему.

## Что заменить перед коммитом

| Где | Что |
|---|---|
| `docker-compose.yml`, `image:` | `your-feed` → фид ProGet, куда публикуется образ с тестами |

Всё остальное рабочее.

## Откуда берётся образ с тестами

Собирается вашим же `tests/Elara.OpenIde.Backend.Infrastructure.IntegrationTests/postgres.Dockerfile`
и публикуется в ProGet отдельной конфигурацией сборки. Проверено на стенде:

```sh
docker build \
  -f tests/Elara.OpenIde.Backend.Infrastructure.IntegrationTests/postgres.Dockerfile \
  -t proget.inc.elara.local/your-feed/openide-postgres-integration-tests:1.0.0 .
```

Сборке нужен `*.crt` в корне checkout'а: его забирает `COPY *.crt` из вашего
Dockerfile. Функционально сертификат не понадобился (пакеты тянутся с
внутреннего фида), но без файла сборка падает на самом `COPY`.

## Как проверить у себя

```sh
cd tdc-runner
python3 -m tdc validate --repo <checkout>                 # без контейнеров
./run_local.sh postgres_integration --repo <checkout>     # полный прогон
```

Отчёты лягут в `<checkout>/.tdc-out/`. Добавьте его в `.gitignore`.

## Что было на стенде

```
##teamcity[importData type='mstest' path='…/tests/results/integration.trx']
##teamcity[buildStatisticValue key='CodeCoverageL' value='5.53']   # 238/4307
##teamcity[buildStatisticValue key='CodeCoverageB' value='1.38']   # 18/1300
postgres_integration: passed (main service exit code 0)
```

После прогона на машине не осталось ни контейнеров, ни томов.

Покрытие низкое закономерно: тесты слоя Infrastructure считаются против всех
связанных продуктовых сборок. Нужна осмысленная цифра: сужайте область сбора,
это настройка проекта.

## Чего этот профиль не покрывает

Второй набор, тесты веб-слоя, сюда не входит. Он тянет `Docker.DotNet` и
создаёт контейнеры программно через Docker API. Такие контейнеры не
принадлежат прогону, их не убирает ни `down -v`, ни уборка по метке. Решаем
отдельно.

Подробный разбор всего случая: [docs/case_dotnet_openide.md](../../docs/case_dotnet_openide.md).
