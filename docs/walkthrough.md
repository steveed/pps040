# A walkthrough of the assembly, for Python developers

`src/ppi2000mem.asm` (the ROM module) and `src/ppiload.asm` (its installer) are 68000-family
assembly. This guide explains them for someone who knows Python but not 68k assembly or AmigaOS
internals, by translating each routine into Python-like pseudocode.

## 1. The big picture

At power-on, exec (the kernel in ROM) scans the ROM for the magic word `$4AFC`. Each hit starts a
**RomTag**: a small struct that describes a module with its name, a priority and a pointer to an
`init` function. Exec sorts the modules by priority and calls each `init` in turn, much like a
plugin registry calling `setup()` on every registered plugin.

ppi2000mem has priority 105, so it runs straight after `expansion.library` (priority 110) has
configured the Zorro boards, and long before DOS starts. Its `init` finds the PP&S card, tests the
card's RAM, and calls `AddMemList()` to give that RAM to the system. To the rest of the system the
memory looks as if it had been there from the start.

## 2. A 68k crash course

**Registers** are the CPU's local variables. There are exactly 16:

- `d0`–`d7`, data registers: think of them as ints.
- `a0`–`a7`, address registers: think of them as pointers. `a7` is the stack pointer, `sp`.

**Sizes.** Every instruction has a size suffix: `.b` is 8 bits, `.w` 16, `.l` 32.
`move.l d0,d1` is `d1 = d0`. Note the order: source first, destination second.

**Operands.** `$` means hex and `#` a literal value:

| Syntax     | Meaning                                                | Python-ish                   |
|------------|--------------------------------------------------------|------------------------------|
| `#5`       | the number 5                                           | `5`                          |
| `d0`       | register                                               | `d0`                         |
| `(a0)`     | memory at the address in a0                            | `mem[a0]`                    |
| `$10(a2)`  | memory at a2 + $10                                     | `mem[a2 + 0x10]`: a struct field |
| `(a0)+`    | `mem[a0]`, then add the operand size to a0             | `*p++` in C                  |
| `-(sp)`    | subtract from sp first, then access: a push            | `stack.append(...)`          |
| `name(pc)` | the address of `name`, relative to this code           | position-independent address |

**Flags and branches.** Most instructions set condition flags as a side effect. The one that
matters here is **Z**, "the result was zero" or "equal". `beq` jumps if Z is set, `bne` if it's
clear. Several helper routines here **return their result in the Z flag**: a boolean return value
without a variable.

**Labels.** A label such as `.scan:` is just a name for an address; `.name` labels are local to
the routine above them. Execution runs straight on from one instruction to the next, past labels,
until a branch, a `jsr`/`bsr` (call) or an `rts` (return).

**Calling convention (AmigaOS).** Arguments go in specific registers, not in a parameter list.
The result comes back in `d0`. Calls may destroy `d0`, `d1`, `a0` and `a1`, so treat those as
temporaries. Every other register must come back unchanged, which is why `init` starts with
`movem.l d2-d7/a2-a6,-(sp)` (push all of them) and ends by popping them back.

**Library calls** look like `jsr _LVOAddMemList(a6)`. A library base (in `a6`) has a table of jump
instructions at negative offsets below it; `-618(a6)` is the `AddMemList` slot. It's
`exec.vtable[-618](...)`. The `_LVO…` constants are those offsets.

**Loops.** `dbf d1,.loop` decrements d1 and jumps back until it passes zero, so with `d1 = 63` it's
`for _ in range(64)`. `dbne` is the same but also stops early when Z is clear, like a `break` on a
mismatch.

## 3. The module, section by section

### Constants

```asm
AttnFlags               equ $128
cd_BoardAddr            equ $20
```

`equ` defines a constant. Most of these are field offsets in AmigaOS structs: "AttnFlags is at byte
0x128 of ExecBase", "BoardAddr is at 0x20 of a ConfigDev". It's the same idea as a
`ctypes.Structure` layout, written as raw numbers.

### `start`

```asm
start:  moveq   #-1,d0
        rts
```

