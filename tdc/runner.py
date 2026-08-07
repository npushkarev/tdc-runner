"""Orchestration: scan -> validate -> stage -> run -> collect.

Design for testability: all subprocess execution goes through an injectable
callable `execute(cmd: List[str], **kw) -> subprocess.CompletedProcess`
stored on the runner; unit tests replace it with a fake.

scan_configs(repo_root: Path, trigger="post_commit") -> List[Path]
    Sorted list of config dirs under repo_root/CONFIG_DIR_ROOT/<trigger>/*/
    that contain TEST_CFG_NAME. Directory names not matching CONFIG_NAME_RE
    -> ConfigError later in validate, still returned here.

load_config(config_dir: Path) -> Tuple[Optional[TestConfig], List[ValidationIssue]]
    - dir name vs CONFIG_NAME_RE ("config.bad_name");
    - required files present: COMPOSE_FILE_NAME, ENV_DEFAULT_NAME,
      TEST_CFG_NAME ("config.missing_file");
    - composecheck.list_compose_files;
    - xmlcfg.parse_test_cfg (catch ConfigError -> issues), fill name/dir.

run_config(cfg: TestConfig, ctx: RunContext, execute) -> RunResult
    Lifecycle per the contract (§3 steps 3.1-3.7):
      0. Снести work/ и reports/<cfg> прошлого прогона: иначе отчёты
         копятся и счётчики покрытия суммируются между запусками.
      1. envfile: parse .env.default, check_reserved, merge ci vars
         (TEST_* + BUILD_* injected values), render .env into a private
         WORK dir (ctx.output_root/"_work"/cfg.name), NOT into the checkout.
         Copy user compose file into work dir alongside .env? NO -- run
         compose with cwd=cfg.dir but --env-file pointing at the work .env
         and explicit -f paths, --project-directory cfg.dir.
      2. composecheck.normalize_compose + check_compose (+ per-spec
         staging.validate_input_spec). Any error issue -> RunResult ERROR
         without touching docker.
      3. staging.stage_inputs into work/staging; output dir work/output
         (mkdir, mode 0777 -- the container drops DAC_OVERRIDE and would not
         be able to write into a dir owned by the agent user);
         collisions/zero-match errors -> ERROR.
      4. overridegen.generate_override + write_override into work.
      5. If ctx.dry_run: return RunResult(PASSED, details="dry-run").
      6. compose CMD base: ctx.compose_bin + ("-p", project, "-f", user_file,
         "-f", override_file, "--env-file", work_env, "--project-directory",
         str(cfg.dir)).
         pull (no timeout enforcement here), up -d,
         then `docker wait <cid>` where cid = `compose ps -q main_service`;
         enforce cfg.execution.timeout_minutes via the execute() timeout
         parameter around `docker wait`; timeout -> FAILED "timeout".
         Exit code from docker wait stdout: 0 -> PASSED else FAILED.
      7. ALWAYS (finally): collect reports from work/output per cfg.reports
         (glob; missing non-optional -> issue + status ERROR unless already
         FAILED), copy into ctx.output_root/reports/<cfg.name>/<type>/;
         `compose logs --no-color -t` + `compose ps -a` into
         .../reports/<cfg.name>/_infra/; emit teamcity.import_data for
         junit ("junit") and trx ("mstest") reports; cobertura has no TC
         importer -> counters go out as build statistics;
         `compose down -v --remove-orphans`.
    Return RunResult.

sweep_orphans(execute, docker_bin) -> None
    docker ps -aq --filter label=HARNESS_LABEL -> docker rm -f;
    docker volume ls -q --filter label=... -> docker volume rm (ignore errors).

run_slot(ctx: RunContext, execute) -> List[RunResult]
    sweep_orphans; scan; for each config: load, slot-match
    (not cfg.matches_slot -> SKIPPED), capability classes (unknown ->
    validate error already; "config"-class caps assumed present in v1 --
    emit SKIPPED with details when we cannot verify: keep simple, treat all
    known config-class caps as present), teamcity suite open/close around
    run_config, aggregate.
"""
import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path
from xml.etree import ElementTree

