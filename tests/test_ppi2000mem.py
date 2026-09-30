"""Run ppi2000mem's init routine on an emulated 68040 against simulated boards.

The module is assembled from src/, loaded like mkrom.py loads it, and its
RomTag init routine is called the way exec calls it at cold start. Just
enough of AmigaOS is faked for it: ExecBase with AttnFlags and the memory
list, and the library calls it makes, implemented here in Python. The PP&S
card's SIMMs are one host buffer mapped into the 32-bit area, and also at
$00200000 when 24-bit RAM is configured, so the aliasing and mirrors the real
card shows behave the same way here.

Run: make test
"""
import ctypes
import mmap
import struct
from dataclasses import dataclass, field

import pytest
from unicorn import (UC_ARCH_M68K, UC_HOOK_CODE, UC_HOOK_MEM_WRITE,
                     UC_MODE_BIG_ENDIAN, Uc)
from unicorn.m68k_const import (UC_CPU_M68K_M68040, UC_M68K_REG_A0,
                                UC_M68K_REG_A1, UC_M68K_REG_A7, UC_M68K_REG_D0,
                                UC_M68K_REG_D1, UC_M68K_REG_PC)

MB = 1 << 20
CHIP_SIZE = 2 * MB
CODE_ADDR = 0x00F80000
RETURN_ADDR = 0x00F90000          # init "returns" here; emulation stops
EXEC_BASE = 0x00010000
EXP_BASE = 0x00020000
CONFIGDEV_AREA = 0x00030000
MEMNODE_AREA = 0x00040000
STACK_TOP = 0x001F0000
IO_BOARD = 0x00E90000
RAM24 = 0x00200000
RAM32 = 0x08000000
AREA32_END = 0x0A000000           # Init040's probe limit for 4 MB SIMMs

D = [UC_M68K_REG_D0 + i for i in range(8)]
A = [UC_M68K_REG_A0 + i for i in range(8)]
SCRATCH_JUNK = 0xDEADBEEF

# Library vector offsets the module may call, per library.
EXEC_LVOS = {-414: "CloseLibrary", -552: "OpenLibrary", -618: "AddMemList",
             -636: "CacheClearU"}
EXP_LVOS = {-72: "FindConfigDev"}


@dataclass
class Card:
    """How the PP&S 2000/040 is fitted and jumpered."""
    installed_mb: int = 32          # SIMM memory on the card
    ram24_mb: int = 0               # autoconfig (24-bit) RAM jumper: 0, 2, 4, 8
    simms_4mb: bool = True          # jumper B2 / status bit 5
    unpopulated: str = "mirror"     # what the area above the SIMMs does:
                                    # "mirror", "ones" (reads $FFFFFFFF) or
                                    # "lastbus" (reads the last value written)
    io_board: bool = True
    manufacturer: int = 0x7EA


@dataclass
class Machine:
    cpu_040: bool = True
    already_added: bool = False
    card: Card | None = field(default_factory=Card)