If someone runs the file from the Shell, it returns an error straight away: the equivalent of
`if __name__ == "__main__": sys.exit(1)`.

### `romtag`

```asm
romtag: dc.w    RTC_MATCHWORD
        dc.l    romtag
        dc.l    endskip
        dc.b    RTF_COLDSTART,VERSION,NT_UNKNOWN,PRIORITY
        dc.l    name
        dc.l    idstring
        dc.l    init
```

This is data, not code: `dc.w`, `dc.b` and `dc.l` emit raw words, bytes and longs. In Python terms,
a struct literal:

```python
RomTag(match=0x4AFC, match_tag=<its own address>, end_skip=endskip,
       flags=RTF_COLDSTART, version=1, type=NT_UNKNOWN, priority=105,
       name="ppi2000mem", id_string="ppi2000mem 1.1 (29.9.2026)\r\n", init=init)
```

The pointer back to itself is how exec tells a real RomTag from a random `$4AFC` in some data.
These five pointers are the module's only absolute addresses. When `tools/mkrom.py` places the
module in the ROM, or `ppiload` copies it into RAM, those five are adjusted to the new address;
everything else in the module is position-independent.

### `init`

The whole routine, translated to Python. The comments give the register that holds each variable.

```python
def init():
    save_callee_registers()                        # movem.l d2-d7/a2-a6,-(sp)
    exec = peek32(4)                               # ExecBase always lives at address 4
    if not exec.AttnFlags & AFF_68040:             # card switched to 68000 mode:
        return                                     #   $08000000 doesn't exist
    if findmem("PPI 32Bit RAM"):                   # already added (e.g. an old Init040)
        return

    expansion = OpenLibrary("expansion.library", 36)
    ram24_size, simms_4mb, found = 0, True, False      # d5, d6, d7
    cd = None                                          # a2
    while cd := FindConfigDev(cd, -1, -1):             # every Zorro board
        if cd.product != 0x69 or cd.manufacturer not in (2026, 756):
            continue
        found = True
        if cd.er_Type & ERTF_MEMLIST:                  # the 24-bit RAM board
            ram24_size = cd.BoardSize
        else:                                          # the 64K I/O board
            simms_4mb = bool(peek8(cd.BoardAddr + 3) & 0x20)   # the jumper byte
    CloseLibrary(expansion)
    if not found:
        return

    # The 24-bit RAM also shows up at $08200000, so the main block starts after it.
    base = 0x08000000 if ram24_size == 0 else 0x08200000 + ram24_size    # d4
    low_ok = False                                     # a5
    if ram24_size:
        if not testchunk(0x08000000):      # the 2 MB below the alias
            return                         # odd board: going on could hit the 24-bit RAM
        low_ok = True

    end = base                                         # a3
    limit = 0x0A000000 if simms_4mb else 0x08800000
    if simms_4mb or ram24_size != 8 * MB:  # 1 MB SIMMs with 8 MB autoconfig: nothing left
        while True:
            if not testchunk(end):                     # nothing (usable) here
                break
            if not checkall(low_ok, base, end):        # writing here clobbered an earlier
                break                                  #   chunk: it's a mirror
            end += CHUNK                               # 2 MB
            if end >= limit:
                break

    if low_ok:
        AddMemList(2 * MB, MEMF_PUBLIC | MEMF_FAST, 30, 0x08000000, "PPI 32Bit RAM")
    if end > base:
        name = "PPI 32Bit RAM ][" if low_ok else "PPI 32Bit RAM"
        AddMemList(end - base, MEMF_PUBLIC | MEMF_FAST, 30, base, name)
    restore_callee_registers()
```

In the assembly, each `if` is "test something, then `beq`/`bne` to a label", and the shared
`return` is the `.done` label. The `while` loop is the block from `.probe` to `.limit`, which jumps
back to `.probe` with `bcs` ("branch if carry set", which after `cmpa.l` means "less than").

Priority 30 matters: the 24-bit RAM that expansion.library added has priority 0 and chip RAM -10,
so the system uses the fast 32-bit RAM first and leaves the 24-bit block free for disk DMA.

### The helpers

