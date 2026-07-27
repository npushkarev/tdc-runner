"""Slot parsing and slot-token path matching.

parse_slot(text: str) -> Slot
    "lin-x64" -> Slot("lin","x64"); validate against OSES/ARCHES else ValueError.

path_matches_slot(relpath: str, slot: Slot) -> bool
    True if the relative path (of an artifact) carries this slot's tokens.
    Tokenize on separators [./_\\-] (path segments AND file name pieces:
    "grpc.lin.gcc.shared.x64.1.78.1.nupkg" -> ... "lin" ... "x64" ...).
    Rules:
      - os token: slot.os ("lin"/"win") present among tokens.
      - arch token: slot.arch present among tokens; token comparison is exact,
        so "arm" does NOT match "arm64" and vice versa.
      - If the path carries NO os token and NO arch token at all -> True
        (slot-neutral artifact, e.g. shared test data).
      - If it carries only one axis, only that axis must match.
"""
import re

from .model import Slot, OSES, ARCHES

# Backslash included so win-style relative paths tokenize the same way.
_TOKEN_SEP_RE = re.compile(r"[./_\\-]+")


def parse_slot(text):
    # maxsplit=1: the arch may not swallow extra dashes ("lin-arm-64" is invalid).
    parts = text.split("-", 1)
    if len(parts) != 2 or parts[0] not in OSES or parts[1] not in ARCHES:
        raise ValueError(
            "invalid slot %r: expected <os>-<arch> with os in %s and arch in %s"
            % (text, "/".join(OSES), "/".join(ARCHES)))
    return Slot(parts[0], parts[1])


def path_matches_slot(relpath, slot):
    tokens = set(_TOKEN_SEP_RE.split(relpath))
    os_tokens = tokens.intersection(OSES)
    arch_tokens = tokens.intersection(ARCHES)
    os_ok = not os_tokens or slot.os in os_tokens
    arch_ok = not arch_tokens or slot.arch in arch_tokens
    return os_ok and arch_ok
