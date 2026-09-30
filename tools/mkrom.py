#!/usr/bin/env python3
"""Put a resident module into unused space of a 512K Kickstart image.

Exec finds resident modules by scanning the ROM for their RomTag, so the
module only has to sit in the $FF-filled free area with its relocations applied
for that address. The Kickstart checksum is then recomputed. Writes a .rom
(for emulators and MapROM), a byte-swapped .bin (for burning 16-bit ROMs)
and, by default, a -x4.bin with four copies of it for a 2 MB MX29F1615 or
27C160 in a 512K socket. Needs only Python 3.8+, no other packages.

Usage: mkrom.py <kick.rom> <module hunk file> <output base name> [--copies N]
"""
import argparse
import struct
import sys

ROM_SIZE = 0x80000
ROM_BASE = 0xF80000
CHECKSUM_OFF = ROM_SIZE - 0x18
FREE_FILL = 0xFF

HUNK_HEADER, HUNK_CODE, HUNK_DATA, HUNK_BSS = 0x3F3, 0x3E9, 0x3EA, 0x3EB
HUNK_RELOC32, HUNK_END = 0x3EC, 0x3F2
HUNK_RELOC32SHORT = (0x3FC, 0x3F7)  # LoadSeg reads HUNK_DREL32 as short relocs too


def load_module(path):
    """Return (code bytes, [reloc offsets]) for a single-hunk executable."""
    raw = open(path, "rb").read()
    pos = 0

    def u32():
        nonlocal pos
        v = struct.unpack_from(">I", raw, pos)[0]
        pos += 4
        return v

    def u16():
        nonlocal pos
        v = struct.unpack_from(">H", raw, pos)[0]
        pos += 2
        return v

    assert u32() == HUNK_HEADER
    assert u32() == 0
    table, first, last = u32(), u32(), u32()
    if (table, first, last) != (1, 0, 0):
        sys.exit("module must be a single code hunk")
    u32()
    code, relocs = None, []
    while pos < len(raw):
        t = u32() & 0x3FFFFFFF
        if t == HUNK_CODE:
            n = u32() * 4
            code = bytearray(raw[pos:pos + n])
            pos += n
        elif t == HUNK_RELOC32:
            while (n := u32()):
                assert u32() == 0
                relocs += [u32() for _ in range(n)]
        elif t in HUNK_RELOC32SHORT:
            while (n := u16()):
                assert u16() == 0
                relocs += [u16() for _ in range(n)]
            if pos & 2:
                pos += 2
        elif t == HUNK_END:
            pass
        else:
            sys.exit(f"unexpected hunk {t:#x}")
    return code, relocs


def free_area(rom):
    """Offset and length of the largest run of FREE_FILL bytes."""
    best, i = (0, 0), 0
    while i < CHECKSUM_OFF:
        j = i
        while j < CHECKSUM_OFF and rom[j] == FREE_FILL:
            j += 1
        if j - i > best[1]:
            best = (i, j - i)
        i = j + 1
    return best


def fix_checksum(rom):
    struct.pack_into(">I", rom, CHECKSUM_OFF, 0)
    total = 0
    for (v,) in struct.iter_unpack(">I", rom):
        total += v
        if total > 0xFFFFFFFF:
            total = (total & 0xFFFFFFFF) + 1
    struct.pack_into(">I", rom, CHECKSUM_OFF, ~total & 0xFFFFFFFF)


class RomError(Exception):
    pass


def patch_rom(rom, code, relocs):
    """Place relocated module code in the ROM's free area and fix the checksum.

    Returns (patched ROM, address of the code, (free offset, free length)).
    """
    rom = bytearray(rom)
    if len(rom) != ROM_SIZE or struct.unpack_from(">I", rom, CHECKSUM_OFF + 4)[0] != ROM_SIZE:
        raise RomError("not a 512K Kickstart image")
    start, length = free_area(rom)
    off = (start + 15) & ~15
    if off + len(code) > start + length:
        raise RomError(f"module ({len(code)} bytes) does not fit in the free area")
    addr = ROM_BASE + off
    code = bytearray(code)
    for r in relocs:
        v = struct.unpack_from(">I", code, r)[0]
        struct.pack_into(">I", code, r, v + addr)
    rom[off:off + len(code)] = code
    fix_checksum(rom)
    return rom, addr, (start, length)


def byteswap(rom):
    """Swap the bytes of every word: the order used for burning 16-bit ROMs."""
    swapped = bytearray(len(rom))
    swapped[0::2], swapped[1::2] = rom[1::2], rom[0::2]
    return swapped


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("kick", help="512K Kickstart image (.rom)")
    ap.add_argument("module", help="assembled module (hunk executable)")
    ap.add_argument("out", help="output name without extension")
    ap.add_argument("--copies", type=int, default=4,
                    help="also write OUT-xN.bin with N copies of the .bin, for "
                         "larger chips in a 512K socket (default 4, 1 = off)")
    args = ap.parse_args()

    code, relocs = load_module(args.module)
    try:
        rom, addr, (start, length) = patch_rom(open(args.kick, "rb").read(), code, relocs)
    except RomError as e:
        sys.exit(str(e))

    open(args.out + ".rom", "wb").write(rom)
    swapped = byteswap(rom)
    open(args.out + ".bin", "wb").write(swapped)
    if args.copies > 1:
        open(f"{args.out}-x{args.copies}.bin", "wb").write(swapped * args.copies)
    print(f"placed {len(code)} bytes at ${addr:06X} (free area ${ROM_BASE + start:06X}, "
          f"{length} bytes); {len(relocs)} relocations")


if __name__ == "__main__":
    main()
