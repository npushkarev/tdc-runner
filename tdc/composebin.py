"""Which compose CLI to run.

The contract fixes ONE compose version everywhere (agents + local runner), so a
pinned binary ships in vendor/compose/ and wins over whatever the machine has.
Astra agents in particular have docker without the compose plugin.

Resolution order:
  1. $TDC_COMPOSE_BIN — space-separated override ("docker compose",
     "/opt/compose/docker-compose"); escape hatch, never second-guessed.
  2. vendor/compose/docker-compose-linux-<arch> — the pin, linux only.
  3. system `docker compose` plugin.
  -> None when nothing works; callers report that in their own words.

Python 3.8+, stdlib only.
"""
import os
import platform
import subprocess
from pathlib import Path

VENDOR_DIR = Path(__file__).resolve().parent.parent / "vendor" / "compose"
ENV_OVERRIDE = "TDC_COMPOSE_BIN"

# uname -m -> the arch token used in the vendored file names
ARCH_ALIASES = {
    "x86_64": "x86_64", "amd64": "x86_64",
    "aarch64": "aarch64", "arm64": "aarch64",
}


def _works(cmd):
    try:
        return subprocess.run(list(cmd) + ["version"],
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL).returncode == 0
    except OSError:
        return False


def vendored_path(system=None, machine=None):
    """Path of the pinned binary for this platform, or None if not shipped."""
    system = (system or platform.system()).lower()
    if system != "linux":
        return None
    arch = ARCH_ALIASES.get((machine or platform.machine()).lower())
    if arch is None:
        return None
    path = VENDOR_DIR / ("docker-compose-linux-%s" % arch)
    return path if path.is_file() and os.access(str(path), os.X_OK) else None


def resolve(env=None):
    """-> (compose_bin tuple, source label) or (None, reason)."""
    env = os.environ if env is None else env
    override = env.get(ENV_OVERRIDE)
    if override:
        return tuple(override.split()), ENV_OVERRIDE

    pinned = vendored_path()
    if pinned is not None and _works((str(pinned),)):
        return (str(pinned),), "vendored"

    if _works(("docker", "compose")):
        return ("docker", "compose"), "system plugin"

    if pinned is not None:
        return None, "vendored compose at %s is not runnable" % pinned
    return None, ("no compose v2: system plugin missing and nothing vendored "
                  "for %s/%s" % (platform.system(), platform.machine()))
