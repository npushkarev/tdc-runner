#!/bin/sh
# Содержимое образа-заглушки: это НЕ пускалка, а то, что выполняется
# внутри контейнера вместо настоящих тестов (см. smoke/Dockerfile).
# Делает то же, что сделал бы `dotnet test` у OpenIde: ходит в базу, создаёт
# свои БД (имитация EF-миграций) и выкладывает trx + cobertura в $TEST_OUTPUT.
set -e
echo "stub-tests: TEST_OUTPUT=$TEST_OUTPUT TEST_OS=$TEST_OS TEST_ARCH=$TEST_ARCH"
echo "stub-tests: config=$TEST_CONFIG_NAME build=$BUILD_NUMBER"

export PGPASSWORD="$POSTGRES_PASSWORD"
PSQL="psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER"
$PSQL -d postgres -c "CREATE DATABASE $WRITE_DB" >/dev/null
$PSQL -d postgres -c "CREATE DATABASE $READ_DB" >/dev/null
$PSQL -d "$WRITE_DB" -c 'create table t(id int); insert into t values (1);' >/dev/null
$PSQL -d "$WRITE_DB" -tAc 'select count(*) from t'
echo "stub-tests: postgres reachable, databases created"

RESULTS="$TEST_OUTPUT/results"
mkdir -p "$RESULTS"

cat > "$RESULTS/integration.trx" <<'TRX'
<?xml version="1.0" encoding="UTF-8"?>
<TestRun xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010">
  <ResultSummary outcome="Completed">
    <Counters total="2" executed="2" passed="2" failed="0"/>
  </ResultSummary>
</TestRun>
TRX

# Раскладка как у настоящего VSTest: отчёт в results/<guid>/, плюс его копия
# в каталоге вложений. Дубль намеренный — ядро обязано посчитать покрытие один
# раз, а не удвоить (проверено на реальном прогоне dotnet с coverlet 8.0.1).
COV_XML='<?xml version="1.0" encoding="UTF-8"?>
<coverage line-rate="0.75" branch-rate="0.5"
          lines-covered="150" lines-valid="200"
          branches-covered="20" branches-valid="40"/>'
mkdir -p "$RESULTS/3f8b599e-ed2b-42e6-b428-f10187562474" \
         "$RESULTS/_stub_2026_08_03/In/stub"
echo "$COV_XML" > "$RESULTS/3f8b599e-ed2b-42e6-b428-f10187562474/coverage.cobertura.xml"
echo "$COV_XML" > "$RESULTS/_stub_2026_08_03/In/stub/coverage.cobertura.xml"

echo "stub-tests: wrote $(find "$RESULTS" -type f | wc -l) file(s)"
