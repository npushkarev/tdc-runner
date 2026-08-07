"""CLI: python3 -m tdc {validate|run}.

validate: --repo PATH [--registry-prefix P ...]
    Load every config under every trigger dir, run compose normalization
    + whitelist when docker is available (--no-docker to skip), print
    issues, exit 1 on any error.

run: --repo PATH --slot lin-x64 --mode {ci,local} --out PATH
     [--artifacts PATH] [--secrets PATH] [--config NAME]
     [--build-id ID] [--dry-run]
     [--registry-prefix P ...]
    mode=ci runs every slot-matching config (runner.run_slot);
    mode=local requires --config and runs just it.
    Exit code: 0 all passed/skipped, 1 any failed/error.

main(argv=None) -> int; module runnable via __main__.py.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import (composebin, composecheck, envfile, overridegen, runner,
               slots, staging)
from .model import (
    COMPOSE_FILE_NAME, CONFIG_DIR_ROOT, DEFAULT_REGISTRY_PREFIXES,
    ENV_DEFAULT_NAME, INFRA_REPORT_DIR, TRIGGER_CLASSES, ConfigError,
    RunContext, RunResult, Slot, TestConfig, PASSED, SKIPPED, ERROR,
)


def _execute(cmd, **kw):
    kw.setdefault("stdout", subprocess.PIPE)
    kw.setdefault("stderr", subprocess.PIPE)
    kw.setdefault("universal_newlines", True)
    return subprocess.run(cmd, **kw)


def _registry_prefixes(args):
    return DEFAULT_REGISTRY_PREFIXES + tuple(args.registry_prefix or ())


def _validate_static(config_dir, cfg):
    """Docker-independent checks: reserved env names, input specs."""
    issues = []
    env_path = config_dir / ENV_DEFAULT_NAME
    if env_path.is_file():
        try:
            issues.extend(envfile.check_reserved(
                envfile.parse_env_file(env_path)))
        except ConfigError as exc:
            issues.extend(exc.issues)
    if cfg is not None:
        for spec in cfg.inputs:
            issues.extend(staging.validate_input_spec(spec))
    return issues


def _validate_compose(config_dir, cfg, prefixes, compose_bin):
    """Normalize via the resolved compose CLI and run the whitelist."""
    env = {}
    env_path = config_dir / ENV_DEFAULT_NAME
    if env_path.is_file():
        try:
            env = envfile.parse_env_file(env_path)
        except ConfigError:
            pass  # already reported by _validate_static
    # Placeholder slot so ${TEST_ARCH}-style interpolation resolves.
    merged = envfile.merge_env(
        env, overridegen.injected_env(cfg.name, Slot("lin", "x64"), {}))
    try:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(envfile.render_env_file(merged),
                                encoding="utf-8")
            doc = composecheck.normalize_compose(config_dir, env_file,
                                                 compose_bin)
        main = cfg.execution.main_service if cfg.execution else ""
        return composecheck.check_compose(doc, main, prefixes,
                                          config_dir=config_dir)
    except ConfigError as exc:
        return list(exc.issues)


def _cmd_validate(args):
    repo = Path(args.repo).resolve()
    prefixes = _registry_prefixes(args)
    compose_bin, source = composebin.resolve()
    use_docker = not args.no_docker and compose_bin is not None
    failed = False
    total = 0
    for trigger in TRIGGER_CLASSES:
        for config_dir in runner.scan_configs(repo, trigger):
            total += 1
            cfg, issues = runner.load_config(config_dir)
            issues.extend(_validate_static(config_dir, cfg))
            if use_docker and (config_dir / COMPOSE_FILE_NAME).is_file():
                # Broken test_cfg.xml must not hide compose violations:
                # fall back to a stub config (main_service check is skipped).
                compose_cfg = cfg or TestConfig(name=config_dir.name,
                                                dir=config_dir)
                issues.extend(_validate_compose(config_dir, compose_cfg,
                                                prefixes, compose_bin))
            label = "%s/%s" % (trigger, config_dir.name)
            if not issues:
                print("%s: OK" % label)
            for issue in issues:
                print("%s: %s" % (label, issue))
            if any(i.severity == "error" for i in issues):
                failed = True
    if use_docker:
        note = " (compose: %s)" % source
    elif args.no_docker:
        note = " (compose checks skipped: --no-docker)"
    else:
        note = " (compose checks skipped: %s)" % source
    print("validated %d config(s)%s" % (total, note))
    return 1 if failed else 0


_COVERAGE_TITLES = {"lines": "строки", "branches": "ветви"}
_COLLECTED_SHOWN = 8


def _print_summary(summary):
    """Итог словами: раньше в логе был только статус, а сколько тестов прошло
    и куда легли файлы, приходилось выяснять по служебным сообщениям TC или
    ходить по каталогам руками."""
    if summary.tests is not None:
        passed, failed, skipped = summary.tests
        print("  тесты: %d прошло, %d упало, %d пропущено"
              % (passed, failed, skipped))
    if summary.coverage:
        parts = ["%s %d/%d (%.2f%%)" % (_COVERAGE_TITLES.get(kind, kind),
                                        covered, valid,
                                        100.0 * covered / valid)
                 for kind, covered, valid in summary.coverage if valid]
        if parts:
            print("  покрытие: %s" % ", ".join(parts))
    if not summary.reports_dir:
        return
    print("  отчёты: %s" % summary.reports_dir)
    for rel in summary.collected[:_COLLECTED_SHOWN]:
        print("    %s" % rel)
    extra = len(summary.collected) - _COLLECTED_SHOWN
    if extra > 0:
        print("    и ещё %d файл(ов)" % extra)
    print("    %s/ — логи контейнеров и вывод compose" % INFRA_REPORT_DIR)


def _cmd_run(args):
    try:
        slot = slots.parse_slot(args.slot)
    except ValueError as exc:
        print("tdc: %s" % exc, file=sys.stderr)
        return 2
    if args.mode == "local" and not args.config:
        print("tdc: --mode local requires --config", file=sys.stderr)
        return 2
    compose_bin, source = composebin.resolve()
    if compose_bin is None and not args.dry_run:
        print("tdc: %s" % source, file=sys.stderr)
        return 2
    print("tdc: compose = %s (%s)" % (" ".join(compose_bin or ()), source))
    ci_env = {}
    for name in ("BUILD_NUMBER", "VCS_REVISION"):
        if name in os.environ:
            ci_env[name] = os.environ[name]
    # TeamCity exposes the revision as BUILD_VCS_NUMBER
    if "VCS_REVISION" not in ci_env and "BUILD_VCS_NUMBER" in os.environ:
        ci_env["VCS_REVISION"] = os.environ["BUILD_VCS_NUMBER"]
    ctx = RunContext(
        mode=args.mode,
        slot=slot,
        repo_root=Path(args.repo).resolve(),
        artifacts_root=Path(args.artifacts).resolve() if args.artifacts
        else None,
        output_root=Path(args.out).resolve(),
        build_id=args.build_id,
        ci_env=ci_env,
        registry_prefixes=_registry_prefixes(args),
        dry_run=args.dry_run,
        secrets_dir=Path(args.secrets).resolve() if args.secrets
        else None,
    )
    if compose_bin is not None:
        ctx.compose_bin = tuple(compose_bin)
    ctx.output_root.mkdir(parents=True, exist_ok=True)
    if args.mode == "local":
        config_dir = (ctx.repo_root / CONFIG_DIR_ROOT / TRIGGER_CLASSES[0]
                      / args.config)
        if not config_dir.is_dir():
            # опечатка в имени набора не должна выглядеть как падение ядра
            available = [d.name for d in runner.scan_configs(ctx.repo_root)]
            print("tdc: набор %r не найден в %s" % (args.config, ctx.repo_root),
                  file=sys.stderr)
            print("tdc: доступны: %s"
                  % (", ".join(available) if available
                     else "ни одного (нет каталога %s/%s/)"
                          % (CONFIG_DIR_ROOT, TRIGGER_CLASSES[0])),
                  file=sys.stderr)
            return 2
        cfg, issues = runner.load_config(config_dir)
        if cfg is None or any(i.severity == "error" for i in issues):
            results = [RunResult(args.config, ERROR, "validation failed",
                                 issues=issues)]
        else:
            results = [runner.run_config(cfg, ctx, _execute)]
    else:
        results = runner.run_slot(ctx, _execute)
    for res in results:
        suffix = " (%s)" % res.details if res.details else ""
        print("%s: %s%s" % (res.config_name, res.status, suffix))
        _print_summary(res.summary)
        for issue in res.issues:
            print("  %s" % issue)
    bad = [r for r in results if r.status not in (PASSED, SKIPPED)]
    return 1 if bad else 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="tdc", description="test_docker_config runner (IN-662)")
    sub = parser.add_subparsers(dest="command")

    p_validate = sub.add_parser("validate",
                                help="validate configs without running")
    p_validate.add_argument("--repo", required=True)
    p_validate.add_argument("--registry-prefix", action="append", default=[])
    p_validate.add_argument("--no-docker", action="store_true",
                            help="skip `docker compose config` checks")

    p_run = sub.add_parser("run", help="run configs for one slot")
    p_run.add_argument("--repo", required=True)
    p_run.add_argument("--slot", required=True, help="e.g. lin-x64")
    p_run.add_argument("--mode", choices=("ci", "local"), required=True)
    p_run.add_argument("--out", required=True)
    p_run.add_argument("--artifacts")
    p_run.add_argument("--secrets",
                       help="каталог с файлами-секретами (см. <secrets>)")
    p_run.add_argument("--config")
    p_run.add_argument("--build-id", default="local")
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--registry-prefix", action="append", default=[])

    args = parser.parse_args(argv)
    if args.command == "validate":
        return _cmd_validate(args)
    if args.command == "run":
        return _cmd_run(args)
    parser.print_usage(sys.stderr)
    return 2