from .model import (
    CONFIG_DIR_ROOT, CONFIG_NAME_RE, COMPOSE_FILE_NAME, ENV_DEFAULT_NAME,
    ENV_LOCAL_NAME, SECRET_NAME_RE,
    HARNESS_LABEL, INFRA_REPORT_DIR, TEST_CFG_NAME, ConfigError, RunResult,
    RunSummary, ValidationIssue, PASSED, FAILED, SKIPPED, ERROR,
)
from . import composecheck, envfile, overridegen, staging, teamcity, xmlcfg


def _has_errors(issues):
    return any(i.severity == "error" for i in issues)


def scan_configs(repo_root, trigger="post_commit"):
    root = Path(repo_root) / CONFIG_DIR_ROOT / trigger
    if not root.is_dir():
        return []
    return sorted(
        p for p in root.iterdir()
        if p.is_dir() and (p / TEST_CFG_NAME).is_file()
    )


def load_config(config_dir):
    config_dir = Path(config_dir)
    issues = []
    if not re.match(CONFIG_NAME_RE, config_dir.name):
        issues.append(ValidationIssue(
            "error", "config.bad_name",
            "config dir name %r does not match %s"
            % (config_dir.name, CONFIG_NAME_RE)))
    for required in (COMPOSE_FILE_NAME, ENV_DEFAULT_NAME, TEST_CFG_NAME):
        if not (config_dir / required).is_file():
            issues.append(ValidationIssue(
                "error", "config.missing_file",
                "%s is missing in %s" % (required, config_dir.name)))
    issues.extend(composecheck.list_compose_files(config_dir))
    cfg = None
    cfg_path = config_dir / TEST_CFG_NAME
    if cfg_path.is_file():
        try:
            cfg = xmlcfg.parse_test_cfg(cfg_path)
            cfg.name = config_dir.name
            cfg.dir = config_dir
            issues.extend(cfg.warnings)
        except ConfigError as exc:
            issues.extend(exc.issues)
    return cfg, issues


