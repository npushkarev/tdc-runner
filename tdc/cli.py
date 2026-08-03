"""CLI: python3 -m tdc {validate|run}.

validate: --repo PATH [--registry-prefix P ...]
    Load every config under every trigger dir, run compose normalization
    + whitelist when docker is available (--no-docker to skip), print
    issues, exit 1 on any error.

run: --repo PATH --slot lin-x64 --mode {ci,local} --out PATH
     [--artifacts PATH] [--config NAME] [--build-id ID] [--dry-run]
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

from . import composecheck, envfile, overridegen, runner, slots, staging
from .model import (
    COMPOSE_FILE_NAME, CONFIG_DIR_ROOT, DEFAULT_REGISTRY_PREFIXES,
    ENV_DEFAULT_NAME, TRIGGER_CLASSES, ConfigError, RunContext, RunResult,
    Slot, TestConfig, PASSED, SKIPPED, ERROR,
)


def _execute(cmd, **kw):
    kw.setdefault("stdout", subprocess.PIPE)
    kw.setdefault("stderr", subprocess.PIPE)
    kw.setdefault("universal_newlines", True)
    return subprocess.run(cmd, **kw)


def _has_compose_v2():
    """`docker` on PATH says nothing about the compose v2 plugin being there."""
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(["docker", "compose", "version"],
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL).returncode == 0
    except OSError:
        return False


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


def _validate_compose(config_dir, cfg, prefixes):
    """Normalize via `docker compose config` and run the whitelist."""
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
                                                 ("docker", "compose"))
        main = cfg.execution.main_service if cfg.execution else ""
        return composecheck.check_compose(doc, main, prefixes,
                                          config_dir=config_dir)
    except ConfigError as exc:
        return list(exc.issues)


def _cmd_validate(args):
    repo = Path(args.repo).resolve()
    prefixes = _registry_prefixes(args)
    use_docker = not args.no_docker and _has_compose_v2()
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
                                                prefixes))
            label = "%s/%s" % (trigger, config_dir.name)
            if not issues:
                print("%s: OK" % label)
            for issue in issues:
                print("%s: %s" % (label, issue))
            if any(i.severity == "error" for i in issues):
                failed = True
    if use_docker:
        note = ""
    elif args.no_docker:
        note = " (compose checks skipped: --no-docker)"
    else:
        note = " (compose checks skipped: docker compose v2 unavailable)"
    print("validated %d config(s)%s" % (total, note))
    return 1 if failed else 0


def _cmd_run(args):
    try:
        slot = slots.parse_slot(args.slot)
    except ValueError as exc:
        print("tdc: %s" % exc, file=sys.stderr)
        return 2
    if args.mode == "local" and not args.config:
        print("tdc: --mode local requires --config", file=sys.stderr)
        return 2
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
    )
    ctx.output_root.mkdir(parents=True, exist_ok=True)
    if args.mode == "local":
        config_dir = (ctx.repo_root / CONFIG_DIR_ROOT / TRIGGER_CLASSES[0]
                      / args.config)
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