```python
def testchunk(addr):                   # write a unique pattern, then read it back
    for i in range(64):
        poke32(addr + 4*i, ~(addr + 4*i))
    return checkchunk(addr)            # "bra checkchunk" in the assembly

def checkchunk(addr):
    CacheClearU()                      # flush the 040 caches so we read the RAM, not the cache
    return all(peek32(addr + 4*i) == ~(addr + 4*i) for i in range(64))

def checkall(low_ok, base, end):       # are all earlier chunks still intact?
    if low_ok and not checkchunk(0x08000000):
        return False
    return all(checkchunk(a) for a in range(base, end, CHUNK))

def findmem(name):                     # walk exec's linked list of memory regions
    node = exec.MemList.head
    while node.succ:                   # the list ends at a node whose succ is NULL
        if node.name and cstr(node.name) == name:
            return True
        node = node.succ
    return False

def addmem(size, base, name):
    AddMemList(size, MEMF_PUBLIC | MEMF_FAST, 30, base, name)
```

Why the pattern is `~address`: every long in every chunk gets a different value, which catches
three hardware situations.

- **Nothing at the address** reads back garbage.
- **A floating bus** often reads back the last value written. Only the last long would match, so
  the first one fails.
- **A mirror**, where fewer SIMMs are fitted and the same RAM answers at a second address: writing
  the new chunk's pattern overwrites the earlier chunk's, and `checkall` notices.

`checkchunk` uses `cmp.l` with `dbne`: the loop stops at the first mismatch with Z clear, or runs
all 64 longs and ends with Z set. That flag is its return value.

## 4. Lines that look odd

- **`move.w AttnFlags(a6),d0` then `btst #AFB_68040,d0`**, rather than one `btst` straight on
  memory. The Unicorn emulator used by the tests crashes on bit tests with memory operands, so the
  module always tests bits in a register. On a real 68040 it's the same.
- **`sne d6` then `andi.l #1,d6`**: "set the low byte of d6 to $FF if not equal, else to 0", then
  mask it to 0 or 1. That's `simms_4mb = int(bit != 0)`.
- **`movea.w #1,a5`**: an address register used as a boolean, because every data register is
  already in use. `cmpa.w #0,a5` tests it.
- **`lea ramname(pc),a1` before the first `addmem`, and `lea ramname2(pc),a1` after it**:
  `AddMemList` may destroy `a1`, so the name pointer is always loaded again after a call.
- **`movea.l a6,a4` … `movea.l d0,a6`** around the board scan: library calls need their own base
  in `a6`, so ExecBase is parked in `a4` while expansion.library's base is in `a6`, then swapped
  back before `CloseLibrary`.

## 5. The bug in 1.0

In assembly, a routine that doesn't end in `rts` or a branch runs straight into whatever code
comes next. `testchunk` was written to fall through into `checkchunk`. When `checkall` was added
for the mirror check, it was placed between them, so version 1.0 effectively did:

```python
def testchunk(addr):
    write_pattern(addr)
    return checkall(low_ok, base, end)     # should have been: return checkchunk(addr)
```

Two consequences:

- **A new chunk was never read back**, only the chunks found before it. On a card with fewer
  SIMMs and no mirror, the module would add memory that isn't there.
- **The very first test, of $08000000 in 2 MB autoconfig mode, ran before `end` (`a3`) was set.**
  `a3` held whatever exec left in it, so the result depended on leftover register contents.

Version 1.1 ends `testchunk` with an explicit `bra checkchunk`. The tests (section 7) start every
run with two different sets of leftover register values to catch this kind of mistake.

## 6. ppiload

`src/ppiload.asm` does what AmigaOS's `LoadModule` does, for this one module, so the test floppy
doesn't need any AmigaOS files. It includes the module as a raw binary assembled at address 0, so
each of the five RomTag pointers holds an offset into the module.

