# Запуск интеграционных тестов на сборочной машине

Эта папка добавляет одно: интеграционные тесты можно запускать не только руками
на ноутбуке, но и автоматически после сборки, с выгрузкой отчётов.

Больше в репозитории ничего не меняется. Код тестов, `.csproj` и существующие
`postgres-integration-tests-compose.yaml` и `backend-integration-tests-compose.yaml`
остаются как были.

## Что здесь лежит

```
test_docker_config/post_commit/postgres_integration/
    docker-compose.yml   тот же набор, что у вас, с правками под запуск на агенте
    .env.default         значения по умолчанию, без секретов
    test_cfg.xml         что запускать и какие отчёты забрать
```

Набор один: интеграционные тесты слоя Infrastructure на PostgreSQL. Семь тестов.

## Зачем это, если compose у вас уже есть

Ваш текущий набор работает, но отчёты остаются внутри контейнера и умирают
вместе с ним. `dotnet test` вызывается без `--logger` и `--results-directory`,
томов под результаты нет. Наружу выходит только код возврата.

Здесь эти ключи добавлены, а `test_cfg.xml` описывает, какие файлы забрать после
прогона. На выходе получаются trx и покрытие в TeamCity.

## Чем отличается compose

| Было | Стало | Почему |
|---|---|---|
| `build:` | `image:` | сборочная машина не собирает образы и не получает исходники, образ публикуется в ProGet отдельной конфигурацией |
| `container_name:` | убран | два прогона одновременно не уживутся с фиксированным именем |
| `restart: always` | убран | под тестовый прогон это бесконечный подъём упавшей базы |
| `CMD` без ключей | `command:` с `--logger` и `--results-directory` | иначе отчётов нет |

Ещё в compose явно указан путь к `.csproj`. Без него `dotnet test` берёт `.slnx`
из `/app`, и результат зависит от того, что лежит в рабочем каталоге образа.

## Как проверить самому

Нужен docker и python 3.8 или новее.

```sh
git clone https://github.com/npushkarev/tdc-runner
cd tdc-runner
python3 -m tdc validate --repo <путь к checkout openide>      # без контейнеров
./run_local.sh postgres_integration --repo <путь к checkout>  # полный прогон
```

Отчёты лягут в `<checkout>/.tdc-out/`. Добавьте `.tdc-out/` в `.gitignore`.

Перед полным прогоном нужен образ с тестами. Собирается вашим же Dockerfile:

```sh
docker build \
  -f tests/Elara.OpenIde.Backend.Infrastructure.IntegrationTests/postgres.Dockerfile \
  -t proget.inc.elara.local/<фид>/openide-postgres-integration-tests:1.0.0 .
```

Сборке нужен любой `*.crt` в корне checkout: его забирает `COPY *.crt` из
вашего Dockerfile.

## Что получилось на нашем стенде

```
##teamcity[importData type='mstest' path='.../results/integration.trx']
##teamcity[buildStatisticValue key='CodeCoverageL' value='5.53']   # 238/4307
##teamcity[buildStatisticValue key='CodeCoverageB' value='1.38']   # 18/1300
postgres_integration: passed (main service exit code 0)
```

После прогона на машине не осталось ни контейнеров, ни томов.

Покрытие низкое закономерно: тесты одного слоя считаются против связанных
сборок. Область сбора уже сужена фильтром до Infrastructure и Application. Если
цифра должна быть другой, это настройка проекта, скажите какая.

## Что нужно заменить перед мержем

`your-feed` в `docker-compose.yml` на фид ProGet, куда будет публиковаться образ
с тестами. Фид заводим мы.

## Два вопроса к вам

1. В `Web.IntegrationTests` смонтирован `/var/run/docker.sock`, и там же лежит
   `Docker.DotNet`. Тесты создают контейнеры сами? Такие контейнеры не
   принадлежат прогону, и уборка их не видит. Пока этот набор не подключаем.
2. Планируете ли уходить от `build:` в существующих compose-файлах, или они
   остаются для локальной работы?

## Второй набор

Рядом может лежать `all_tests`: всё решение, кроме веб-слоя. Он требует правки
вашего `postgres.Dockerfile` (сборка решения вместо одного проекта) и пока не
прогонялся. В первый заход его не берём.
