"""Run ppiload on an emulated 68040 and check what it leaves for the next reset.

ppiload replaces LoadModule for our module: it copies the module into chip
RAM, fixes its RomTag pointers, and links it into ExecBase's KickMemPtr and
KickTagPtr lists before rebooting. Exec only honours those lists at reset if
they're built exactly right, so these tests check the structures themselves.
"""
import struct

import pytest
from unicorn import UC_ARCH_M68K, UC_HOOK_CODE, UC_MODE_BIG_ENDIAN, Uc
from unicorn.m68k_const import (UC_CPU_M68K_M68040, UC_M68K_REG_A0,
                                UC_M68K_REG_A1, UC_M68K_REG_A7, UC_M68K_REG_D0,
                                UC_M68K_REG_D1)

CHIP_SIZE = 2 << 20
PROG_ADDR = 0x00100000
RETURN_ADDR = 0x001FF000
STACK_TOP = 0x001F0000
EXEC_BASE = 0x00010000
DOS_BASE = 0x00020000
HEAP = 0x00080000
OLD_KICKMEM = 0x00040000
OLD_KICKTAGS = 0x00041000
KICKMEM, KICKTAG, KICKSUM = 0x222, 0x226, 0x22A
CHECKSUM = 0x5EC0DE42

EXEC_LVOS = {-96: "FindResident", -132: "Forbid", -198: "AllocMem",
             -414: "CloseLibrary", -552: "OpenLibrary", -612: "SumKickData",
             -624: "CopyMem", -636: "CacheClearU", -726: "ColdReboot"}
DOS_LVOS = {-198: "Delay", -948: "PutStr"}


class Loader:
    def __init__(self, code, relocs, resident=False, old_kick=False):
        self.resident = resident
        self.output = ""
        self.calls = []
        self.heap = HEAP
        self.sum_state = None
        uc = self.uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
        uc.ctl_set_cpu_model(UC_CPU_M68K_M68040)
        uc.mem_map(0, CHIP_SIZE)
        code = bytearray(code)
        for r in relocs:
            v = struct.unpack_from(">I", code, r)[0]
            struct.pack_into(">I", code, r, v + PROG_ADDR)
        uc.mem_write(PROG_ADDR, bytes(code))
        uc.mem_write(4, struct.pack(">I", EXEC_BASE))
        if old_kick:
            self.w32(EXEC_BASE + KICKMEM, OLD_KICKMEM)
            self.w32(EXEC_BASE + KICKTAG, OLD_KICKTAGS)
        for base, lvos in ((EXEC_BASE, EXEC_LVOS), (DOS_BASE, DOS_LVOS)):
            for off in lvos:
                uc.mem_write(base + off, b"\x4e\x75")          # rts
            uc.hook_add(UC_HOOK_CODE, self._call, (base, lvos), base - 0x400, base - 1)
        sp = STACK_TOP - 4
        self.w32(sp, RETURN_ADDR)
        uc.reg_write(UC_M68K_REG_A7, sp)

    def r32(self, addr):
        return struct.unpack(">I", self.uc.mem_read(addr, 4))[0]

    def w32(self, addr, value):
        self.uc.mem_write(addr, struct.pack(">I", value))

    def cstr(self, addr):
        out = bytearray()
        while (c := self.uc.mem_read(addr + len(out), 1)[0]):
            out.append(c)
        return out.decode("latin-1")

    def _call(self, uc, address, size, user):
        base, lvos = user
        name = lvos.get(address - base)
        if name is None:
            raise AssertionError(f"unexpected call {address - base} on ${base:x}")
        self.calls.append(name)
        r = uc.reg_read
        d0 = 0
        if name == "OpenLibrary":
            d0 = DOS_BASE if self.cstr(r(UC_M68K_REG_A1)) == "dos.library" else 0
        elif name == "FindResident":
            d0 = 0x00F80004 if self.resident else 0
        elif name == "AllocMem":
            size, flags = r(UC_M68K_REG_D0), r(UC_M68K_REG_D1)
            assert flags & 2, "KickMem must be chip RAM: nothing else exists at reset"
            d0, self.heap = self.heap, self.heap + ((size + 7) & ~7)
            uc.mem_write(d0, b"\xAA" * size if not flags & 0x10000 else bytes(size))
        elif name == "CopyMem":
            src, dst, n = r(UC_M68K_REG_A0), r(UC_M68K_REG_A1), r(UC_M68K_REG_D0)
            uc.mem_write(dst, bytes(uc.mem_read(src, n)))
        elif name == "SumKickData":
            self.sum_state = (self.r32(EXEC_BASE + KICKMEM), self.r32(EXEC_BASE + KICKTAG))
            d0 = CHECKSUM
        elif name == "PutStr":
            self.output += self.cstr(r(UC_M68K_REG_D1))
        elif name == "ColdReboot":
            uc.emu_stop()
        uc.reg_write(UC_M68K_REG_D0, d0)

    def run(self):
        self.uc.emu_start(PROG_ADDR, RETURN_ADDR, count=2_000_000)
        return self


@pytest.mark.parametrize("old_kick", [False, True])
def test_install_builds_the_reset_lists(ppiload_code, old_kick):
    ld = Loader(*ppiload_code, old_kick=old_kick).run()
    assert ld.calls[-1] == "ColdReboot"
    assert "Installing ppi2000mem 1.1" in ld.output

    block = ld.r32(EXEC_BASE + KICKMEM)
    assert block == HEAP
    # MemList: chained to the old list, one entry covering the whole block
    assert ld.r32(block) == (OLD_KICKMEM if old_kick else 0)
    assert struct.unpack(">H", ld.uc.mem_read(block + 14, 2))[0] == 1
    assert ld.r32(block + 16) == block
    length = ld.r32(block + 20)

    # KickTag table: our RomTag, then a link to the old table, then 0
    table = ld.r32(EXEC_BASE + KICKTAG)
    tag = ld.r32(table)
    assert ld.r32(table + 4) == ((OLD_KICKTAGS | 0x80000000) if old_kick else 0)
    assert ld.r32(table + 8) == 0

    # The RomTag is relocated to where the module now lives
    assert block < tag < block + length
    assert struct.unpack(">H", ld.uc.mem_read(tag, 2))[0] == 0x4AFC
    assert ld.r32(tag + 2) == tag
    assert ld.cstr(ld.r32(tag + 14)) == "ppi2000mem"
    assert ld.cstr(ld.r32(tag + 18)).startswith("ppi2000mem 1.1")
    for off in (6, 14, 18, 22):
        assert block < ld.r32(tag + off) <= block + length

    # The checksum is taken after both lists are in place, and stored
    assert ld.sum_state == (block, table)
    assert ld.r32(EXEC_BASE + KICKSUM) == CHECKSUM
    assert ld.calls.index("Forbid") < ld.calls.index("SumKickData")


def test_already_resident_changes_nothing(ppiload_code):
    ld = Loader(*ppiload_code, resident=True).run()
    assert "already resident" in ld.output
    assert "AllocMem" not in ld.calls and "ColdReboot" not in ld.calls
    assert ld.r32(EXEC_BASE + KICKMEM) == 0 and ld.r32(EXEC_BASE + KICKTAG) == 0
    assert ld.uc.reg_read(UC_M68K_REG_D0) == 5
