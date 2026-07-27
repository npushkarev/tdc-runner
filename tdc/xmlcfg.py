"""Parse and validate test_cfg.xml -> model.TestConfig.

parse_test_cfg(path: Path) -> TestConfig
    - xml.etree.ElementTree, no external deps.
    - Root <test_cfg version="1">; unknown version -> ConfigError.
    - <environment>: <os> single value (linux|windows -> XML_OS_MAP),
      <arch> space-separated list from ARCHES; unknown value -> error.
      <requires><capability name= [min_version=]/>: name must be in
      CAPABILITIES (closed dictionary) else error "capability.unknown".
    - <inputs>: <artifact|source path= dest= [optional=] [slot_filter=]/>.
      kind "artifact"/"source" from the tag name. Booleans: "true"/"false".
    - <outputs>: <report type= format= path= [optional=]/> and
      <artifact path= [optional=]/>. type in CONTAINER_TEST_SUITE_TYPES,
      format in REPORT_FORMATS. At least one report type="tests" required
      -> error "outputs.no_tests_report" otherwise.
    - <execution>: <main_service> (non-empty) and <timeout_minutes> (int > 0)
      both required.
    - Collect ALL problems into ConfigError(issues) rather than failing on
      the first one. name/dir fields are filled by the caller (runner).
"""
import xml.etree.ElementTree as ET
from pathlib import Path

from .model import (
    ARCHES, CAPABILITIES, CONTAINER_TEST_SUITE_TYPES, REPORT_FORMATS,
    XML_OS_MAP, Capability, ConfigError, Execution, InputSpec,
    OutputArtifactSpec, ReportSpec, TestConfig, ValidationIssue,
)

SCHEMA_VERSION = "1"


def _err(issues, code, message):
    issues.append(ValidationIssue("error", code, message))


def _parse_bool(value, default, issues, code, where):
    if value is None:
        return default
    if value == "true":
        return True
    if value == "false":
        return False
    _err(issues, code, "%s: expected 'true'/'false', got %r" % (where, value))
    return default


def _parse_environment(env, cfg, issues):
    os_text = (env.findtext("os") or "").strip()
    if not os_text:
        _err(issues, "environment.os_missing", "<os> is required")
    elif os_text not in XML_OS_MAP:
        _err(issues, "environment.os_unknown",
             "unknown os %r (allowed: %s)" % (os_text, ", ".join(sorted(XML_OS_MAP))))
    else:
        cfg.oses.append(XML_OS_MAP[os_text])

    arch_text = (env.findtext("arch") or "").strip()
    if not arch_text:
        _err(issues, "environment.arch_missing", "<arch> is required")
    else:
        for token in arch_text.split():
            if token not in ARCHES:
                _err(issues, "environment.arch_unknown",
                     "unknown arch %r (allowed: %s)" % (token, ", ".join(ARCHES)))
            else:
                cfg.arches.append(token)

    requires = env.find("requires")
    if requires is not None:
        for cap in requires.findall("capability"):
            name = cap.get("name")
            if not name:
                _err(issues, "capability.name_missing", "<capability> requires name=")
            elif name not in CAPABILITIES:
                _err(issues, "capability.unknown",
                     "unknown capability %r (closed dictionary: %s)"
                     % (name, ", ".join(sorted(CAPABILITIES))))
            else:
                cfg.requires.append(Capability(name, cap.get("min_version")))


def _parse_inputs(inputs, cfg, issues):
    for el in inputs:
        if el.tag not in ("artifact", "source"):
            _err(issues, "inputs.unknown_element", "unexpected <%s> in <inputs>" % el.tag)
            continue
        path, dest = el.get("path"), el.get("dest")
        if not path or not dest:
            _err(issues, "inputs.attr_missing", "<%s> requires path= and dest=" % el.tag)
            continue
        where = "<%s path=%r>" % (el.tag, path)
        cfg.inputs.append(InputSpec(
            kind=el.tag, path=path, dest=dest,
            optional=_parse_bool(el.get("optional"), False, issues, "inputs.bad_bool", where),
            slot_filter=_parse_bool(el.get("slot_filter"), True, issues, "inputs.bad_bool", where),
        ))


