# Живой пример: OpenIde

Интеграционные тесты `SCADA/elara_openide_backend`, набор на PostgreSQL.
Прогнано на dev-стенде 5 августа 2026. Готовый профиль лежит в
[profiles/elara_openide_backend](../profiles/elara_openide_backend/).

## Было

Тесты запускались руками, по инструкции в Confluence: поставить Docker
Desktop, скопировать `.env`, вручную выгрузить сертификат прокси, поправить
подсети. Команда внутри контейнера:

```
dotnet test --filter "Category=Integration&DbProvider=Npgsql" --no-build -c Release
```

Ни `--logger`, ни `--results-directory`, ни `--collect`. Томов под отчёты в
compose тоже нет. Результаты оставались внутри контейнера и пропадали вместе с
ним. В CI не запускалось.

## Стало

Три файла в репозитории. В коде тестов ноль изменений.

| Что поменяли в их compose | Зачем |
|---|---|
| `build:` заменён на `image:` | тестовая машина не собирает образы и не получает исходники |
| убран `container_name` | два прогона одновременно не уживутся |
| убран `restart: always` | не поднимать упавшую базу бесконечно |
| добавлены три ключа к команде | без них отчёты не выходят наружу |
| добавлен `<privileges>` для базы | под снятыми правами postgres не стартует |

Ключи, ради которых всё затевалось:

```
--logger "trx;LogFileName=integration.trx"
--collect:"XPlat Code Coverage"
--results-directory /test/output/results
```

## Результат

```
##teamcity[importData type='mstest' path='.../tests/results/integration.trx']
##teamcity[buildStatisticValue key='CodeCoverageL' value='5.53']   # 238/4307
postgres_integration: passed (main service exit code 0)
```

Семь тестов, все прошли. После прогона на машине ни контейнеров, ни томов.

Покрытие считается только по слоям Infrastructure и Application. Без фильтра в
знаменатель попадали все связанные сборки и выходило 4.44% от 7447 строк.

## Пять граблей, которые встретятся и вам

1. **`dotnet test` без пути к проекту** берёт `.slnx` из рабочего каталога.
   Результат зависит от того, что лежит в образе. Указывайте проект явно.
2. **VSTest пишет отчёт о покрытии дважды**: в `results/<guid>/` и копией в
   каталог вложений. Маска `results/**` заберёт оба, цифры удвоятся. Нужна
   `results/*/…`.
3. **`--collect` работает даже при `PrivateAssets="all"`** у
   `coverlet.collector`. Проверено.
4. **`.env` может быть запечён в бинарники** через
   `CopyToOutputDirectory=Always`. Это второй канал конфигурации помимо
   compose. Настоящий пароль туда класть нельзя, он уедет в артефакт сборки.
5. **Базе надо вернуть права**, иначе `failed switching to 'postgres'`.

## Что не вошло

Второй набор, тесты веб-слоя, тянет `Docker.DotNet` и создаёт контейнеры через
Docker API. Такие контейнеры не принадлежат прогону и остаются на машине.
В первый этап не входит.
