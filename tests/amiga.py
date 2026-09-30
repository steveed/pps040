"""A small fake Amiga for running this project's 68k code under Unicorn.

Just enough of AmigaOS is faked: ExecBase with AttnFlags and a memory list of
real MemHeader structures, and the library calls our code makes, implemented
in Python. Each library vector slot holds an RTS; a code hook runs the Python
version of the call just before that RTS executes, then overwrites d1/a0/a1
as real calls may, so the code under test can't rely on them.

The PP&S card's SIMMs are one host buffer mapped into the 32-bit area, and also
at $00200000 when 24-bit RAM is configured, so the aliasing and mirrors the
real card shows behave the same way here.
"""
import ctypes
import mmap
import re
import struct
from dataclasses import dataclass, field

from unicorn import (UC_ARCH_M68K, UC_HOOK_CODE, UC_HOOK_MEM_WRITE,
                     UC_MODE_BIG_ENDIAN, Uc)
from unicorn.m68k_const import (UC_CPU_M68K_M68040, UC_M68K_REG_A0,
                                UC_M68K_REG_A1, UC_M68K_REG_A7, UC_M68K_REG_D0,
                                UC_M68K_REG_D1, UC_M68K_REG_D2, UC_M68K_REG_PC)

MB = 1 << 20
CHUNK = 2 * MB
CHIP_SIZE = 2 * MB
EXEC_BASE = 0x00010000
EXP_BASE = 0x00020000
DOS_BASE = 0x00028000
CONFIGDEV_AREA = 0x00030000
MEMNODE_AREA = 0x00040000
RESIDENT_AREA = 0x00048000
STACK_TOP = 0x001F0000
CODE_ADDR = 0x00F80000            # programs and modules are loaded here
RETURN_ADDR = 0x00FF0000          # the code "returns" here; emulation stops
IO_BOARD = 0x00E90000
RAM24 = 0x00200000
RAM32 = 0x08000000
AREA32_END = 0x0A000000           # Init040's probe limit for 4 MB SIMMs

D = [UC_M68K_REG_D0 + i for i in range(8)]
A = [UC_M68K_REG_A0 + i for i in range(8)]
SCRATCH_JUNK = 0xDEADBEEF

MEMF_PUBLIC, MEMF_CHIP, MEMF_FAST, MEMF_LOCAL, MEMF_24BITDMA, MEMF_KICK = 1, 2, 4, 0x100, 0x200, 0x400

LIBRARIES = {
    EXEC_BASE: {-30: "Supervisor", -96: "FindResident", -120: "Disable", -126: "Enable",
                -132: "Forbid", -138: "Permit", -414: "CloseLibrary", -534: "TypeOfMem",
                -552: "OpenLibrary", -618: "AddMemList", -636: "CacheClearU"},
    EXP_BASE: {-72: "FindConfigDev"},
    DOS_BASE: {-954: "VPrintf"},
}


@dataclass
class Card:
    """How the PP&S 2000/040 is fitted and jumpered."""
    installed_mb: int = 32          # SIMM memory on the card
    ram24_mb: int = 0               # autoconfig (24-bit) RAM jumper: 0, 2, 4, 8
    simms_4mb: bool = True          # jumper B2 / status bit 5
    unpopulated: str = "mirror"     # what the area above the SIMMs does:
                                    # "mirror", "ones" (reads $FFFFFFFF) or
                                    # "lastbus" (reads the last value written)
    faulty_chunk: int | None = None # a 2 MB chunk where every other long fails
    io_board: bool = True
    manufacturer: int = 0x7EA


@dataclass
class Region:
    """An entry in exec's memory list."""
    lower: int
    upper: int
    attributes: int
    priority: int
    name: str


@dataclass
class Machine:
    cpu_040: bool = True
    mmu_on: bool = False
    card: Card | None = field(default_factory=Card)
    memory: list = field(default_factory=list)      # extra Regions, e.g. added RAM
    resident: str | None = None                     # id string of a resident ppi2000mem


