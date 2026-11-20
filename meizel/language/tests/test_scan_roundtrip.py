"""A scan survives the cache: what is decoded is the scan that was encoded, whatever the file."""

from __future__ import annotations

import dataclasses
import subprocess
from collections.abc import Mapping
from pathlib import Path

from meizel import allowances
from meizel.checkout import GitRepo
from meizel.graph.model import OS_KINDS, Sources
from meizel.language import FileScan, scan_all, scan_source
from meizel.language.python import (
    FixtureFunction,
    FixtureState,
    PythonRecord,
    decode_record,
    encode_record,
    python_record,
)
from meizel.language.scan_codec import decode_file_scan, encode_file_scan

_FILES = {
    "meizel.toml": '[roles]\napplication = ["pkg"]\ntests = ["tests"]\n',
    "meizel.policy.toml": (
        '[injected-calls]\n"max-sites" = ["2"]\n\n[injected-calls.sites]\n'
        '"pkg/mod.py#read#deps.read_text" = "the entry hands the reader in"\n'
        '"pkg/mod.py#gone#deps.read_text" = "approves nothing: no such function"\n'
    ),
    "pkg/__init__.py": "",
    "pkg/meizel.toml": 'purity = "strict-to-be"\n',
    "pkg/plugin.py": (
        "import pytest\n\n\n@pytest.fixture\ndef shared(tmp_path):\n    return tmp_path\n"
    ),
    "pkg/mod.py": (
        "from __future__ import annotations\n\n"
        "import enum\nimport os\nimport time\nimport uuid\nfrom typing import TYPE_CHECKING, Any, cast\n\n"
        "from pkg import plugin\n\n"
        "if TYPE_CHECKING:\n    from pkg.plugin import shared\n\n\n"
        "class Color(enum.Enum):\n    RED = 1\n    BLUE = 2\n    GREEN = 3\n\n\n"
        "def paint(color: Color) -> str:\n"
        "    return 'warm' if color in (Color.RED, Color.BLUE) else 'cold'\n\n\n"
        "def collect(items: list[int]) -> None:\n    items.append(1)\n\n\n"
        "def read(deps: object) -> str:\n    return deps.read_text()\n\n\n"
        "def identity(value: Any) -> Any:\n"
        "    return cast(int, value), os.environ, f'{time.monotonic_ns()}', uuid.uuid4(), plugin\n\n\n"
        "def wait() -> None:\n    exec('1')\n    open('x')\n"
    ),
    "conftest.py": (
        "import subprocess\n\nimport pytest\n\npytest_plugins = ['pkg.plugin']\n\n\n"
        "def helper():\n    return subprocess.run(['true'])\n\n\n"
        "def deeper():\n    return helper()\n\n\n"
        "@pytest.fixture\ndef db(shared):\n    import sqlite3\n    return sqlite3.connect(':memory:')\n\n\n"
        "@pytest.fixture\nasync def connection(db):\n    return deeper()\n"
    ),
    "pkg/other.py": (
        "from pkg.mod import Color\n\n\n"
        "def cold(color: Color) -> bool:\n    return color in (Color.RED, Color.BLUE)\n"
    ),
    "tests/__init__.py": "",
    "tests/test_mod.py": (
        "import pytest\nfrom unittest import mock\n\nfrom pkg import mod\n\n\n"
        "@pytest.mark.usefixtures('db')\n"
        "def test_it(connection, monkeypatch, request):\n"
        "    monkeypatch.setattr(mod, 'read', lambda deps: '')\n"
        "    request.getfixturevalue('db')\n"
        "    with mock.patch.object(mod, 'wait'):\n        mod.collect([])\n"
    ),
}


def _init_git_repo(base: Path, files: Mapping[str, str]) -> Path:
    root = base / "repo"
    root.mkdir()
    # Fixed git init argv on a temporary directory without invoking a shell.
    subprocess.run(["git", "init", "--initial-branch=main", "-q", str(root)], check=True)  # noqa: S603
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    # Fixed git add argv on the temporary checkout without invoking a shell.
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)  # noqa: S603
    return root


