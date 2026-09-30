# Testing, building and burning

## 1. Test on the real card without burning anything

`make bootdisk` builds `build/pps040-test.adf`; every release also has it as
`pps040-<version>.adf`. It contains only this project's files: the Shell and `Echo` come from the
Kickstart ROM. It boots without SetPatch, so MMULib never loads and the MMU stays off, and it
runs `ppiprobe`, which reports:

- whether the `ppi2000mem` module is resident, where, and its version;
- the system memory list;
- the card's autoconfig boards and its jumper byte;
- every 2 MB chunk from $08000000 to $09FFFFFF: RAM, no RAM, mirror, same memory as the 24-bit
  RAM, or unreliable. It skips anything already in the memory list and restores everything it
  writes.

To try the module before burning, type `ppiload`. It copies the module into chip RAM, registers
it with exec as reset-proof (the way LoadModule does) and reboots, so the module runs at the next
cold start exactly as it would from ROM. Boot the floppy again and `ppiprobe` shows the module as
resident at a chip RAM address, plus the memory it added. Switching the power off removes it.
`LoadModule ppi2000mem` from the AmigaOS disks works too.

**Remove any `AddMem` or `Init040 ADDMEM` line from the hard disk's startup-sequence first**, or
the same memory is added twice.

## 2. Build the ROM

```
make rom                     # KICK defaults to amiga_roms/CDTVA500A600A2000.47.115.rom
make rom KICK=path/to/kick.rom
```

Without the repository, `mkrom.py` from a release zip does the same with plain Python:
`python3 mkrom.py kick.rom ppi2000mem kick-ppi2000mem`.

`tools/mkrom.py` doesn't rebuild the Kickstart. Exec finds resident modules by scanning the whole
ROM for RomTags, so the module is copied into the ROM's unused $FF area (at $FFCF20 in the 3.2.3
ROM), its five RomTag pointers are relocated to that address, and the Kickstart checksum is
recomputed. Nothing else changes. `romtool info` and `romtool scan` check the result.

Output, next to the input's name in `build/`:

| File          | Use                                                                |
|---------------|--------------------------------------------------------------------|
| `….rom`       | emulators and MapROM                                               |
| `….bin`       | 512K, byte-swapped for burning (same order as Hyperion's `.bin`)   |
| `…-x4.bin`    | 2 MB: four copies of the `.bin`, for an MX29F1615 / 27C160         |

## 3. Try it in an emulator

Boot the `.rom` with the test floppy in an emulator set up as an A2000. `ppiprobe` should report
the module as resident (at $00FFCF24 for the 3.2.3 ROM). With a 68000 it stops there. With a
68040 and the MMU off it lists the memory, finds no PP&S board, and the module adds nothing.

## 4. Burn

The reference machine uses an MX29F1615 (2 MB, 16-bit) on a 42-to-40-pin adapter in the A2000's
Kickstart socket, programmed with a GQ-4x4. The chip's two top address lines are left unconnected,
so their level isn't guaranteed: burn `-x4.bin`, which has the same ROM in all four 512K slots.
The byte-swapped image is the right one for this setup; the unswapped one gives a black screen
and a pulsing power LED.

After burning, cold-boot with the test floppy: `ppiprobe` should show
`ppi2000mem module: resident at $00FFCF24, ppi2000mem 1.1 (29.9.2026)` and the "PPI 32Bit RAM"
region(s) at priority 30, without LoadModule.

## 5. MMULib

With the memory present from cold start, MMULib's tables cover it from the moment SetPatch loads
68040.library. Useful additions to the startup-sequence, after SetPatch:

```
MuFastROM
MuFastZero ON FASTSSP
```

`MuFastZero ON` moves the zero page, and `FASTSSP` the supervisor stack, from chip RAM to fast RAM.
Its `FASTEXEC` option also moves ExecBase, which on this card starts life in chip RAM, but needs
`MuMove4K` (from the Aminet MMULib archive) run before SetPatch.