def load_hunks(path, base):
    """Load an AmigaOS executable, segment n at base + n * 64K, relocated.

    Returns [(address, bytes)] per segment.
    """
    raw = open(path, "rb").read()
    pos = 0

    def u32():
        nonlocal pos
        pos += 4
        return struct.unpack_from(">I", raw, pos - 4)[0]

    def u16():
        nonlocal pos
        pos += 2
        return struct.unpack_from(">H", raw, pos - 2)[0]

    assert u32() == 0x3F3 and u32() == 0
    count, first, last = u32(), u32(), u32()
    sizes = [(u32() & 0x3FFFFFFF) * 4 for _ in range(first, last + 1)]
    segs, relocs = [], []
    while pos < len(raw):
        t = u32() & 0x3FFFFFFF
        if t in (0x3E9, 0x3EA):                         # CODE, DATA
            n = u32() * 4
            data = bytearray(raw[pos:pos + n]) + bytes(sizes[len(segs)] - n)
            pos += n
            segs.append(data)
            relocs.append([])
        elif t == 0x3EB:                                # BSS
            u32()
            segs.append(bytearray(sizes[len(segs)]))
            relocs.append([])
        elif t == 0x3EC:                                # RELOC32
            while (n := u32()):
                target = u32()
                relocs[-1] += [(u32(), target) for _ in range(n)]
        elif t in (0x3FC, 0x3F7):                       # RELOC32SHORT, DREL32
            while (n := u16()):
                target = u16()
                relocs[-1] += [(u16(), target) for _ in range(n)]
            if pos & 2:
                pos += 2
        elif t in (0x3F0, 0x3F1):                       # SYMBOL, DEBUG
            if t == 0x3F1:
                pos += u32() * 4
            else:
                while (n := u32()):
                    pos += n * 4 + 4
        elif t != 0x3F2:                                # END
            raise ValueError(f"unhandled hunk {t:#x}")
    addrs = [base + i * 0x10000 for i in range(len(segs))]
    for seg, rels in zip(segs, relocs):
        for off, target in rels:
            v = struct.unpack_from(">I", seg, off)[0]
            struct.pack_into(">I", seg, off, v + addrs[target])
    return list(zip(addrs, map(bytes, segs)))


def rawdofmt(fmt, next_arg, read_cstr):
    """exec's RawDoFmt: %[-][0][width][.limit][l]{d,u,x,s,c,%}.

    Without "l", numbers are 16-bit; %s always takes a 32-bit pointer.
    """
    def one(m):
        left, zero, width, limit, long_, kind = m.groups()
        if kind == "%":
            return "%"
        if kind == "s":
            text = read_cstr(next_arg(4))
            if limit:
                text = text[:int(limit)]
        else:
            v = next_arg(4 if long_ else 2)
            bits = 32 if long_ else 16
            if kind == "d" and v >= 1 << (bits - 1):
                v -= 1 << bits
            text = {"d": str, "u": str, "x": lambda x: f"{x:X}", "c": chr}[kind](v)
        width = int(width or 0)
        if left:
            return text.ljust(width)
        return text.rjust(width, "0" if zero else " ")

    return re.sub(r"%(-)?(0)?(\d+)?(?:\.(\d+))?(l)?([dusxc%])", one, fmt)


