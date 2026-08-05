# Образ с настоящими тестами для показа. Собирается так же, как это делают
# команды у себя: SDK-образ из внутреннего registry, сборка тест-проекта.
ARG BASE_IMAGE=proget.inc.elara.local/main/library/dotnet:0.5.0
FROM ${BASE_IMAGE}
WORKDIR /app
COPY . .
RUN dotnet build ./tests/My.Component.IntegrationTests/My.Component.IntegrationTests.csproj -c Release
