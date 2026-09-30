# Reverse engineering the PP&S driver software

What the original Progressive Peripherals & Software driver disks do, worked out by disassembling
them. This is the basis for `src/ppi2000mem.asm`.

## Reproducing the listings

The PP&S software isn't in this repository. `make fetch` downloads the three driver disks from
[amiga.resource.cx](https://amiga.resource.cx/exp/progressive2040) into `vendor/pps040/`, and
`make disasm` writes the listings to `build/disasm/`:

- `build/disasm/Init040.s`, from `PPI_040/68040/Init040` (v2.2)
- `build/disasm/ppi040.library.s`, from `PPI_040/Libs/ppi040.library`

`tools/disasm.py` loads the AmigaOS hunk file, applies its relocations and disassembles it with
Capstone. It names library calls (`exec/AddMemList`) where it can tell which library base is in
`a6`, and prints text strings inline. Addresses such as `S0_195E` below are offsets into the code
hunk as printed in those listings.

## The disks

The three disks on the site (`PPS_040-23`, `PPS_040-24`, `PPS_040-24_2`) contain byte-identical
copies of the board software, `Init040`, `CPU040`, `Switch` and `ppi040.library`. Only Commodore's
`68040.library` changes between them (v37.4, then v37.10). A fourth copy found elsewhere
("Installer's Heaven") is identical to `PPS_040-23`. The ReadMe dates the set to November 1992 and
recommends SetPatch 37.34 (OS 2.04) or 38.31 (OS 2.1): the software was written for OS 2.x only.

## ppi040.library

A small helper library. It never adds memory. It provides:

- **Board detection** (`S0_055C`), used by Init040:

  | Code | How it is detected                        | Init040 calls it       |
  |------|-------------------------------------------|------------------------|
  | $10  | FindConfigDev($7EA, $BB)                  | A500/040               |
  | 1    | FindConfigDev($7EA, $96)                  | Zeus '040              |
  | 4    | FindConfigDev($7EA, $69)                  | Progressive '040 2000  |
  | 2    | a register at $0F00C000 answers (10 tries)| Mercury '040           |
  | 8    | bit 0 of $0800C000 is read/write          | Progressive '040 3000  |

- Supervisor-mode wrappers to read and write the 040's control registers (CACR, TC, URP/SRP, VBR,
  ITT0/1, DTT0/1, MMUSR) and to push the caches.
- CPU and FPU identification.
- On Kickstart 1.3 only (`S0_08BE`): transparent translation that makes the whole 24-bit area
  non-cacheable for data and turns on both caches.

## Init040

Options: `ADDMEM`, `FASTROM`, `FASTSYS`. It opens ppi040.library, detects the board and branches
per board (`S0_21EE`). For the 2000/040 (`S0_2140`):

- `ADDMEM` runs `S0_195E` (below); `FASTSYS` runs `S0_0392`, which moves the vector base and the
  supervisor stack into fast RAM.
- **FASTROM never runs on the 2000.** The FastROM flag is only set for board codes 1, 2 and $10
  (`S0_2050`), so `Init040 FASTROM` is silently ignored on this card.
- Contemporary users reported that Init040 locks up with 68040.library v37.10 or later, and PP&S
  confirmed the incompatibility (see [the old FAQ](https://www.dpmworld.net/AmigaGallery/pps/pps040_orig.html)).

### ADDMEM on the 2000 (`S0_195E`)

1. Walks `ExecBase->MemList`; gives up if a region named "PPI 32Bit RAM" already exists.
2. Reads the card's jumper byte at **$E90003** (offset 3 of the card's I/O board):
   - bits 1 and 6: whether 24-bit autoconfig RAM is jumpered on;
   - bit 5: SIMM size (1 = 4 MB SIMMs, probe up to $0A000000; 0 = 1 MB SIMMs, up to $08800000).
3. If 24-bit RAM is on, reads `er_Type & 7` of the $7EA/$69 board to get its size:
   6 = 2 MB, 7 = 4 MB, 0 = 8 MB.
4. Tests 2 MB chunks by writing `~address` to the first 256 bytes and reading it back.
5. Calls `AddMemList(size, MEMF_PUBLIC|MEMF_FAST, 30, address, name)` (`S0_0D36`).

Resulting layout, where N is the size of the 24-bit autoconfig RAM:

| N    | Blocks added                                                                |
|------|-----------------------------------------------------------------------------|
| 0    | one block from $08000000, "PPI 32Bit RAM"                                   |
| 2 MB | $08000000–$081FFFFF "PPI 32Bit RAM"; $08400000–end "PPI 32Bit RAM ]["       |
| 4 MB | $08000000–$081FFFFF; $08600000–end                                          |
| 8 MB | $08000000–$081FFFFF; $08A00000–end                                          |

The hole starting at $08200000 is always exactly N bytes. That is almost certainly the same SIMM
memory the card shows in Zorro II space as its autoconfig RAM, so it must not be added twice.

## What ppi2000mem does differently

`src/ppi2000mem.asm` follows the logic above, with these changes:

- It runs from ROM at cold start (resident priority 105, straight after expansion.library), so the
  memory exists before DOS and before MMULib builds its MMU tables.
- It finds the card by scanning every board for product $69 from manufacturer 2026 or 756, takes
  the 24-bit size from the RAM board's `cd_BoardSize`, and reads the jumper byte from wherever the
  I/O board was configured, not from a fixed $E90003.
- It pushes the 040 caches before reading back a test pattern.
- It tests the 2 MB block at $08000000 first, and after each new chunk re-checks every earlier
  one, so a mirror (fewer SIMMs than the jumper limit allows) ends the probe instead of adding the
  same memory twice.
- It uses the same region names as Init040, so a leftover `Init040 ADDMEM` does nothing.

Version 1.0 had a bug: after writing a chunk's pattern it fell through into the re-check of the
*earlier* chunks rather than reading back the new one. New chunks were never verified, and in
2 MB autoconfig mode the first test ran before its end pointer was set. Version 1.1 fixes this;
`tests/` catches both cases.

## Open questions

- Which manufacturer ID (2026 or 756) belongs to which of the card's two boards? In 0 MB mode the
  I/O board reports 2026.
- Confirm on hardware that $08200000 aliases the 24-bit RAM: with the MMU off and 2 MB autoconfig,
  `ppiprobe` reports it either as "same memory as the 24-bit RAM" or as plain RAM.
- On the Zeus (`S0_0D62`), clearing bit 1 of $E90003 after copying the ROM to $08180000 switches
  on a hardware ROM remap. Unknown whether the 2000 has the same hardware.

## Zeus '040 (`S0_1222`), first look

Not supported by ppi2000mem; notes for anyone who wants to add it.

- Found by FindConfigDev($7EA, $96); reads its jumper byte at $E90003 like the 2000.
- Same 24-bit autoconfig table as the 2000 (0/2/4/8 MB puts the main block at $08000000,
  $08400000, $08600000 or $08A00000), but larger probe limits: $08E00000, $09A00000, $0A600000,
  $0B200000 or $0BE00000, chosen around `S0_1342` (sizing helper `S0_1124` not decoded yet).
- Some paths add only 1 MB at $08000000: with FASTROM the Zeus copies Kickstart to $08180000 and
  remaps it in hardware, so that memory is kept back.