def run_config(cfg, ctx, execute):
    issues = []
    work = ctx.output_root / "_work" / cfg.name
    # Каталоги предыдущего прогона сносим ДО начала. Иначе отчёты копятся:
    # coverlet пишет в cobertura timestamp, поэтому файлы разных прогонов не
    # совпадают побайтно, и счётчики покрытия складывались раз за разом
    # (на стенде 331/7447 превратилось в 993/22341 за три запуска). Хуже:
    # упавший прогон подбирал чужие отчёты и рапортовал успех сбора.
    shutil.rmtree(str(work), ignore_errors=True)
    shutil.rmtree(str(ctx.output_root / "reports" / cfg.name), ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)

    # 3.1: .env = .env.default + injected CI vars, rendered into work
    try:
        defaults = envfile.parse_env_file(cfg.dir / ENV_DEFAULT_NAME)
    except ConfigError as exc:
        return RunResult(cfg.name, ERROR, "bad %s" % ENV_DEFAULT_NAME,
                         issues=list(exc.issues))
    issues.extend(envfile.check_reserved(defaults))
    # .env.local перекрывает .env.default, но только при локальном запуске:
    # на агенте такого файла быть не должно, иначе прогон зависит от машины.
    local_env = cfg.dir / ENV_LOCAL_NAME
    if ctx.mode == "local" and local_env.is_file():
        try:
            overrides = envfile.parse_env_file(local_env)
        except ConfigError as exc:
            return RunResult(cfg.name, ERROR, "bad %s" % ENV_LOCAL_NAME,
                             issues=list(exc.issues))
        issues.extend(envfile.check_reserved(overrides))
        defaults = envfile.merge_env(defaults, overrides)
    elif ctx.mode != "local" and local_env.is_file():
        issues.append(ValidationIssue(
            "warning", "env.local_ignored",
            "%s есть в репозитории, но в режиме %s игнорируется"
            % (ENV_LOCAL_NAME, ctx.mode)))
    merged = envfile.merge_env(
        defaults, overridegen.injected_env(cfg.name, ctx.slot, ctx.ci_env))
    work_env = work / ".env"
    work_env.write_text(envfile.render_env_file(merged), encoding="utf-8")

    # 3.2: normalized compose + whitelist + input specs
    try:
        doc = composecheck.normalize_compose(cfg.dir, work_env, ctx.compose_bin)
    except ConfigError as exc:
        issues.extend(exc.issues)
        return RunResult(cfg.name, ERROR, "compose invalid", issues=issues)
    main_service = cfg.execution.main_service
    issues.extend(composecheck.check_compose(
        doc, main_service, ctx.registry_prefixes, config_dir=cfg.dir))
    for spec in cfg.inputs:
        issues.extend(staging.validate_input_spec(spec))
    issues.extend(_check_secrets(cfg, ctx))
    if _has_errors(issues):
        return RunResult(cfg.name, ERROR, "validation failed", issues=issues)

    # 3.3: staging
    staging_dir = work / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    output_dir = work / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    # The container writes here under cap_drop: ALL, so its root has no
    # DAC_OVERRIDE and obeys ordinary permission checks. When the runner is not
    # root (a TC agent runs as a service user), a 0755 dir owned by that user
    # is unwritable for the container and every report is silently lost.
    # Confirmed on the dev stand: touch -> "Permission denied", uid 0.
    # The directory is per-run harness scratch, removed with the build.
    os.chmod(str(output_dir), 0o777)
    issues.extend(staging.stage_inputs(cfg, ctx, staging_dir))
    if _has_errors(issues):
        return RunResult(cfg.name, ERROR, "staging failed", issues=issues)

    # 3.4: harness override
    override = overridegen.generate_override(doc, cfg, ctx, staging_dir,
                                             output_dir)
    override_file = overridegen.write_override(
        override, work / "docker-compose.harness.yml")

    if ctx.dry_run:
        return RunResult(cfg.name, PASSED, "dry-run", issues=issues)

    base = list(ctx.compose_bin) + [
        "-p", ctx.project_name(cfg.name),
        "-f", str(cfg.dir / COMPOSE_FILE_NAME),
        "-f", str(override_file),
        "--env-file", str(work_env),
        "--project-directory", str(cfg.dir),
    ]
    status = FAILED
    details = ""
    try:
        # 3.4-3.5: pull outside the timeout, up, wait on the main container
        pull = execute(base + ["pull"])
        up = execute(base + ["up", "-d"])
        if up.returncode != 0:
            # `up` writes the actual cause (missing image, registry auth, bad
            # mount) to stderr; without it "rc=1" sends people digging blind.
            details = "up failed (rc=%d): %s" % (
                up.returncode, _last_line(up.stderr) or "no stderr")
            if pull.returncode != 0:
                details += " | pull rc=%d: %s" % (
                    pull.returncode, _last_line(pull.stderr) or "no stderr")
            _write_infra_text(ctx, cfg, "up-stderr.txt", up.stderr, pull.stderr)
        else:
            cid = (execute(base + ["ps", "-q", main_service]).stdout or "").strip()
            if not cid:
                details = "no container for main service %r" % main_service
            else:
                try:
                    proc = execute(
                        list(ctx.docker_bin) + ["wait", cid],
                        timeout=cfg.execution.timeout_minutes * 60)
                    code = (proc.stdout or "").strip()
                    if code == "0":
                        status = PASSED
                    details = "main service exit code %s" % code
                except subprocess.TimeoutExpired:
                    details = ("timeout after %d min"
                               % cfg.execution.timeout_minutes)
    finally:
        # 3.6-3.7: evidence before teardown, teardown no matter what
        try:
            status, summary = _collect(cfg, ctx, base, execute, output_dir,
                                       issues, status)
        finally:
            execute(base + ["down", "-v", "--remove-orphans"])
    return RunResult(cfg.name, status, details, issues=issues, summary=summary)


