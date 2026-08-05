# Образ для показа. Внутри лежит заглушка, которая притворяется dotnet:
# принимает аргументы из шаблона и пишет такие же отчёты, как настоящий прогон.
# Благодаря этому шаблон запускается без правки команды, меняется только image.
ARG BASE_IMAGE=proget.inc.elara.local/main/library/postgres:18.1
FROM ${BASE_IMAGE}
COPY dotnet /usr/local/bin/dotnet
RUN chmod +x /usr/local/bin/dotnet
ENTRYPOINT []
