# Как это выглядело на настоящем .NET-проекте

Разбор одного случая: интеграционные тесты `SCADA/elara_openide_backend`,
набор на PostgreSQL. Ниже факты, а не план. Прогнано на dev-стенде 4 августа
2026 года.

**Короткий ответ.** Понадобилось добавить три файла. В них перенесли их же
обвязку, убрали запрещённое и дописали ключи выгрузки отчётов. В коде тестов
ноль изменений.

---

## Как было

Тесты запускались руками, с машины разработчика под Windows, по инструкции в
Confluence. Перед первым запуском нужно было:

1. поставить Docker Desktop;
2. скопировать `.env.example` в `.env`;
3. вручную экспортировать корневой сертификат прокси из оснастки MMC и положить
   его в корень решения;
4. поправить подсети в настройках Docker Engine, потому что дефолтные
   пересекаются с офисной сетью.

Команда внутри контейнера была такая:

```
dotnet test --filter "Category=Integration&DbProvider=Npgsql" --no-build -c Release
```

Обратите внимание, чего в ней нет: `--logger`, `--results-directory`,
`--collect`. Томов под отчёты в compose тоже не было. **Результаты оставались
внутри контейнера и пропадали вместе с ним.** Оставался только код возврата.
Упало или нет, без имени упавшего теста.

В CI это не запускалось вообще.

Плюс сам `docker-compose.yml` собирал тестовый образ на лету:

```yaml
services:
  tests:
    build:
      context: .                     # ← весь репозиторий уезжает в образ
      dockerfile: ./tests/…/postgres.Dockerfile
    container_name: openide-…-tests  # ← два запуска сразу не уживутся
  postgres:
    restart: always                  # ← упавшую базу поднимает бесконечно
```

## Что изменили

**В коде тестов ничего.** Ни одной строки.

Добавили каталог из трёх файлов:

```
test_docker_config/post_commit/postgres_integration/
    docker-compose.yml
    .env.default
    test_cfg.xml
```

### `docker-compose.yml`

От оригинального отличается четырьмя местами. `your-feed` надо заменить на
имя реального фида ProGet:

```yaml
services:
  tests:
    # было build:, стало готовый образ из отдельной конфигурации сборки
    image: proget.inc.elara.local/your-feed/openide-postgres-integration-tests:1.0.0
    depends_on:
      postgres:
        condition: service_healthy     # ждём готовности базы, а не старта
    environment:
      - POSTGRES_USER                  # имя без значения = взять из .env.default
      - POSTGRES_PASSWORD
      - POSTGRES_HOST=postgres         # к соседу по имени сервиса, не localhost
      - POSTGRES_PORT=5432
      - READ_DB
      - WRITE_DB
    command:
      - dotnet
      - test
      # путь к проекту указан явно: иначе цель берётся из .slnx в /app
      - ./tests/Elara.OpenIde.Backend.Infrastructure.IntegrationTests/Elara.OpenIde.Backend.Infrastructure.IntegrationTests.csproj
      - --filter
      - Category=Integration&DbProvider=Npgsql
      - --no-build
      - -c
      - Release
      # ↓ вот эти три ключа и есть всё, ради чего затевалось
      - --logger
      - trx;LogFileName=integration.trx
      - --collect:XPlat Code Coverage
      - --results-directory
      - /test/output/results

  postgres:
    image: proget.inc.elara.local/main/library/postgres:18.1
    environment:
      - POSTGRES_USER
      - POSTGRES_PASSWORD
    volumes:
      - postgres-test-data:/var/lib/postgresql
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "${POSTGRES_USER}", "-d", "postgres"]
      interval: 5s
      timeout: 3s
      retries: 5
      start_period: 10s

volumes:
  postgres-test-data:
```

Убрано: `build:`, `container_name`, `restart: always`.
Добавлено: готовый образ и ключи выгрузки отчётов.

Двух вещей в этом файле нет, и это нормально. Каталог `/test/output`
монтирует сама система, писать его в compose не надо. Файл `.env.default`
она же читает и передаёт compose, поэтому переменные без значения берут
значения оттуда.

### `.env.default`

```
POSTGRES_USER=test
POSTGRES_PASSWORD=test
READ_DB=openide_read
WRITE_DB=openide
```

Из восьми переменных их `.env.example` осталось четыре: `POSTGRES_HOST`,
`POSTGRES_PORT`, `BACKEND_HOST` и `BACKEND_PORT` выводятся из самого compose:
хост это имя сервиса, порт и так объявлен. Заодно исчез класс ошибок: в их
`.env.example` стоит `POSTGRES_HOST=localhost`, а инструкция утверждает, что по
умолчанию там `postgres`. Кто выполнит инструкцию буквально, получит тесты,
которые не найдут базу.

