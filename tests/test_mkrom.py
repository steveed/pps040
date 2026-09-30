"""Check tools/mkrom.py against a synthetic Kickstart image.

Real Kickstart ROMs can't be part of the repository, so these tests build a
512K image with the same shape: the $1114 header and reset jump, some
non-empty "code", a run of $FF free space, and the footer with checksum, size
and vector bytes. The checksum is verified with an independent implementation.
"""
import struct
import subprocess
import sys

import pytest

from conftest import ROOT
from mkrom import CHECKSUM_OFF, ROM_BASE, ROM_SIZE, RomError, byteswap, patch_rom

FREE_START = 0x70004        # deliberately not 16-byte aligned


def kick_checksum_ok(rom):
    total = 0
    for (v,) in struct.iter_unpack(">I", rom):
        total += v
        if total > 0xFFFFFFFF:
            total = (total & 0xFFFFFFFF) + 1
    return total == 0xFFFFFFFF


def fake_kickstart(free_start=FREE_START):
    rom = bytearray(ROM_SIZE)
    for i in range(0, CHECKSUM_OFF, 2):            # any non-$FF filler
        struct.pack_into(">H", rom, i, (i * 7 + 3) & 0x7F7F)
    rom[0:8] = bytes.fromhex("11144ef900f800d2")
    rom[free_start:CHECKSUM_OFF] = b"\xff" * (CHECKSUM_OFF - free_start)
    struct.pack_into(">I", rom, CHECKSUM_OFF + 4, ROM_SIZE)
    rom[CHECKSUM_OFF + 8:] = bytes(range(0x18, 0x20)) * 2
    total = 0
    for (v,) in struct.iter_unpack(">I", rom):
        total += v
        if total > 0xFFFFFFFF:
            total = (total & 0xFFFFFFFF) + 1
    struct.pack_into(">I", rom, CHECKSUM_OFF, ~total & 0xFFFFFFFF)
    assert kick_checksum_ok(rom)
    return bytes(rom)


def test_module_is_placed_aligned_in_the_free_area(module_code):
    code, relocs = module_code
    rom, addr, (start, length) = patch_rom(fake_kickstart(), code, relocs)
    off = addr - ROM_BASE
    assert start == FREE_START and length == CHECKSUM_OFF - FREE_START
    assert off % 16 == 0 and start <= off < start + length


def test_romtag_pointers_are_relocated(module_code):
    code, relocs = module_code
    rom, addr, _ = patch_rom(fake_kickstart(), code, relocs)
    off = addr - ROM_BASE
    tag = rom.index(b"\x4a\xfc", off)
    match_tag, end_skip = struct.unpack_from(">II", rom, tag + 2)
    name, id_string, init = struct.unpack_from(">III", rom, tag + 14)
    assert match_tag == ROM_BASE + tag
    for ptr in (end_skip, name, id_string, init):
        assert addr <= ptr <= addr + len(code)
    name_off = name - ROM_BASE
    assert rom[name_off:rom.index(0, name_off)] == b"ppi2000mem"


def test_checksum_is_valid_and_nothing_else_changes(module_code):
    code, relocs = module_code
    before = fake_kickstart()
    rom, addr, _ = patch_rom(before, code, relocs)
    assert kick_checksum_ok(rom)
    off = addr - ROM_BASE
    changed = [i for i in range(ROM_SIZE) if rom[i] != before[i]]
    outside = [i for i in changed
               if not (off <= i < off + len(code) or CHECKSUM_OFF <= i < CHECKSUM_OFF + 4)]
    assert changed and outside == []


def test_byteswap():
    rom = fake_kickstart()
    swapped = byteswap(rom)
    assert swapped[:4] == bytes.fromhex("1411f94e")
    assert byteswap(swapped) == rom


def test_module_that_does_not_fit_is_refused(module_code):
    code, relocs = module_code
    with pytest.raises(RomError, match="does not fit"):
        patch_rom(fake_kickstart(free_start=CHECKSUM_OFF - 64), code, relocs)


def test_not_a_kickstart_is_refused(module_code):
    code, relocs = module_code
    with pytest.raises(RomError, match="not a 512K"):
        patch_rom(bytes(256 * 1024), code, relocs)


def test_command_line_writes_all_images(module_path, tmp_path):
    kick = tmp_path / "kick.rom"
    kick.write_bytes(fake_kickstart())
    out = tmp_path / "patched"
    subprocess.run([sys.executable, str(ROOT / "tools" / "mkrom.py"), str(kick),
                    str(module_path), str(out)], check=True, capture_output=True)
    rom = (tmp_path / "patched.rom").read_bytes()
    binary = (tmp_path / "patched.bin").read_bytes()
    x4 = (tmp_path / "patched-x4.bin").read_bytes()
    assert kick_checksum_ok(rom)
    assert binary == byteswap(rom)
    assert x4 == binary * 4
