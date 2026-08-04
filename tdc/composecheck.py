"""Compose normalization + whitelist validation (§3.5).

list_compose_files(config_dir: Path) -> List[ValidationIssue]
    Any file matching (docker-)?compose*.y*ml other than exactly
    COMPOSE_FILE_NAME -> error "compose.extra_file".

normalize_compose(config_dir: Path, env_file: Path, compose_bin) -> dict
    Run: compose_bin + ("-f", COMPOSE_FILE_NAME, "--env-file", str(env_file),
    "config", "--format", "json") with cwd=config_dir; parse stdout as JSON.
    Non-zero exit -> ConfigError "compose.invalid" with stderr tail.

check_compose(doc, main_service, registry_prefixes, config_dir=None)
    Whitelist over the NORMALIZED document; see the schema draft §3.5 for
    the rule-by-rule rationale.  Returns ALL issues.
"""
import json
import os
import re
import subprocess
from pathlib import Path

from .model import (
    ALLOWED_SERVICE_KEYS, COMPOSE_FILE_NAME, RESERVED_MOUNT_PREFIX,
    ConfigError, ValidationIssue,
)

_COMPOSE_NAME_RE = re.compile(r"^(docker-)?compose.*\.ya?ml$")
_DOCKER_SOCK = "/var/run/docker.sock"

# Keys outside ALLOWED_SERVICE_KEYS that get a specific code instead of the
# generic compose.key_forbidden.
_FORBIDDEN_KEY_CODES = {
    "build": "compose.build_forbidden",
    "ports": "compose.ports_forbidden",
    "privileged": "compose.privilege_forbidden",
    "cap_add": "compose.privilege_forbidden",
    "devices": "compose.privilege_forbidden",
    "security_opt": "compose.privilege_forbidden",
    "sysctls": "compose.privilege_forbidden",
    "network_mode": "compose.host_namespace",
    "pid": "compose.host_namespace",
    "ipc": "compose.host_namespace",
    "uts": "compose.host_namespace",
    "userns_mode": "compose.host_namespace",
    "cgroup_parent": "compose.host_namespace",
    "extends": "compose.extends_forbidden",
    "volumes_from": "compose.volumes_from_forbidden",
    "secrets": "compose.secrets_forbidden",
    "configs": "compose.secrets_forbidden",
    "logging": "compose.logging_forbidden",
    "dns": "compose.dns_forbidden",
    "extra_hosts": "compose.dns_forbidden",
    "restart": "compose.restart_forbidden",
    "container_name": "compose.container_name_forbidden",
}


def _err(code, message):
    return ValidationIssue("error", code, message)


def list_compose_files(config_dir):
    config_dir = Path(config_dir)
    issues = []
    if not config_dir.is_dir():
        return [_err("config.missing_dir",
                     "каталог конфигурации не найден: %s" % config_dir)]
    for entry in sorted(config_dir.iterdir()):
        if entry.name == COMPOSE_FILE_NAME or not entry.is_file():
            continue
        if _COMPOSE_NAME_RE.match(entry.name):
            issues.append(_err(
                "compose.extra_file",
                "extra compose file '%s' in %s: only %s is read by the "
                "harness (compose would auto-merge it past the validator)"
                % (entry.name, config_dir, COMPOSE_FILE_NAME)))
    return issues


def normalize_compose(config_dir, env_file, compose_bin):
    cmd = list(compose_bin) + [
        "-f", COMPOSE_FILE_NAME, "--env-file", str(env_file),
        "config", "--format", "json",
    ]
    proc = subprocess.run(
        cmd, cwd=str(config_dir),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-15:])
        raise ConfigError([_err(
            "compose.invalid",
            "'%s' failed (exit %d): %s" % (" ".join(cmd), proc.returncode, tail))])
    try:
        return json.loads(proc.stdout)
    except ValueError:
        raise ConfigError([_err(
            "compose.invalid",
            "unparseable JSON from '%s'" % " ".join(cmd))])