class Emulator:
    def __init__(self, code, relocs, machine, entry_regs):
        self.machine = machine
        self.added = []            # (base, size, attributes, priority, name)
        self.alias_writes = []     # writes into the live 24-bit RAM
        self.calls = []
        self.uc = uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
        uc.ctl_set_cpu_model(UC_CPU_M68K_M68040)

        uc.mem_map(0, CHIP_SIZE)
        code = bytearray(code)
        for r in relocs:
            v = struct.unpack_from(">I", code, r)[0]
            struct.pack_into(">I", code, r, v + CODE_ADDR)
        uc.mem_map(CODE_ADDR, 0x20000)
        uc.mem_write(CODE_ADDR, bytes(code))
        self.init_addr = self._find_init(bytes(code))

        self._setup_exec()
        self._setup_library(EXEC_BASE, EXEC_LVOS)
        self._setup_library(EXP_BASE, EXP_LVOS)
        self.configdevs = []
        if machine.card:
            self._setup_card(machine.card)

        # Callee-saved registers get recognisable values; the rest get junk
        # so the module can't rely on what happens to be in them.
        self.saved = {}
        for i in range(8):
            uc.reg_write(D[i], entry_regs + i)
            if i < 7:
                uc.reg_write(A[i], entry_regs + 0x100 + i)
        for r in D[2:8] + A[2:7]:
            self.saved[r] = uc.reg_read(r)
        sp = STACK_TOP - 4
        uc.mem_write(sp, struct.pack(">I", RETURN_ADDR))
        uc.reg_write(UC_M68K_REG_A7, sp)
        self.entry_sp = sp

    # -- setup -------------------------------------------------------------

    def _find_init(self, code):
        tag = code.index(b"\x4a\xfc")
        return struct.unpack_from(">I", code, tag + 22)[0]

    def _setup_exec(self):
        m, uc = self.machine, self.uc
        uc.mem_write(4, struct.pack(">I", EXEC_BASE))
        uc.mem_write(EXEC_BASE + 0x128, struct.pack(">H", 0x0F if m.cpu_040 else 0))
        # Empty MemList: lh_Head -> lh_Tail, lh_Tail = 0, lh_TailPred -> lh_Head
        head, tail = EXEC_BASE + 0x142, EXEC_BASE + 0x146
        uc.mem_write(head, struct.pack(">III", tail, 0, head))
        if m.already_added:
            node = MEMNODE_AREA
            name = node + 0x40
            uc.mem_write(name, b"PPI 32Bit RAM\0")
            uc.mem_write(node, struct.pack(">II", tail, head))
            uc.mem_write(node + 10, struct.pack(">I", name))
            uc.mem_write(head, struct.pack(">I", node))

    def _setup_library(self, base, lvos):
        # Each vector slot holds RTS; a code hook runs the Python version of
        # the call just before that RTS executes.
        for off in lvos:
            self.uc.mem_write(base + off, b"\x4e\x75")
        self.uc.hook_add(UC_HOOK_CODE, self._library_call, (base, lvos),
                         base - 0x400, base - 1)

    def _add_configdev(self, er_type, product, manufacturer, addr, size):
        cd = CONFIGDEV_AREA + len(self.configdevs) * 0x100
        self.uc.mem_write(cd + 0x10, bytes([er_type, product]))
        self.uc.mem_write(cd + 0x14, struct.pack(">H", manufacturer))
        self.uc.mem_write(cd + 0x20, struct.pack(">II", addr, size))
        self.configdevs.append((cd, manufacturer, product))

    def _setup_card(self, card):
        uc = self.uc
        # A board that isn't ours, configured first, to make sure it's skipped.
        self._add_configdev(0xC1, 0x03, 514, 0x00EA0000, 0x10000)

        ram24 = card.ram24_mb * MB
        if card.io_board:
            uc.mem_map(IO_BOARD, 0x10000)
            status = 0xA0 if card.simms_4mb else 0x80
            uc.mem_write(IO_BOARD + 3, bytes([status]))
            self._add_configdev(0xC1, 0x69, card.manufacturer, IO_BOARD, 0x10000)
        if ram24:
            size_code = {2: 6, 4: 7, 8: 0}[card.ram24_mb]
            self._add_configdev(0xE0 | size_code, 0x69, card.manufacturer, RAM24, ram24)

        # The SIMMs: one buffer, linear from $08000000. The 24-bit RAM is the
        # part at $08200000, also mapped at $00200000.
        installed = card.installed_mb * MB
        # Unicorn needs page-aligned host memory; an anonymous mmap is.
        self.simms = mmap.mmap(-1, installed)
        ptr = ctypes.addressof(ctypes.c_char.from_buffer(self.simms))
        uc.mem_map_ptr(RAM32, installed, 7, ptr)
        if ram24:
            uc.mem_map_ptr(RAM24, ram24, 7, ptr + 2 * MB)
            alias = RAM32 + 2 * MB
            uc.hook_add(UC_HOOK_MEM_WRITE, self._alias_write, None,
                        alias, alias + ram24 - 1)

        addr = RAM32 + installed
        while addr < AREA32_END:
            size = min(installed, AREA32_END - addr)
            if card.unpopulated == "mirror":
                uc.mem_map_ptr(addr, size, 7, ptr)
            else:
                self._open_bus(addr, size, card.unpopulated)
            addr += size

    def _open_bus(self, addr, size, kind):
        last = [0]

        def read(uc, offset, size, user):
            return 0xFFFFFFFF if kind == "ones" else last[0]

        def write(uc, offset, size, value, user):
            last[0] = value

        self.uc.mmio_map(addr, size, read, None, write, None)

    # -- hooks -------------------------------------------------------------

    def _alias_write(self, uc, access, address, size, value, user):
        self.alias_writes.append(address)

    def _library_call(self, uc, address, size, user):
        base, lvos = user
        off = address - base
        name = lvos.get(off)
        if name is None:
            raise AssertionError(f"unexpected call {off} on library at ${base:x}")
        self.calls.append(name)
        getattr(self, "_lib_" + name)()
        # AmigaOS calls may trash d0/d1/a0/a1; do so, so the module can't
        # rely on them surviving a call.
        for r in (UC_M68K_REG_D1, UC_M68K_REG_A0, UC_M68K_REG_A1):
            uc.reg_write(r, SCRATCH_JUNK)

    def _cstr(self, addr):
        out = bytearray()
        while (c := self.uc.mem_read(addr + len(out), 1)[0]):
            out.append(c)
        return out.decode("latin-1")

    def _set_d0(self, v):
        self.uc.reg_write(UC_M68K_REG_D0, v & 0xFFFFFFFF)

    def _lib_OpenLibrary(self):
        name = self._cstr(self.uc.reg_read(UC_M68K_REG_A1))
        self._set_d0(EXP_BASE if name == "expansion.library" else 0)

    def _lib_CloseLibrary(self):
        self._set_d0(SCRATCH_JUNK)

    def _lib_CacheClearU(self):
        self._set_d0(SCRATCH_JUNK)

    def _lib_AddMemList(self):
        r = self.uc.reg_read
        self.added.append((r(A[0]), r(D[0]), r(D[1]), r(D[2]),
                           self._cstr(r(A[1]))))
        self._set_d0(SCRATCH_JUNK)

    def _lib_FindConfigDev(self):
        r = self.uc.reg_read
        old, manu, prod = r(A[0]), r(D[0]), r(D[1])
        found = old == 0
        for cd, m, p in self.configdevs:
            if not found:
                found = cd == old
                continue
            if manu in (m, 0xFFFFFFFF) and prod in (p, 0xFFFFFFFF):
                self._set_d0(cd)
                return
        self._set_d0(0)

    # -- run ---------------------------------------------------------------

    def run(self):
        self.uc.emu_start(self.init_addr, RETURN_ADDR, count=5_000_000)
        uc = self.uc
        assert uc.reg_read(UC_M68K_REG_PC) == RETURN_ADDR, "init did not return"
        assert uc.reg_read(UC_M68K_REG_A7) == self.entry_sp + 4, "stack unbalanced"
        for reg, value in self.saved.items():
            assert uc.reg_read(reg) == value, "a callee-saved register changed"
        return self


