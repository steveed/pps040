#!/usr/bin/env python3
"""Disassemble an AmigaOS hunk executable with relocations applied.

Segment n is loaded at LOAD_BASE + n * SEG_SPAN (well clear of real hardware
addresses) so relocated pointers read as S<n>_offset.  Inline NUL-terminated
strings are emitted as dc.b so the sweep stays aligned.
Library calls (jsr/jmp -N(a6)) are annotated with the LVO name for the
library most recently loaded into a6, where that can be guessed.

Usage: disasm.py <hunkfile> [--seg N] [--start OFF] [--end OFF]
"""
import argparse
import re
import struct
import sys

import capstone

from lvos import LVOS

LOAD_BASE = 0x70000000
SEG_SPAN = 0x01000000

HUNK_UNIT, HUNK_NAME, HUNK_CODE, HUNK_DATA, HUNK_BSS = 0x3E7, 0x3E8, 0x3E9, 0x3EA, 0x3EB
HUNK_RELOC32, HUNK_SYMBOL, HUNK_DEBUG, HUNK_END, HUNK_HEADER = 0x3EC, 0x3F0, 0x3F1, 0x3F2, 0x3F3
HUNK_DREL32, HUNK_RELOC32SHORT = 0x3F7, 0x3FC


class Segment:
    def __init__(self, idx, kind, data, alloc):
        self.idx, self.kind, self.data, self.alloc = idx, kind, bytearray(data), alloc
        self.relocs = {}  # offset -> target segment
        self.symbols = {}

    @property
    def base(self):
        return LOAD_BASE + self.idx * SEG_SPAN


def load_hunks(path):
    raw = open(path, "rb").read()
    pos = 0

    def u32():
        nonlocal pos
        v = struct.unpack_from(">I", raw, pos)[0]
        pos += 4
        return v

    if u32() != HUNK_HEADER:
        sys.exit("not a hunk executable")
    while u32():  # resident library names (always empty in practice)
        pass
    u32()  # table size
    first, last = u32(), u32()
    allocs = [(u32() & 0x3FFFFFFF) * 4 for _ in range(first, last + 1)]

    segs, cur = [], None
    while pos < len(raw):
        t = u32() & 0x3FFFFFFF
        if t in (HUNK_CODE, HUNK_DATA):
            n = u32() * 4
            cur = Segment(len(segs), "CODE" if t == HUNK_CODE else "DATA",
                          raw[pos:pos + n], allocs[len(segs)])
            cur.data.extend(b"\0" * (cur.alloc - n))
            segs.append(cur)
            pos += n
        elif t == HUNK_BSS:
            u32()
            cur = Segment(len(segs), "BSS", b"\0" * allocs[len(segs)], allocs[len(segs)])
            segs.append(cur)
        elif t == HUNK_RELOC32:
            while True:
                n = u32()
                if not n:
                    break
                tgt = u32()
                for _ in range(n):
                    cur.relocs[u32()] = tgt
        elif t == HUNK_SYMBOL:
            while True:
                n = u32()
                if not n:
                    break
                name = raw[pos:pos + n * 4].rstrip(b"\0").decode("latin-1")
                pos += n * 4
                cur.symbols[u32()] = name
        elif t == HUNK_DEBUG:
            pos += u32() * 4
        elif t == HUNK_END:
            pass
        else:
            sys.exit(f"unhandled hunk type {t:#x} at {pos - 4:#x}")

    for s in segs:
        for off, tgt in s.relocs.items():
            v = struct.unpack_from(">I", s.data, off)[0]
            struct.pack_into(">I", s.data, off, v + segs[tgt].base)
    return segs


def sym(segs, addr):
    idx, off = divmod(addr - LOAD_BASE, SEG_SPAN)
    if 0 <= idx < len(segs) and off <= segs[idx].alloc:
        return segs[idx].symbols.get(off, f"S{idx}_{off:04X}")
    return None