def _parse_outputs(outputs, cfg, issues):
    for el in outputs:
        if el.tag == "report":
            rtype, rformat, rpath = el.get("type"), el.get("format"), el.get("path")
            ok = True
            if not rtype or not rformat or not rpath:
                _err(issues, "outputs.attr_missing", "<report> requires type=, format= and path=")
                ok = False
            if rtype and rtype not in CONTAINER_TEST_SUITE_TYPES:
                _err(issues, "outputs.report_type",
                     "unknown report type %r (allowed: %s)"
                     % (rtype, ", ".join(CONTAINER_TEST_SUITE_TYPES)))
                ok = False
            if rformat and rformat not in REPORT_FORMATS:
                _err(issues, "outputs.report_format",
                     "unknown report format %r (allowed: %s)"
                     % (rformat, ", ".join(REPORT_FORMATS)))
                ok = False
            if not ok:
                continue
            optional = _parse_bool(el.get("optional"), False, issues,
                                   "outputs.bad_bool", "<report path=%r>" % rpath)
            cfg.reports.append(ReportSpec(rtype, rformat, rpath, optional))
        elif el.tag == "artifact":
            path = el.get("path")
            if not path:
                _err(issues, "outputs.attr_missing", "<artifact> requires path=")
                continue
            optional = _parse_bool(el.get("optional"), False, issues,
                                   "outputs.bad_bool", "<artifact path=%r>" % path)
            cfg.out_artifacts.append(OutputArtifactSpec(path, optional))
        else:
            _err(issues, "outputs.unknown_element", "unexpected <%s> in <outputs>" % el.tag)


def _parse_execution(execution, cfg, issues):
    main_service = (execution.findtext("main_service") or "").strip()
    if not main_service:
        _err(issues, "execution.main_service", "<main_service> is required and must be non-empty")

    timeout_text = (execution.findtext("timeout_minutes") or "").strip()
    timeout = None
    try:
        timeout = int(timeout_text)
    except ValueError:
        _err(issues, "execution.timeout",
             "<timeout_minutes> must be an integer, got %r" % timeout_text)
    if timeout is not None and timeout <= 0:
        _err(issues, "execution.timeout", "<timeout_minutes> must be > 0, got %d" % timeout)
        timeout = None

    if main_service and timeout is not None:
        cfg.execution = Execution(main_service, timeout)


def parse_test_cfg(path):
    path = Path(path)
    try:
        root = ET.parse(str(path)).getroot()
    except (ET.ParseError, OSError) as exc:
        raise ConfigError([ValidationIssue(
            "error", "xml.malformed", "%s: %s" % (path, exc))])

    issues = []
    if root.tag != "test_cfg":
        raise ConfigError([ValidationIssue(
            "error", "xml.root", "root element must be <test_cfg>, got <%s>" % root.tag)])
    if root.get("version") != SCHEMA_VERSION:
        _err(issues, "cfg.version",
             "unknown version %r (supported: %s)" % (root.get("version"), SCHEMA_VERSION))

    cfg = TestConfig(name="", dir=path.parent)

    meta = root.find("meta")
    if meta is not None:
        cfg.description = (meta.findtext("description") or "").strip()

    env = root.find("environment")
    if env is None:
        _err(issues, "environment.missing", "<environment> is required")
    else:
        _parse_environment(env, cfg, issues)

    inputs = root.find("inputs")
    if inputs is not None:
        _parse_inputs(inputs, cfg, issues)

    outputs = root.find("outputs")
    if outputs is not None:
        _parse_outputs(outputs, cfg, issues)
    if not any(r.type == "tests" for r in cfg.reports):
        _err(issues, "outputs.no_tests_report",
             'at least one <report type="tests"> is required')

    execution = root.find("execution")
    if execution is None:
        _err(issues, "execution.missing", "<execution> is required")
    else:
        _parse_execution(execution, cfg, issues)

    if issues:
        raise ConfigError(issues)
    return cfg