def run(module_code, machine, entry_regs=0x11110000):
    code, relocs = module_code
    return Emulator(code, relocs, machine, entry_regs).run()


def block(base, mb, name="PPI 32Bit RAM"):
    return (base, mb * MB, 5, 30, name)


# Register contents at entry are whatever exec left there; try two extremes
# so a register the module forgets to set is caught either way.
ENTRY = pytest.mark.parametrize("entry_regs", [0x00000000, 0xFFFFF000])


@ENTRY
def test_0mb_autoconfig_32mb_is_one_block(module_code, entry_regs):
    emu = run(module_code, Machine(card=Card(installed_mb=32)), entry_regs)
    assert emu.added == [block(RAM32, 32)]


@ENTRY
def test_2mb_autoconfig_skips_the_24bit_alias(module_code, entry_regs):
    emu = run(module_code, Machine(card=Card(installed_mb=32, ram24_mb=2)), entry_regs)
    assert emu.added == [block(RAM32, 2), block(0x08400000, 28, "PPI 32Bit RAM ][")]
    assert emu.alias_writes == []


@ENTRY
@pytest.mark.parametrize("unpopulated", ["mirror", "ones", "lastbus"])
def test_16mb_stops_at_the_end_of_the_simms(module_code, entry_regs, unpopulated):
    card = Card(installed_mb=16, unpopulated=unpopulated)
    emu = run(module_code, Machine(card=card), entry_regs)
    assert emu.added == [block(RAM32, 16)]


@ENTRY
@pytest.mark.parametrize("unpopulated", ["mirror", "ones", "lastbus"])
def test_16mb_with_2mb_autoconfig(module_code, entry_regs, unpopulated):
    card = Card(installed_mb=16, ram24_mb=2, unpopulated=unpopulated)
    emu = run(module_code, Machine(card=card), entry_regs)
    assert emu.added == [block(RAM32, 2), block(0x08400000, 12, "PPI 32Bit RAM ][")]
    assert emu.alias_writes == []


def test_1mb_simms_stop_at_8mb(module_code):
    card = Card(installed_mb=8, simms_4mb=False, unpopulated="ones")
    emu = run(module_code, Machine(card=card))
    assert emu.added == [block(RAM32, 8)]


def test_old_manufacturer_id_is_accepted(module_code):
    emu = run(module_code, Machine(card=Card(manufacturer=0x2F4)))
    assert emu.added == [block(RAM32, 32)]


def test_68000_mode_adds_nothing(module_code):
    emu = run(module_code, Machine(cpu_040=False))
    assert emu.added == [] and emu.calls == []


def test_already_added_adds_nothing(module_code):
    emu = run(module_code, Machine(already_added=True))
    assert emu.added == []
    assert "OpenLibrary" not in emu.calls


def test_no_card_adds_nothing(module_code):
    emu = run(module_code, Machine(card=None))
    assert emu.added == []
    assert emu.calls.count("OpenLibrary") == emu.calls.count("CloseLibrary")