### `test_cfg.xml`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<test_cfg version="1">
  <meta>
    <description>OpenIde backend: интеграционные тесты слоя Infrastructure на PostgreSQL</description>
  </meta>

  <environment>
    <os>linux</os>
    <arch>x64</arch>
  </environment>

  <outputs>
    <report type="tests" format="trx" path="results/**/*.trx"/>
    <!-- VSTest кладёт копию отчёта в каталог вложений, поэтому глоб ровно
         на один уровень: иначе покрытие посчитается дважды -->
    <report type="coverage" format="cobertura"
            path="results/*/coverage.cobertura.xml" optional="true"/>
    <!-- Snapshooter пишет .mismatch только при расхождении снапшотов -->
    <report type="snapshots" format="raw" path="snapshots/**" optional="true"/>
    <artifact path="logs/**" optional="true"/>
  </outputs>

  <!-- postgres при первом старте создаёт свой каталог данных и переключает
       пользователя: под снятыми привилегиями не поднимется -->
  <privileges>
    <service name="postgres" cap_add="CHOWN DAC_OVERRIDE FOWNER SETGID SETUID"/>
  </privileges>

  <execution>
    <main_service>tests</main_service>
    <timeout_minutes>20</timeout_minutes>
  </execution>
</test_cfg>
```

## Что получилось

Прогон на dev-стенде (Astra 1.8, docker 28.3.3, python 3.11.2):

```
tdc: compose = …/vendor/compose/docker-compose-linux-x86_64 (vendored)
##teamcity[importData type='mstest' path='…/reports/postgres_integration/tests/results/integration.trx']
##teamcity[buildStatisticValue key='CodeCoverageAbsLCovered' value='331']
##teamcity[buildStatisticValue key='CodeCoverageAbsLTotal' value='7447']
##teamcity[buildStatisticValue key='CodeCoverageL' value='4.44']
##teamcity[buildStatisticValue key='CodeCoverageAbsBCovered' value='43']
##teamcity[buildStatisticValue key='CodeCoverageAbsBTotal' value='2248']
##teamcity[buildStatisticValue key='CodeCoverageB' value='1.91']
postgres_integration: passed (main service exit code 0)
```

На диске:

```
reports/postgres_integration/tests/results/integration.trx
reports/postgres_integration/coverage/results/<guid>/coverage.cobertura.xml
reports/postgres_integration/_infra/compose-logs.txt
reports/postgres_integration/_infra/compose-ps.txt
```

После прогона на машине не осталось ни контейнеров, ни томов.

Покрытие 4.44% это не поломка, а арифметика. Интеграционные тесты слоя
Infrastructure считаются против всех связанных продуктовых сборок. Нужна
осмысленная цифра: сужайте область сбора. Это настройка проекта.

## Пять вещей, на которые наткнулись

**1. `dotnet test` без явной цели уходит по всему решению.** Если в рабочем
каталоге лежит `.slnx`, команда без пути возьмёт решение целиком. У OpenIde это
сработало, но результат зависит от того, что лежит рядом. Указывайте путь к
csproj явно.

**2. VSTest пишет отчёт о покрытии дважды.** Один раз в `results/<guid>/`,
второй копией в каталог вложений. Маска `results/**` заберёт оба файла, и цифры
удвоятся. Поэтому в примере выше стоит `results/*/…`.

**3. `--collect:"XPlat Code Coverage"` работает даже при
`PrivateAssets="all"` у `coverlet.collector`.** Проверено: коллектор доезжает
до опубликованного бандла.

**4. `.env` может быть запечён в бинарники.** В их тест-проекте стоит
`<None Update=".env"><CopyToOutputDirectory>Always</CopyToOutputDirectory></None>`,
то есть файл копируется в `bin/` и читается кодом тестов. Это второй канал
конфигурации помимо compose. Он проигрывает переменным окружения сервиса,
поэтому наш `.env` его перекрывает. Настоящий пароль туда класть нельзя: он
уедет в опубликованный артефакт сборки.

**5. Базе нужно вернуть права.** Под снятыми привилегиями postgres падает с
`failed switching to 'postgres'`. Пяти из словаря хватает и для 18.1, проверено.

## Что делать в вашем .NET-проекте

- [ ] тестовый образ собирается отдельно и лежит в ProGet с конкретным тегом
- [ ] в `command` добавлены `--logger`, `--collect`, `--results-directory /test/output/results`
- [ ] путь к тест-проекту в `dotnet test` указан явно
- [ ] маска покрытия `results/*/coverage.cobertura.xml`, а не `**`
- [ ] к соседним сервисам обращаемся по имени из compose, не по `localhost`
- [ ] у зависимых сервисов есть `healthcheck`, у тестов `depends_on` с `service_healthy`
- [ ] переменные из `.env.default` перечислены в `environment:` сервиса
- [ ] базе выданы капабилити через `<privileges>`
- [ ] настоящих паролей нет ни в `.env.default`, ни в запечённом `.env`
- [ ] `python3 -m tdc validate` даёт `OK`, `./run_local.sh` проходит локально

## Что осталось нерешённым

У OpenIde есть второй набор: тесты веб-слоя. Они тянут `Docker.DotNet` и
создают контейнеры программно, через Docker API. Такие контейнеры не
принадлежат нашему прогону. Их не видит ни `down -v`, ни уборка по метке, и они
остаются на машине навсегда. В первый этап такие наборы не входят. Если это ваш
случай, приходите, будем решать отдельно.