def ascii_at(seg, off, maxlen=60):
    out = bytearray()
    while off < len(seg.data) and seg.data[off] and len(out) < maxlen:
        c = seg.data[off]
        if not (32 <= c < 127 or c in (9, 10, 27)):
            return None
        out.append(c)
        off += 1
    return out.decode("latin-1") if len(out) >= 4 else None


A6_LOAD = re.compile(r"^movea?\.l\s+(.+),\s*a6$")


def disassemble(segs, idx, start, end, a6_names):
    seg = segs[idx]
    md = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_M68K_040)
    md.skipdata = True
    code = bytes(seg.data[start:end])
    a6 = None
    targets = set()
    lines = []
    pos = start
    while pos < end:
        txt = ascii_at(seg, pos, maxlen=200)
        if txt and len(txt) >= 6 and pos + len(txt) < len(seg.data) and seg.data[pos + len(txt)] == 0:
            n = len(txt) + 1
            n += n & 1  # compilers word-align what follows
            lines.append((seg.base + pos, "", f"dc.b {txt!r},0", ""))
            pos += n
            a6 = None
            continue
        ins = next(md.disasm(code[pos - start:pos - start + 10], seg.base + pos, count=1), None)
        if ins is None:
            lines.append((seg.base + pos, seg.data[pos:pos + 2].hex(), f"dc.w ${seg.data[pos]:02x}{seg.data[pos + 1]:02x}", ""))
            pos += 2
            continue
        pos += ins.size
        op = ins.op_str
        # symbolise absolute addresses that land in a segment
        for m in re.findall(r"\$([0-9a-f]+)", op):
            s = sym(segs, int(m, 16))
            if s:
                op = op.replace(f"${m}", s)
                targets.add(int(m, 16))
        text = f"{ins.mnemonic} {op}".strip()
        note = ""
        m = A6_LOAD.match(text)
        if m:
            a6 = a6_names.get(m.group(1).strip(), m.group(1).strip())
        if ins.mnemonic == "movea.l" and op.startswith("$4.w, a6"):
            a6 = "exec"
        lvo = re.match(r"^j(sr|mp) -\$([0-9a-f]+)\(a6\)$", text)
        if lvo:
            off = -int(lvo.group(2), 16)
            lib = a6 if a6 in LVOS else None
            name = LVOS.get(lib, {}).get(off) if lib else None
            if name:
                note = f"{lib}/{name}"
            else:
                guess = LVOS["exec"].get(off)
                note = f"a6={a6} LVO {off}" + (f" (exec?/{guess})" if guess else "")
        for t in re.findall(r"(S(\d+)_([0-9A-F]{4,}))", op):
            s = segs[int(t[1])]
            txt = ascii_at(s, int(t[2], 16))
            if txt:
                note = (note + " " if note else "") + repr(txt)
        if ins.mnemonic in ("rts", "rte", "jmp", "bra", "bra.s", "bra.w"):
            end_blk = True
        else:
            end_blk = False
        lines.append((ins.address, ins.bytes.hex(), text, note))
        if end_blk:
            a6 = None
    return lines, targets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--seg", type=int, default=0)
    ap.add_argument("--start", type=lambda x: int(x, 0), default=0)
    ap.add_argument("--end", type=lambda x: int(x, 0), default=None)
    ap.add_argument("--a6", action="append", default=[],
                    help="operand=libname hint, e.g. -$7ff4(a4)=exec")
    args = ap.parse_args()

    segs = load_hunks(args.file)
    for s in segs:
        print(f"; segment {s.idx} {s.kind} size {s.alloc:#x} relocs {len(s.relocs)}")
    hints = dict(h.split("=", 1) for h in args.a6)
    seg = segs[args.seg]
    end = args.end if args.end is not None else len(seg.data)
    lines, _ = disassemble(segs, args.seg, args.start, end, hints)
    for addr, hx, text, note in lines:
        label = sym(segs, addr)
        print(f"{label}:  {hx:<20} {text:<40} {('; ' + note) if note else ''}")


if __name__ == "__main__":
    main()