```python
def ppiload():
    dos = OpenLibrary("dos.library", 37)
    if FindResident("ppi2000mem"):
        print("already resident"); return 5            # RETURN_WARN

    # One chip RAM block: chip RAM is the only memory that exists at every reset.
    block = AllocMem(40 + len(MODULE), MEMF_PUBLIC | MEMF_CHIP | MEMF_CLEAR)
    code = block + 40
    CopyMem(MODULE, code, len(MODULE))

    # Find the RomTag (the $4AFC whose match pointer equals its own offset)
    # and turn its five offsets into real addresses.
    tag = code + next(off for off in range(0, len(MODULE), 2)
                      if peek16(code + off) == 0x4AFC and peek32(code + off + 2) == off)
    for field in (MATCHTAG, ENDSKIP, NAME, IDSTRING, INIT):
        poke32(tag + field, peek32(tag + field) + code)

    # A MemList with one entry covering the block: exec re-reserves it at reset.
    block.NumEntries, block.me_Addr, block.me_Length = 1, block, 40 + len(MODULE)
    print("Installing", cstr(peek32(tag + IDSTRING)), "Rebooting..."); Delay(50)

    Forbid()
    tags = [tag, (exec.KickTagPtr | 0x80000000) if exec.KickTagPtr else 0, 0]
    block.tags = tags                            # bit 31 set = "continue in this table"
    block.succ = exec.KickMemPtr                 # chain existing reset-proof memory
    exec.KickMemPtr = block
    exec.KickTagPtr = address_of(block.tags)
    exec.KickCheckSum = SumKickData()            # exec ignores both lists if this is wrong
    CacheClearU()
    ColdReboot()                                 # never returns
```

At the next reset exec checks `KickCheckSum`, reserves every block on the `KickMemPtr` list so
nothing overwrites it, and adds every RomTag on the `KickTagPtr` list to the ones it found in ROM.
From then on the module is treated exactly like a ROM module. Switching the power off clears
chip RAM, and the module is gone.

## 7. The tests

`make test` runs pytest in the tools container. The tests run the assembled code on
[Unicorn](https://www.unicorn-engine.org/), an emulated 68040 driven from Python, on a small fake
Amiga in `tests/amiga.py`:

1. A fixture in `conftest.py` assembles the current source, so the tests never run a stale binary.
2. Just enough of AmigaOS is faked. ExecBase and its memory list of MemHeaders are real bytes in
   emulated memory. Each library vector slot holds an `rts`, and a code hook runs a Python
   stand-in (`_lib_AddMemList`, `_lib_FindConfigDev`, `_lib_VPrintf`, …) just before it executes.
   The stand-ins deliberately overwrite `d1`, `a0` and `a1`, as real calls may. `VPrintf` formats
   with a Python version of exec's `RawDoFmt`.
3. The card is simulated. Its SIMMs are one `mmap` buffer mapped at $08000000; in 2 MB mode part of
   it is mapped a second time at $00200000, reproducing the real card's alias. Above the fitted
   SIMMs the tests try three behaviours: a mirror, an open bus reading $FFFFFFFF, and an open bus
   reading back the last value written. One chunk can be made faulty, losing every other write.

`tests/test_ppi2000mem.py` calls the module's `init` the way exec does and asserts the exact
`AddMemList` calls, no writes into the live 24-bit RAM, a balanced stack and restored registers.
Each scenario runs twice, with the registers starting at 0 and at $FFFFF000, to catch variables
used before they're set.

`tests/test_ppiprobe.py` runs `ppiprobe` and checks the lines it prints, and that every byte of
the SIMMs, including the live 24-bit RAM, is the same afterwards.

`tests/test_ppiload.py` runs `ppiload` and checks the `KickMemPtr` list, the `KickTagPtr` table
(chained to an existing one when there is one), the relocated RomTag, and that the checksum is
taken after both lists are in place.

`tests/test_mkrom.py` checks `tools/mkrom.py` against a synthetic Kickstart image: placement,
relocation, checksum, byte swap and refusal of bad input.

## 8. Where to go next

- `tools/mkrom.py`: a pure-Python loader for AmigaOS executables and the Kickstart checksum.
- `_lib_FindConfigDev` in `tests/test_ppi2000mem.py`: how a library stand-in works.
- `make disasm`, then compare `S0_195E` in `build/disasm/Init040.s` with `init` above; see
  [reverse-engineering.md](reverse-engineering.md).