def _check_secrets(cfg, ctx):
    """Fail-closed: объявил секрет — он обязан быть выложен файлом до запуска.

    Иначе контейнер стартует, прочитает пустоту и упадёт где-то в тестах, а
    настоящая причина останется незаметной.
    """
    if not cfg.secrets:
        return []
    if ctx.secrets_dir is None:
        return [ValidationIssue(
            "error", "secrets.dir_missing",
            "объявлено секретов: %d, но каталог с ними не передан. Локально — "
            "--secrets <каталог>; в CI — шаг «Секреты» и переменная TDC_SECRETS"
            % len(cfg.secrets))]
    issues = []
    known = {s.name for s in cfg.secrets}
    for spec in cfg.secrets:
        path = Path(ctx.secrets_dir) / spec.name
        if not path.is_file():
            issues.append(ValidationIssue(
                "error", "secrets.file_missing",
                "секрет %r не выложен: нет файла %s" % (spec.name, path)))
    # лишние файлы в каталоге — повод сказать вслух: не опечатка ли в имени
    try:
        extra = sorted(p.name for p in Path(ctx.secrets_dir).iterdir()
                       if p.is_file() and p.name not in known)
    except OSError:
        extra = []
    if extra:
        issues.append(ValidationIssue(
            "warning", "secrets.unused_files",
            "в каталоге секретов есть файлы, которых нет в манифесте: %s"
            % ", ".join(extra)))
    return issues