def _scans(root: Path) -> dict[str, FileScan]:
    universe = GitRepo(root).universe()
    return scan_all(universe, Sources(), jobs=1, policy=allowances.load(universe.repo))


# The fields that hold something other than their default in at least one of these values; a field
# with no default (a name, a line) is always held.
def _populated(
    values: Mapping[str, object], fields: tuple[dataclasses.Field[object], ...]
) -> set[str]:
    rows = [dataclasses.asdict(value) for value in values.values()]  # type: ignore[arg-type]
    held: set[str] = set()
    for field in fields:
        if field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING:
            held.add(field.name)
            continue
        default = (
            field.default
            if field.default_factory is dataclasses.MISSING
            else field.default_factory()
        )
        blank = dataclasses.asdict(default) if dataclasses.is_dataclass(default) else default  # type: ignore[arg-type]
        if any(row[field.name] != blank for row in rows):
            held.add(field.name)
    return held


def test_a_decoded_scan_is_the_scan_it_was_encoded_from(tmp_path: Path) -> None:
    scans = _scans(_init_git_repo(tmp_path, _FILES))
    assert scans
    for path, scan in scans.items():
        encoded = encode_file_scan(scan, encode_record)
        assert decode_file_scan(encoded, OS_KINDS, decode_record) == scan, path


# The test above is only as strong as the scans it covers: every field of a scan, of the record the
# Python frontend keeps, and of a fixture is non-default in at least one file here, so a field that
# the codec forgets cannot hide behind an empty default. `symbols` is the TypeScript compiler's.
def test_the_files_populate_every_field_the_codec_carries(tmp_path: Path) -> None:
    scans = _scans(_init_git_repo(tmp_path, _FILES))
    records = {path: python_record(scan) for path, scan in scans.items()}
    scan_fields = tuple(f for f in dataclasses.fields(FileScan) if f.name not in {"path", "extra"})
    missing = {f.name for f in scan_fields} - _populated(scans, scan_fields)
    assert missing == {"symbols"}
    record_fields = dataclasses.fields(PythonRecord)
    assert {f.name for f in record_fields} - _populated(records, record_fields) == set()
    states = {path: record.fixtures for path, record in records.items()}
    state_fields = dataclasses.fields(FixtureState)
    assert {f.name for f in state_fields} - _populated(states, state_fields) == set()
    functions = {
        f"{path}:{fn.name}": fn
        for path, record in records.items()
        for fn in (*record.fixtures.functions, *record.fixtures.helpers)
    }
    function_fields = dataclasses.fields(FixtureFunction)
    assert {f.name for f in function_fields} - _populated(functions, function_fields) == set()


# A second run reads the first run's scans back from the checkout's cache, and sees what the first saw.
def test_a_scan_read_back_from_the_cache_is_the_scan_that_was_stored(
    tmp_path: Path,
) -> None:
    root = _init_git_repo(tmp_path, _FILES)
    first_universe = GitRepo(root).universe()
    first = scan_all(first_universe, Sources(), jobs=1, policy=allowances.load(first_universe.repo))
    second_universe = GitRepo(root).universe()
    second = scan_all(
        second_universe, Sources(), jobs=1, policy=allowances.load(second_universe.repo)
    )
    assert second == first


# The files of this repository, scanned afresh (the cache would hand back what an earlier run stored).
def test_the_files_of_this_repository_round_trip() -> None:
    universe = GitRepo(Path(__file__).resolve().parents[3]).universe()
    policy = allowances.load(universe.repo)
    paths = [path for path in universe.files_ending((".py",)) if path.startswith("meizel/")]
    assert len(paths) > 100
    for path in paths:
        scan = scan_source(universe, path, universe.repo.load_bytes(path), Sources(), policy=policy)
        encoded = encode_file_scan(scan, encode_record)
        assert decode_file_scan(encoded, OS_KINDS, decode_record) == scan, path
