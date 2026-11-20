# `meizel` as a child process whose environment the caller chose: the test hands it a PATH instead
# of patching this process's.
from __future__ import annotations

import sys

from meizel.entry import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
