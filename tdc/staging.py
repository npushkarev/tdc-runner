"""Input staging: glob resolution, slot filter, safe copy.

validate_input_spec(spec: InputSpec) -> List[ValidationIssue]
    - path/dest: reject absolute paths and any '..' segment
      ("inputs.path_escape").
    - source specs: pattern must start with a literal path segment
      (no glob meta in the first segment; leading '**' forbidden)
      -> "inputs.source_root_glob".

resolve_glob(root: Path, pattern: str) -> List[Path]
    Deterministic (sorted) glob over root, files only.

stage_inputs(cfg: TestConfig, ctx: RunContext, staging_dir: Path)
        -> List[ValidationIssue]
    For each InputSpec:
      - root = ctx.artifacts_root (artifact) / ctx.repo_root (source).
        artifact spec with ctx.artifacts_root None -> "inputs.no_artifacts".
      - matches = resolve_glob(...); for artifact specs with
        spec.slot_filter, keep only slots.path_matches_slot(rel, ctx.slot)
        (log dropped count via issues, severity "warning",
        code "inputs.slot_filtered").
      - 0 matches and not spec.optional -> error "inputs.zero_matches".
      - Copy preserving the path relative to the STATIC PREFIX of the
        pattern (rsync semantics: for "output/**/*.nupkg" the preserved
        part starts after "output/"). Destination: staging_dir/spec.dest/...
      - Final-path collision from different specs -> error
        "inputs.dest_collision".
      - NEVER dereference symlinks (shutil.copy2 with follow_symlinks=False
        for the link itself); after copying, any symlink whose resolved
        target escapes its source root -> error "inputs.symlink_escape"
        and the link is removed.
    Errors abort the config (caller checks), staging_dir may be partial.
"""
import glob
import os
import re
import shutil
from pathlib import Path, PurePosixPath, PureWindowsPath

from .model import InputSpec, TestConfig, RunContext, ValidationIssue  # noqa: F401
from . import slots

_GLOB_META = re.compile(r"[*?\[]")


def _segments(p):
    return [s for s in re.split(r"[\\/]", p) if s not in ("", ".")]


def _is_absolute(p):
    return PurePosixPath(p).is_absolute() or PureWindowsPath(p).is_absolute()


def _static_prefix_len(pattern):
    """Leading literal directory segments; the last segment is always preserved."""
    segs = _segments(pattern)
    n = 0
    for seg in segs[:-1]:
        if _GLOB_META.search(seg):
            break
        n += 1
    return n


def validate_input_spec(spec):
    issues = []
    for name, value in (("path", spec.path), ("dest", spec.dest)):
        if _is_absolute(value) or ".." in _segments(value):
            issues.append(ValidationIssue(
                "error", "inputs.path_escape",
                "input %s %r: absolute paths and '..' segments are forbidden"
                % (name, value)))
    if spec.kind == "source":
        segs = _segments(spec.path)
        first = segs[0] if segs else ""
        if not first or _GLOB_META.search(first):
            issues.append(ValidationIssue(
                "error", "inputs.source_root_glob",
                "source path %r must start with a literal segment" % spec.path))
    return issues


def resolve_glob(root, pattern):
    root = Path(root)
    hits = glob.glob(glob.escape(str(root)) + os.sep + pattern, recursive=True)
    out = []
    for hit in sorted(set(hits)):
        # symlinks stay in the list undereferenced so stage_inputs can vet them
        if os.path.islink(hit) or os.path.isfile(hit):
            out.append(Path(hit))
    return out


def stage_inputs(cfg, ctx, staging_dir):
    issues = []
    staging_dir = Path(staging_dir)
    staging_norm = os.path.normpath(str(staging_dir))
    staged = {}  # normalized final path -> spec that staged it
    for spec in cfg.inputs:
        if spec.kind == "artifact":
            if ctx.artifacts_root is None:
                issues.append(ValidationIssue(
                    "error", "inputs.no_artifacts",
                    "artifact input %r: не указан каталог артефактов. Локально — ./run_local.sh <набор> --artifacts <каталог со сборкой>; в CI — переменная TDC_ARTIFACTS" % spec.path))
                continue
            root = Path(ctx.artifacts_root)
        else:
            root = Path(ctx.repo_root)
        matches = resolve_glob(root, spec.path)
        if spec.kind == "artifact" and spec.slot_filter:
            kept = [m for m in matches
                    if slots.path_matches_slot(m.relative_to(root).as_posix(),
                                               ctx.slot)]
            dropped = len(matches) - len(kept)
            if dropped:
                issues.append(ValidationIssue(
                    "warning", "inputs.slot_filtered",
                    "%r: %d match(es) dropped by slot filter %s"
                    % (spec.path, dropped, ctx.slot)))
            matches = kept
        if not matches:
            if not spec.optional:
                issues.append(ValidationIssue(
                    "error", "inputs.zero_matches",
                    "%s input %r matched nothing" % (spec.kind, spec.path)))
            continue
        prefix_len = _static_prefix_len(spec.path)
        root_real = Path(os.path.realpath(str(root)))
        for m in matches:
            rel = m.relative_to(root)
            dest = staging_dir.joinpath(spec.dest, *rel.parts[prefix_len:])
            key = os.path.normpath(str(dest))
            # belt and braces: never write outside staging_dir even if the
            # spec skipped validate_input_spec
            if key != staging_norm and not key.startswith(staging_norm + os.sep):
                issues.append(ValidationIssue(
                    "error", "inputs.path_escape",
                    "staged path %s escapes the staging dir" % key))
                continue
            other = staged.get(key)
            if other is not None:
                if other is not spec:
                    issues.append(ValidationIssue(
                        "error", "inputs.dest_collision",
                        "inputs %r and %r both stage %s"
                        % (other.path, spec.path, key)))
                continue
            staged[key] = spec
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(m), str(dest), follow_symlinks=False)
            if os.path.islink(str(m)):
                target = Path(os.path.realpath(str(m)))
                try:
                    target.relative_to(root_real)
                except ValueError:
                    dest.unlink()
                    issues.append(ValidationIssue(
                        "error", "inputs.symlink_escape",
                        "symlink %s -> %s escapes %s; link removed"
                        % (rel.as_posix(), target, root)))
    return issues