def _last_line(text):
    """Most informative single line of a compose failure (docker is chatty)."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def _write_infra_text(ctx, cfg, name, *chunks):
    infra = ctx.output_root / "reports" / cfg.name / INFRA_REPORT_DIR
    infra.mkdir(parents=True, exist_ok=True)
    body = "\n".join(c for c in chunks if c)
    (infra / name).write_text(body, encoding="utf-8")


def _collect(cfg, ctx, base, execute, output_dir, issues, status):
    """Reports + infra diagnostics into ctx.output_root/reports/<cfg.name>/."""
    reports_root = ctx.output_root / "reports" / cfg.name
    summary = RunSummary(reports_dir=str(reports_root))
    coverage_files = []
    test_files = []
    for spec in cfg.reports:
        matches = sorted(p for p in output_dir.glob(spec.path) if p.is_file())
        if not matches and not spec.optional:
            issues.append(ValidationIssue(
                "error", "reports.zero_matches",
                "report %r matched no files under %s" % (spec.path,
                                                         output_dir)))
            if status != FAILED:
                status = ERROR
            continue
        for src in matches:
            dest = reports_root / spec.type / src.relative_to(output_dir)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dest))
            summary.collected.append(str(dest.relative_to(reports_root)))
            if spec.format == "junit":
                teamcity.import_data("junit", str(dest))
                test_files.append((dest, "junit"))
            elif spec.format == "trx":
                teamcity.import_data("mstest", str(dest))
                test_files.append((dest, "trx"))
            elif spec.format == "cobertura":
                coverage_files.append(dest)
    summary.coverage = _emit_coverage_stats(coverage_files)
    summary.tests = _test_counts(test_files)
    for spec in cfg.out_artifacts:
        matches = sorted(p for p in output_dir.glob(spec.path) if p.is_file())
        if not matches and not spec.optional:
            issues.append(ValidationIssue(
                "error", "outputs.zero_matches",
                "artifact %r matched no files under %s" % (spec.path,
                                                           output_dir)))
            if status != FAILED:
                status = ERROR
            continue
        for src in matches:
            dest = reports_root / "artifacts" / src.relative_to(output_dir)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dest))
            summary.collected.append(str(dest.relative_to(reports_root)))
    infra = reports_root / INFRA_REPORT_DIR
    infra.mkdir(parents=True, exist_ok=True)
    logs = execute(base + ["logs", "--no-color", "-t"])
    (infra / "compose-logs.txt").write_text(logs.stdout or "",
                                            encoding="utf-8")
    ps = execute(base + ["ps", "-a"])
    (infra / "compose-ps.txt").write_text(ps.stdout or "", encoding="utf-8")
    return status, summary


_COVERAGE_STATS = (("lines", "L"), ("branches", "B"))


def _emit_coverage_stats(paths):
    """Cobertura has no TC importer: publish counters as build statistics.

    VSTest writes the coverage file twice -- once under results/<guid>/ and
    once into the attachment dir results/_<host>_<date>/In/<host>/ -- so a
    glob over the results tree yields duplicates that would double every
    counter. Identical files are counted once (observed with coverlet 8.0.1).
    """
    totals = {kind: [0, 0] for kind, _ in _COVERAGE_STATS}  # covered, valid
    seen = False
    digests = set()
    for path in paths:
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
        if digest in digests:
            continue
        digests.add(digest)
        try:
            root = ElementTree.parse(str(path)).getroot()
        except (ElementTree.ParseError, OSError):
            continue
        for kind, _ in _COVERAGE_STATS:
            try:
                covered = int(root.get("%s-covered" % kind))
                valid = int(root.get("%s-valid" % kind))
            except (TypeError, ValueError):
                continue
            totals[kind][0] += covered
            totals[kind][1] += valid
            seen = True
    if not seen:
        return []
    stats = []
    for kind, suffix in _COVERAGE_STATS:
        covered, valid = totals[kind]
        if not valid:
            continue
        teamcity.build_statistic("CodeCoverageAbs%sCovered" % suffix, covered)
        teamcity.build_statistic("CodeCoverageAbs%sTotal" % suffix, valid)
        teamcity.build_statistic("CodeCoverage%s" % suffix,
                                 round(100.0 * covered / valid, 2))
        stats.append((kind, covered, valid))
    return stats


_TRX_NS = "{http://microsoft.com/schemas/VisualStudio/TeamTest/2010}"


def _trx_counts(root):
    node = root.find("%sResultSummary/%sCounters" % (_TRX_NS, _TRX_NS))
    if node is None:
        return None
    def num(name):
        try:
            return int(node.get(name) or 0)
        except ValueError:
            return 0
    # notExecuted это и пропуски по фильтру, и [Skip]: для сводки одно и то же
    return (num("passed"), num("failed") + num("error"), num("notExecuted"))


def _junit_counts(root):
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    total = failed = skipped = 0
    for suite in suites:
        def num(name):
            try:
                return int(suite.get(name) or 0)
            except ValueError:
                return 0
        total += num("tests")
        failed += num("failures") + num("errors")
        skipped += num("skipped")
    if not total:
        return None
    return (total - failed - skipped, failed, skipped)


def _test_counts(paths):
    """(прошло, упало, пропущено) по отчётам, None если ни один не разобран.

    Файлы дедуплицируются по содержимому: VSTest кладёт копию отчёта в каталог
    вложений, и без этого счётчики удваивались бы — та же грабля, что с
    покрытием.
    """
    totals = [0, 0, 0]
    seen = False
    digests = set()
    for path, fmt in paths:
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
        if digest in digests:
            continue
        digests.add(digest)
        try:
            root = ElementTree.parse(str(path)).getroot()
        except (ElementTree.ParseError, OSError):
            continue
        counts = _trx_counts(root) if fmt == "trx" else _junit_counts(root)
        if counts is None:
            continue
        seen = True
        for i, value in enumerate(counts):
            totals[i] += value
    return tuple(totals) if seen else None


def sweep_orphans(execute, docker_bin):
    docker_bin = list(docker_bin)
    label_filter = "label=%s" % HARNESS_LABEL
    # Best effort: a degraded daemon must not kill the build in the sweep.
    try:
        proc = execute(docker_bin + ["ps", "-aq", "--filter", label_filter])
        ids = (proc.stdout or "").split()
        if ids:
            execute(docker_bin + ["rm", "-f"] + ids)
    except Exception:
        pass
    try:
        proc = execute(docker_bin + ["volume", "ls", "-q", "--filter",
                                     label_filter])
        vols = (proc.stdout or "").split()
        if vols:
            execute(docker_bin + ["volume", "rm"] + vols)
    except Exception:
        pass


def run_slot(ctx, execute):
    sweep_orphans(execute, ctx.docker_bin)
    results = []
    for config_dir in scan_configs(ctx.repo_root):
        name = config_dir.name
        cfg, issues = load_config(config_dir)
        if cfg is None or _has_errors(issues):
            results.append(RunResult(name, ERROR, "validation failed",
                                     issues=issues))
            continue
        if not cfg.matches_slot(ctx.slot):
            results.append(RunResult(
                name, SKIPPED,
                "slot %s not in os/arch matrix" % ctx.slot, issues=issues))
            continue
        # v1: known config-class capabilities are assumed present (docstring).
        teamcity.test_suite_started(name)
        try:
            result = run_config(cfg, ctx, execute)
            result.issues = issues + result.issues
        finally:
            teamcity.test_suite_finished(name)
        results.append(result)
    return results
