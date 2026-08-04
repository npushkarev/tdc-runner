# Образ-заглушка тестов. База — тот же postgres, что и в обвязке: в нём есть psql,
# он уже лежит в ProGet, и на закрытой сети ничего тянуть не надо.
ARG BASE_IMAGE=proget.inc.elara.local/main/library/postgres:18.1
FROM ${BASE_IMAGE}
COPY stub_entrypoint.sh /usr/local/bin/stub_entrypoint.sh
RUN chmod +x /usr/local/bin/stub_entrypoint.sh
ENTRYPOINT []
CMD ["/usr/local/bin/stub_entrypoint.sh"]
