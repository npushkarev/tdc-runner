"""Data model and contract constants for the test_docker_config runner (IN-662).

Contract source: IN-662 ticket + schema draft (test_cfg_schema_draft.md).
Python 3.8+, stdlib only.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# --- Slot dictionary: legacy .nupkg axis, do not invent a second one ---
OSES = ("lin", "win")
ARCHES = ("x64", "arm", "arm64")
XML_OS_MAP = {"linux": "lin", "windows": "win"}  # test_cfg.xml -> canonical

TRIGGER_CLASSES = ("post_commit",)  # v1
CONFIG_DIR_ROOT = "test_docker_config"
CONFIG_NAME_RE = r"^[a-z0-9_]+$"
# Имя секрета = имя файла в каталоге секретов, поэтому без путей и точек
SECRET_NAME_RE = r"^[a-z0-9_]+$"
COMPOSE_FILE_NAME = "docker-compose.yml"
ENV_DEFAULT_NAME = ".env.default"
# Локальные переопределения разработчика: читаются только в режиме local
# и не коммитятся (их место — в .gitignore тестируемого репозитория).
ENV_LOCAL_NAME = ".env.local"
TEST_CFG_NAME = "test_cfg.xml"

# In-container mount points (linux v1); reach services via env vars.
TEST_INPUT_MOUNT = "/test/input"
TEST_OUTPUT_MOUNT = "/test/output"
TEST_SECRETS_MOUNT = "/test/secrets"
RESERVED_MOUNT_PREFIX = "/test"

# .env.default may not define names with these prefixes (harness/compose control).
RESERVED_ENV_PREFIXES = ("COMPOSE_", "DOCKER_", "TEST_", "BUILD_", "VCS_")
# The only variables the harness injects into every service environment.
INJECTED_ENV_NAMES = (
    "TEST_INPUT", "TEST_OUTPUT", "TEST_OS", "TEST_ARCH",
    "TEST_CONFIG_NAME", "BUILD_NUMBER", "VCS_REVISION",
)

# Closed capability dictionary. class: "slot" = checked once per build,
# absence = build failure; "config" = known optional, absence = visible skip.
CAPABILITIES = {
    "docker": "slot",
    "docker-compose": "slot",
    "qemu-user-static": "config",
}

# Registry prefixes allowed in image references (extend via CLI/env).
DEFAULT_REGISTRY_PREFIXES = ("proget.inc.elara.local/",)

# Compose service keys a user file may contain (normalized form, §3.5).
ALLOWED_SERVICE_KEYS = {
    "image", "command", "entrypoint", "environment", "env_file",
    "depends_on", "healthcheck", "expose", "working_dir", "user",
    "networks", "volumes",
}
# Container label marking everything we start (orphan sweep key).
HARNESS_LABEL = "tc.in662"

# Capabilities a config may ask back after cap_drop: ALL. Closed dictionary:
# enough for images that set up their own data dir on first start (postgres
# initdb, mysql, rabbitmq), nothing that grants host reach.
ALLOWED_CAP_ADD = ("CHOWN", "DAC_OVERRIDE", "FOWNER", "FSETID", "KILL",
                   "SETGID", "SETUID", "NET_BIND_SERVICE")

# Report types are an OPEN dictionary (ticket p.4): known values below drive
# import/statistics, anything else is published as an artifact with a warning.
CONTAINER_TEST_SUITE_TYPES = ("tests", "coverage", "static_analysis",
                              "snapshots", "custom")
REPORT_FORMATS = ("junit", "trx", "cobertura", "raw")
INFRA_REPORT_DIR = "_infra"


@dataclass(frozen=True)
class Slot:
    os: str    # lin | win
    arch: str  # x64 | arm | arm64

    def __str__(self):
        return "%s-%s" % (self.os, self.arch)


@dataclass
class Capability:
    name: str
    min_version: Optional[str] = None


@dataclass
class InputSpec:
    kind: str          # "artifact" | "source"
    path: str          # glob, relative to the kind's root
    dest: str          # subpath inside TEST_INPUT_MOUNT
    optional: bool = False
    slot_filter: bool = True  # artifacts only: filter matches by slot tokens


@dataclass
class ReportSpec:
    type: str          # tests | coverage | static_analysis | custom
    format: str        # junit | trx | cobertura | raw
    path: str          # glob relative to TEST_OUTPUT_MOUNT
    optional: bool = False


@dataclass
class OutputArtifactSpec:
    path: str
    optional: bool = False


@dataclass
class SecretSpec:
    name: str                       # имя файла в каталоге секретов
    services: List[str] = field(default_factory=list)  # пусто = только главный


@dataclass
class Execution:
    main_service: str
    timeout_minutes: int


@dataclass
class TestConfig:
    name: str                       # directory name
    dir: Path                       # config directory
    description: str = ""
    oses: List[str] = field(default_factory=list)    # canonical: lin/win
    arches: List[str] = field(default_factory=list)  # x64/arm/arm64
    requires: List[Capability] = field(default_factory=list)
    inputs: List[InputSpec] = field(default_factory=list)
    reports: List[ReportSpec] = field(default_factory=list)
    out_artifacts: List[OutputArtifactSpec] = field(default_factory=list)
    execution: Optional[Execution] = None
    # service name -> capabilities added back after cap_drop: ALL (ALLOWED_CAP_ADD)
    cap_add: Dict[str, List[str]] = field(default_factory=dict)
    secrets: List[SecretSpec] = field(default_factory=list)
    # non-fatal findings from parsing (open dictionaries); load_config surfaces them
    warnings: List["ValidationIssue"] = field(default_factory=list)

    def matches_slot(self, slot: Slot) -> bool:
        return slot.os in self.oses and slot.arch in self.arches


@dataclass
class ValidationIssue:
    severity: str   # "error" | "warning"
    code: str       # short machine code, e.g. "compose.build_forbidden"
    message: str

    def __str__(self):
        return "[%s] %s: %s" % (self.severity, self.code, self.message)


class ConfigError(Exception):
    """Fatal config problem; carries the issue list."""
    def __init__(self, issues):
        self.issues = list(issues)
        super().__init__("; ".join(str(i) for i in self.issues))


@dataclass
class Limits:
    pids: int = 512
    memory: str = "2g"
    cpus: str = "2"


# Run statuses
PASSED, FAILED, SKIPPED, ERROR = "passed", "failed", "skipped", "error"


@dataclass
class RunResult:
    config_name: str
    status: str                      # passed | failed | skipped | error
    details: str = ""
    issues: List[ValidationIssue] = field(default_factory=list)


@dataclass
class RunContext:
    mode: str                        # "ci" | "local"
    slot: Slot
    repo_root: Path
    artifacts_root: Optional[Path]   # downloaded artifact tree (None = no artifacts)
    output_root: Path                # where reports/<config>/... land
    build_id: str = "local"
    ci_env: Dict[str, str] = field(default_factory=dict)
    registry_prefixes: Tuple[str, ...] = DEFAULT_REGISTRY_PREFIXES
    limits: Limits = field(default_factory=Limits)
    compose_bin: Tuple[str, ...] = ("docker", "compose")
    docker_bin: Tuple[str, ...] = ("docker",)
    dry_run: bool = False            # validate + stage + generate, no docker calls
    # каталог с файлами-секретами, выложенный отдельным шагом билда
    secrets_dir: Optional[Path] = None

    def project_name(self, config_name: str) -> str:
        prefix = "tc%s" % self.build_id if self.mode == "ci" else "tdc-%s" % self.repo_root.name
        return ("%s-%s" % (prefix, config_name)).lower().replace("_", "-")
