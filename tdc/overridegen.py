"""Harness override generation.

generate_override(doc: dict, cfg: TestConfig, ctx: RunContext,
                  staging_dir: Path, output_dir: Path) -> dict
    Build an override document (returned as a plain dict; JSON-serializable --
    JSON is valid YAML, the file is written with json.dumps) that, for EVERY
    service in the normalized doc:
      - volumes: staging_dir -> TEST_INPUT_MOUNT (read_only True),
        output_dir -> TEST_OUTPUT_MOUNT (rw). Long form entries
        {type: bind, source, target, read_only}.
        (These binds are HARNESS-generated; user binds remain forbidden.)
      - environment: INJECTED_ENV_NAMES with values from ctx/cfg:
        TEST_INPUT/TEST_OUTPUT = mount points, TEST_OS/TEST_ARCH = slot,
        TEST_CONFIG_NAME = cfg.name, BUILD_NUMBER/VCS_REVISION from
        ctx.ci_env (empty string when absent).
      - limits: pids_limit, mem_limit, memswap_limit(=mem_limit), cpus,
        cap_drop: [ALL], security_opt: [no-new-privileges:true]
        from ctx.limits.
      - cap_add: only what cfg.cap_add declares for that service (parsed from
        <privileges>, closed dictionary) — images like postgres cannot run
        initdb under a bare cap_drop: ALL.
      - labels: {HARNESS_LABEL: "1"}.
      - restart: "no" for every service except cfg.execution.main_service
        keeps whatever compose default is (do NOT add restart to main).
    Plus a default network override marking the default network
    internal: true (networks: {default: {internal: true}}).

write_override(override: dict, path: Path) -> Path
    json.dumps(indent=2) -> path; returns path.
"""
import json
from pathlib import Path

from .model import (
    HARNESS_LABEL, INJECTED_ENV_NAMES, TEST_INPUT_MOUNT, TEST_OUTPUT_MOUNT, TEST_SECRETS_MOUNT,
    RunContext, TestConfig,  # noqa: F401  (part of the documented signatures)
)


def injected_env(config_name, slot, ci_env):
    """The exact env set injected into every service; keys == INJECTED_ENV_NAMES.

    Shared with runner (.env merge) and cli (validate-time interpolation) so
    the three places can never drift apart.
    """
    values = {
        "TEST_INPUT": TEST_INPUT_MOUNT,
        "TEST_OUTPUT": TEST_OUTPUT_MOUNT,
        "TEST_OS": slot.os,
        "TEST_ARCH": slot.arch,
        "TEST_CONFIG_NAME": config_name,
        "BUILD_NUMBER": ci_env.get("BUILD_NUMBER", ""),
        "VCS_REVISION": ci_env.get("VCS_REVISION", ""),
    }
    return dict((name, values[name]) for name in INJECTED_ENV_NAMES)


def _secret_services(cfg):
    """Сервис -> нужен ли ему каталог секретов. Пусто в services= = только главный."""
    main = cfg.execution.main_service if cfg.execution else None
    needed = set()
    for spec in cfg.secrets:
        needed.update(spec.services or ([main] if main else []))
    return needed


def generate_override(doc, cfg, ctx, staging_dir, output_dir):
    environment = injected_env(cfg.name, ctx.slot, ctx.ci_env)
    main_service = cfg.execution.main_service if cfg.execution else None
    secret_services = _secret_services(cfg) if ctx.secrets_dir else set()
    services = {}
    for name in (doc.get("services") or {}):
        service = {
            "volumes": [
                {"type": "bind", "source": str(staging_dir),
                 "target": TEST_INPUT_MOUNT, "read_only": True},
                {"type": "bind", "source": str(output_dir),
                 "target": TEST_OUTPUT_MOUNT, "read_only": False},
            ],
            "environment": dict(environment),
            "pids_limit": ctx.limits.pids,
            "mem_limit": ctx.limits.memory,
            # memswap == mem: the limit is total, i.e. zero extra swap
            "memswap_limit": ctx.limits.memory,
            "cpus": ctx.limits.cpus,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "labels": {HARNESS_LABEL: "1"},
        }
        # Секреты видит только тот, кто их запросил: остальным сервисам каталог
        # не монтируется вовсе, чтобы пароль не расползался по обвязке.
        if name in secret_services:
            service["volumes"].append(
                {"type": "bind", "source": str(ctx.secrets_dir),
                 "target": TEST_SECRETS_MOUNT, "read_only": True})
        if name != main_service:
            service["restart"] = "no"
        # declared in test_cfg.xml, validated against the closed dictionary
        caps = cfg.cap_add.get(name)
        if caps:
            service["cap_add"] = list(caps)
        services[name] = service
    return {
        "services": services,
        "networks": {"default": {"internal": True}},
    }


def write_override(override, path):
    path = Path(path)
    path.write_text(json.dumps(override, indent=2) + "\n", encoding="utf-8")
    return path
