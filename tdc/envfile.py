"""'.env.default' parsing, reserved-name policy, merge, rendering.

parse_env_file(path: Path) -> Dict[str, str]
    Strict parser: UTF-8 text, one VAR=value per line; blank lines and
    lines starting with '#' ignored; VAR must match [A-Za-z_][A-Za-z0-9_]*.
    No shell substitution, no quotes stripping beyond a single matching pair
    of double or single quotes around the whole value. Malformed line ->
    ConfigError with code "env.malformed_line" (collect all).

check_reserved(env: Dict[str,str]) -> List[ValidationIssue]
    Error "env.reserved_name" for every key starting with any of
    RESERVED_ENV_PREFIXES.

merge_env(defaults: Dict, ci: Dict) -> Dict
    CI always wins; result is a new dict.

render_env_file(env: Dict) -> str
    Deterministic (sorted) VAR=value lines, trailing newline. Values are
    written as-is (values must not contain newlines -> ValueError).
"""
import re

from .model import ConfigError, ValidationIssue, RESERVED_ENV_PREFIXES

_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def parse_env_file(path):
    env = {}
    issues = []
    for lineno, raw in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE_RE.match(line)
        if m is None:
            issues.append(ValidationIssue(
                "error", "env.malformed_line",
                "%s:%d: not a VAR=value line: %r" % (path.name, lineno, raw)))
            continue
        name, value = m.group(1), m.group(2)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        env[name] = value
    if issues:
        raise ConfigError(issues)
    return env


def check_reserved(env):
    issues = []
    for name in sorted(env):
        for prefix in RESERVED_ENV_PREFIXES:
            if name.startswith(prefix):
                issues.append(ValidationIssue(
                    "error", "env.reserved_name",
                    "%s: prefix %s* is reserved for the harness" % (name, prefix)))
                break
    return issues


def merge_env(defaults, ci):
    merged = dict(defaults)
    merged.update(ci)
    return merged


def render_env_file(env):
    lines = []
    for name in sorted(env):
        value = env[name]
        if "\n" in value or "\r" in value:
            raise ValueError("value of %s contains a newline" % name)
        lines.append("%s=%s\n" % (name, value))
    return "".join(lines)
