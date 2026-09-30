import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from mkrom import load_module  # noqa: E402


@pytest.fixture(scope="session")
def module_path():
    """Assemble the current source so the tests never run a stale binary."""
    out = ROOT / "build" / "ppi2000mem"
    assemble("ppi2000mem.asm", out)
    return out


@pytest.fixture(scope="session")
def module_code(module_path):
    """(code bytes, relocation offsets) of the assembled module."""
    return load_module(module_path)


def assemble(src, out, fmt="hunkexe"):
    out.parent.mkdir(exist_ok=True)
    subprocess.run(["vasmm68k_mot", f"-F{fmt}", "-nosym", "-quiet", "-o", str(out),
                    str(ROOT / "src" / src)], check=True, cwd=ROOT)


@pytest.fixture(scope="session")
def ppiload_code():
    """(code bytes, relocations) of ppiload, with the module built in."""
    assemble("ppi2000mem.asm", ROOT / "build" / "ppi2000mem.bin", "bin")
    assemble("ppiload.asm", ROOT / "build" / "ppiload")
    return load_module(ROOT / "build" / "ppiload")


@pytest.fixture(scope="session")
def ppiprobe_path():
    out = ROOT / "build" / "ppiprobe"
    assemble("ppiprobe.asm", out)
    return out