def _check_image(svc_name, image, registry_prefixes):
    if not image:
        return [_err("compose.image_required",
                     "service '%s': image is required" % svc_name)]
    issues = []
    if not any(image.startswith(p) for p in registry_prefixes):
        issues.append(_err(
            "compose.image_registry",
            "service '%s': image '%s' is not on an allowed registry (%s)"
            % (svc_name, image, ", ".join(registry_prefixes))))
    # tag = after the last ':' of the last path segment, digest cut off
    last = image.split("@", 1)[0].rsplit("/", 1)[-1]
    tag = last.rsplit(":", 1)[1] if ":" in last else ""
    if not tag or tag == "latest":
        issues.append(_err(
            "compose.image_tag",
            "service '%s': image '%s' must carry an immutable tag "
            "(missing or 'latest')" % (svc_name, image)))
    return issues


def _check_volumes(svc_name, volumes):
    issues = []
    for vol in volumes:
        if not isinstance(vol, dict):
            continue  # normalized output always uses the long form
        source = vol.get("source") or ""
        target = vol.get("target") or ""
        if vol.get("type") != "volume":
            if _DOCKER_SOCK in (source, target):
                msg = ("service '%s': mounting the docker socket %s is "
                       "forbidden" % (svc_name, _DOCKER_SOCK))
            else:
                msg = ("service '%s': mount '%s' -> '%s' (type %s) is "
                       "forbidden, only named volumes are allowed"
                       % (svc_name, source, target, vol.get("type")))
            issues.append(_err("compose.bind_mount", msg))
        if target == RESERVED_MOUNT_PREFIX or \
                target.startswith(RESERVED_MOUNT_PREFIX + "/"):
            issues.append(_err(
                "compose.reserved_mount",
                "service '%s': volume target '%s' is under harness-reserved "
                "'%s'" % (svc_name, target, RESERVED_MOUNT_PREFIX)))
    return issues


def _check_env_files(svc_name, entries, config_dir):
    issues = []
    for entry in entries:
        path = entry.get("path") if isinstance(entry, dict) else entry
        if not isinstance(path, str):
            continue
        foreign = os.path.basename(path) != ".env"
        if not foreign and config_dir is not None and os.path.isabs(path):
            foreign = Path(path).resolve().parent != Path(config_dir).resolve()
        if foreign:
            issues.append(_err(
                "compose.env_file_foreign",
                "service '%s': env_file '%s' is not the config-local .env"
                % (svc_name, path)))
    return issues


def check_compose(doc, main_service, registry_prefixes, config_dir=None):
    issues = []
    services = doc.get("services") or {}
    # Empty main_service = caller has no parsed execution block (broken
    # test_cfg.xml); the xml error is already reported, don't add noise.
    if main_service and main_service not in services:
        issues.append(_err(
            "compose.main_service",
            "main_service '%s' not found among services (%s)"
            % (main_service, ", ".join(sorted(services)) or "none")))
    for svc_name in sorted(services):
        svc = services[svc_name] or {}
        for key in sorted(svc):
            code = _FORBIDDEN_KEY_CODES.get(key)
            if code is not None:
                issues.append(_err(code, "service '%s': '%s' is forbidden"
                                   % (svc_name, key)))
            elif key not in ALLOWED_SERVICE_KEYS:
                issues.append(_err(
                    "compose.key_forbidden",
                    "service '%s': key '%s' is not allowed" % (svc_name, key)))
        issues.extend(_check_image(svc_name, svc.get("image"),
                                   registry_prefixes))
        issues.extend(_check_volumes(svc_name, svc.get("volumes") or ()))
        issues.extend(_check_env_files(svc_name, svc.get("env_file") or (),
                                       config_dir))
    top_volumes = doc.get("volumes") or {}
    for vol_name in sorted(top_volumes):
        spec = top_volumes[vol_name]
        if isinstance(spec, dict) and \
                (spec.get("driver_opts") or spec.get("external")):
            issues.append(_err(
                "compose.volume_opts",
                "volume '%s': driver_opts/external are forbidden" % vol_name))
    return issues
