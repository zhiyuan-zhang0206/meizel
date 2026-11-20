# The calls Python's standard library makes whose name alone says what they read: the files a
# `filesystem` root licenses, the wait a `sleep` root licenses, and the kinds the ambient table
# judges a call by its name -- what a `[roots]` declaration of a kind reaches without the scan
# recording an acquisition on the call's line.

from __future__ import annotations

from meizel.graph.model import AmbientKind, ItemReads, PurityItem
from meizel.language.python.surface.surface import judged

__all__ = ["FILESYSTEM_READS", "SLEEP_CALLS", "python_item_reads"]

# The calls a `filesystem` root licenses: the ones whose name decides that it reads. A read of a
# file is an effect in the purity layer, whose keys these are, so this table is the one place the
# `filesystem` kind reaches; a new key belongs here only with a call that layer charges, and the
# table's test pins the set: the module calls against `DEFAULT_IMPURE_CALLS`, every key by hand.
#
# Three families stay out, and each is a boundary rather than an omission. An `open` whose mode
# decides whether it writes (`open`, `builtins.open`, `io.open`, `Path.open`) is an effect the name
# cannot tell from a read. A call on a descriptor (`os.open`, `os.fdopen`, `os.read`, `os.fstat`,
# `os.fwalk`) reads whatever the descriptor is, not a path. A listing given no path (`os.listdir`,
# `os.scandir`) reads the working directory, which is the `cwd` kind and is recorded as an
# acquisition on its line. Every write, rename, unlink and chmod is an effect of the same door and
# stays `impure-call` under any root.
#
# `resolve` and `os.path.realpath` are in it: every one of these reads anchors a relative path in
# the working directory, which the purity layer does not separate out, so a `filesystem` root reads
# the working directory as far as the paths it is handed reach -- the same reach every read here has.
FILESYSTEM_READS: frozenset[str] = frozenset(
    {
        "Path.read_text",
        "Path.read_bytes",
        "Path.exists",
        "Path.is_file",
        "Path.is_dir",
        "Path.is_symlink",
        "Path.samefile",
        "Path.stat",
        "Path.lstat",
        "Path.readlink",
        "Path.iterdir",
        "Path.glob",
        "Path.rglob",
        "Path.resolve",
        "glob.glob",
        "glob.iglob",
        "inspect.getsource",
        "inspect.getsourcefile",
        "inspect.getsourcelines",
        "os.access",
        "os.lstat",
        "os.readlink",
        "os.stat",
        "os.statvfs",
        "os.walk",
        "os.path.exists",
        "os.path.getatime",
        "os.path.getctime",
        "os.path.getmtime",
        "os.path.getsize",
        "os.path.isdir",
        "os.path.isfile",
        "os.path.islink",
        "os.path.ismount",
        "os.path.lexists",
        "os.path.realpath",
        "os.path.samefile",
        "pkgutil.get_data",
    }
)

# The call a `sleep` root licenses: the synchronous process wait at the timer door (`time.sleep`).
# `clock` does not cover `sleep`, so a clock root that waits without declaring `sleep` still owes
# the `impure-call` record; coroutine and synchronisation waits (`asyncio.sleep`, `Event.wait`) are
# not in this set.
SLEEP_CALLS: frozenset[str] = frozenset({"time.sleep"})


# What a purity item of a Python file reads by its name. An item keyed by a site (`fn#call`) reads
# by the line the scan recorded alone, so it reads nothing here; a call reached only when given no
# value reads nothing once it is handed the value, so an `unless` clause names no kind. The purity
# rule keeps the short spelling a call canonicalises to (`datetime.now` for the table's
# `datetime.datetime.now`), so the table's own spelling is a second candidate: the same name, not a
# second rule.
def python_item_reads(item: PurityItem) -> ItemReads:
    if item.key in FILESYSTEM_READS:
        door = frozenset({AmbientKind.FILESYSTEM})
        return ItemReads(door, door)
    if item.key in SLEEP_CALLS:
        door = frozenset({AmbientKind.SLEEP})
        return ItemReads(door, door)
    if "#" in item.key:
        return ItemReads(frozenset(), frozenset())
    reading = judged(item.key)
    if reading is None and "." in item.key:
        head, _, _ = item.key.partition(".")
        reading = judged(f"{head}.{item.key}")
    if reading is None or reading.judgment.unless is not None:
        return ItemReads(frozenset(), frozenset())
    return ItemReads(frozenset(), frozenset(reading.judgment.kinds))