class Amiga:
    def __init__(self, machine, entry_regs=0x11110000):
        self.machine = machine
        self.added = []            # AddMemList calls: (base, size, attributes, priority, name)
        self.alias_writes = []     # writes into the live 24-bit RAM
        self.card_writes = []      # writes anywhere on the card's 32-bit area
        self.calls = []
        self.output = ""
        self.configdevs = []
        self.regions = []
        uc = self.uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
        uc.ctl_set_cpu_model(UC_CPU_M68K_M68040)
        uc.mem_map(0, CHIP_SIZE)
        uc.mem_map(CODE_ADDR, RETURN_ADDR + 0x10000 - CODE_ADDR)

        uc.mem_write(4, struct.pack(">I", EXEC_BASE))
        uc.mem_write(EXEC_BASE + 0x128, struct.pack(">H", 0x0F if machine.cpu_040 else 0))
        for base, lvos in LIBRARIES.items():
            for off in lvos:
                uc.mem_write(base + off, b"\x4e\x75")
            uc.hook_add(UC_HOOK_CODE, self._library_call, (base, lvos), base - 0x400, base - 1)

        self._add_region(Region(0x1020, CHIP_SIZE, 0x0703, -10, "chip memory"))
        if machine.card:
            self._setup_card(machine.card)
        for region in machine.memory:
            self._add_region(region)
        self._build_memlist()

        # Callee-saved registers get recognisable values; the rest get junk
        # so the code can't rely on what happens to be in them.
        for i in range(8):
            uc.reg_write(D[i], entry_regs + i)
            if i < 7:
                uc.reg_write(A[i], entry_regs + 0x100 + i)
        self.saved = {r: uc.reg_read(r) for r in D[2:8] + A[2:7]}
        self.entry_sp = STACK_TOP - 4
        uc.mem_write(self.entry_sp, struct.pack(">I", RETURN_ADDR))
        uc.reg_write(UC_M68K_REG_A7, self.entry_sp)

    # -- loading and running ------------------------------------------------

    def load_module(self, code, relocs):
        """Place a single-hunk module at CODE_ADDR; return its RomTag init."""
        code = bytearray(code)
        for r in relocs:
            v = struct.unpack_from(">I", code, r)[0]
            struct.pack_into(">I", code, r, v + CODE_ADDR)
        self.uc.mem_write(CODE_ADDR, bytes(code))
        tag = code.index(b"\x4a\xfc")
        return struct.unpack_from(">I", code, tag + 22)[0]

    def load_program(self, path):
        """Load an executable at CODE_ADDR; return its entry point."""
        segs = load_hunks(path, CODE_ADDR)
        for addr, data in segs:
            self.uc.mem_write(addr, data)
        return segs[0][0]

    def run(self, entry):
        uc = self.uc
        uc.emu_start(entry, RETURN_ADDR, count=5_000_000)
        assert uc.reg_read(UC_M68K_REG_PC) == RETURN_ADDR, "the code did not return"
        assert uc.reg_read(UC_M68K_REG_A7) == self.entry_sp + 4, "stack unbalanced"
        for reg, value in self.saved.items():
            assert uc.reg_read(reg) == value, "a callee-saved register changed"
        return self

    # -- the machine --------------------------------------------------------

    def _add_region(self, region):
        self.regions.append(region)

    def _build_memlist(self):
        """exec's MemList, highest priority first, of real MemHeaders."""
        head, tail = EXEC_BASE + 0x142, EXEC_BASE + 0x146
        nodes = sorted(self.regions, key=lambda r: -r.priority)
        addrs = [MEMNODE_AREA + i * 0x100 for i in range(len(nodes))]
        for i, (addr, r) in enumerate(zip(addrs, nodes)):
            succ = addrs[i + 1] if i + 1 < len(nodes) else tail
            pred = addrs[i - 1] if i else head
            name = addr + 0x40
            self.uc.mem_write(name, r.name.encode("latin-1") + b"\0")
            self.uc.mem_write(addr, struct.pack(">IIBbI", succ, pred, 10, r.priority, name))
            self.uc.mem_write(addr + 14, struct.pack(">HIII", r.attributes, 0,
                                                     r.lower, r.upper))
        first = addrs[0] if nodes else tail
        last = addrs[-1] if nodes else head
        self.uc.mem_write(head, struct.pack(">III", first, 0, last))

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
            status = (0x20 if card.simms_4mb else 0) | 0x80
            uc.mem_write(IO_BOARD + 3, bytes([status]))
            self._add_configdev(0xC1, 0x69, card.manufacturer, IO_BOARD, 0x10000)
        if ram24:
            size_code = {2: 6, 4: 7, 8: 0}[card.ram24_mb]
            self._add_configdev(0xE0 | size_code, 0x69, card.manufacturer, RAM24, ram24)
            self._add_region(Region(RAM24 + 0x20, RAM24 + ram24, MEMF_PUBLIC | MEMF_FAST
                                    | MEMF_24BITDMA | MEMF_KICK, 0, "expansion memory"))

        # The SIMMs: one buffer, linear from $08000000, mapped chunk by chunk.
        # The 24-bit RAM is the part at $08200000, also mapped at $00200000.
        installed = card.installed_mb * MB
        # Unicorn needs page-aligned host memory; an anonymous mmap is.
        self.simms = mmap.mmap(-1, installed)
        ptr = ctypes.addressof(ctypes.c_char.from_buffer(self.simms))
        for i in range(installed // CHUNK):
            addr = RAM32 + i * CHUNK
            if i == card.faulty_chunk:
                self._faulty(addr)
            else:
                uc.mem_map_ptr(addr, CHUNK, 7, ptr + i * CHUNK)
        if ram24:
            uc.mem_map_ptr(RAM24, ram24, 7, ptr + 2 * MB)
            alias = RAM32 + 2 * MB
            uc.hook_add(UC_HOOK_MEM_WRITE, self._alias_write, None, alias, alias + ram24 - 1)
        uc.hook_add(UC_HOOK_MEM_WRITE, self._card_write, None, RAM32, AREA32_END - 1)

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

    def _faulty(self, addr):
        """A chunk where writes to every other long are lost."""
        store = {}

        def read(uc, offset, size, user):
            return store.get(offset, 0)

        def write(uc, offset, size, value, user):
            if not (offset // 4) % 2:
                store[offset] = value

        self.uc.mmio_map(addr, CHUNK, read, None, write, None)

    # -- hooks --------------------------------------------------------------

    def _alias_write(self, uc, access, address, size, value, user):
        self.alias_writes.append(address)

    def _card_write(self, uc, access, address, size, value, user):
        self.card_writes.append(address)

    def _library_call(self, uc, address, size, user):
        base, lvos = user
        name = lvos.get(address - base)
        if name is None:
            raise AssertionError(f"unexpected call {address - base} on library at ${base:x}")
        self.calls.append(name)
        getattr(self, "_lib_" + name)()
        for r in (UC_M68K_REG_D1, UC_M68K_REG_A0, UC_M68K_REG_A1):
            uc.reg_write(r, SCRATCH_JUNK)

    def cstr(self, addr):
        out = bytearray()
        while (c := self.uc.mem_read(addr + len(out), 1)[0]):
            out.append(c)
        return out.decode("latin-1")

    def _d0(self, v):
        self.uc.reg_write(UC_M68K_REG_D0, v & 0xFFFFFFFF)

    def _r(self, reg):
        return self.uc.reg_read(reg)

    # -- exec ---------------------------------------------------------------

    def _lib_Supervisor(self):
        # Only used to read the 040's TC register; bit 15 is "MMU enabled".
        self._d0(0x8000 if self.machine.mmu_on else 0)

    def _lib_FindResident(self):
        name = self.cstr(self._r(A[1]))
        if name != "ppi2000mem" or not self.machine.resident:
            self._d0(0)
            return
        idstring = RESIDENT_AREA + 0x40
        self.uc.mem_write(idstring, self.machine.resident.encode("latin-1") + b"\0")
        self.uc.mem_write(RESIDENT_AREA, struct.pack(">HI", 0x4AFC, RESIDENT_AREA))
        self.uc.mem_write(RESIDENT_AREA + 18, struct.pack(">I", idstring))
        self._d0(RESIDENT_AREA)

    def _lib_TypeOfMem(self):
        addr = self._r(A[1])
        self._d0(next((r.attributes for r in self.regions
                       if r.lower - 0x20 <= addr < r.upper), 0))

    def _lib_OpenLibrary(self):
        name = self.cstr(self._r(A[1]))
        self._d0({"expansion.library": EXP_BASE, "dos.library": DOS_BASE}.get(name, 0))

    def _lib_AddMemList(self):
        self.added.append((self._r(A[0]), self._r(D[0]), self._r(D[1]), self._r(D[2]),
                           self.cstr(self._r(A[1]))))
        self._d0(SCRATCH_JUNK)

    def _no_result(self):
        self._d0(SCRATCH_JUNK)

    _lib_Disable = _lib_Enable = _lib_Forbid = _lib_Permit = _no_result
    _lib_CloseLibrary = _lib_CacheClearU = _no_result

    # -- expansion ----------------------------------------------------------

    def _lib_FindConfigDev(self):
        old, manu, prod = self._r(A[0]), self._r(D[0]), self._r(D[1])
        found = old == 0
        for cd, m, p in self.configdevs:
            if not found:
                found = cd == old
                continue
            if manu in (m, 0xFFFFFFFF) and prod in (p, 0xFFFFFFFF):
                self._d0(cd)
                return
        self._d0(0)

    # -- dos ----------------------------------------------------------------

    def _lib_VPrintf(self):
        args = [self._r(UC_M68K_REG_D2)]

        def next_arg(size):
            v = int.from_bytes(self.uc.mem_read(args[0], size), "big")
            args[0] += size
            return v

        self.output += rawdofmt(self.cstr(self._r(UC_M68K_REG_D1)), next_arg, self.cstr)
        self._d0(0)
