"""How a file is judged where the manifests say what its neighbours are: the purity a test file
runs under, and the debt a violation of that purity is recorded as."""

from __future__ import annotations

from meizel.contracts.debt import file_key
from meizel.contracts.manifest import Manifest, effective_purity
from meizel.graph.model import DebtKey, FactKind
from meizel.language import FileScan

__all__ = ["purity_debt", "test_purity_mode"]


def purity_debt(owner: str, path: str, key: str, mode: str) -> DebtKey | None:
    return None if mode == "strict" else DebtKey(owner, file_key(owner, path, key))


def test_purity_mode(scan: FileScan, manifests: dict[str, Manifest]) -> str:
    own_mode = effective_purity(scan.path, manifests, include_tests=True)
    targets = {
        f.dst
        for f in scan.facts
        if f.kind in {FactKind.IMPORT, FactKind.ATTRIBUTE, FactKind.PATCH} and f.dst != scan.path
    }
    if not targets:
        return own_mode
    target_modes = {effective_purity(dst, manifests) for dst in targets}
    if "off" in target_modes:
        return "off"
    return "ratchet" if own_mode == "ratchet" or "ratchet" in target_modes else "strict"
