# Changelog

Versions are those of the ppi2000mem ROM module; a release tag `vX.Y` must match the version
string in `src/ppi2000mem.asm`.

## Unreleased

- mkrom.py writes only the .rom and .bin by default; `--copies N` (`make rom COPIES=N`) adds the
  -xN.bin with N copies, which only fits some setups, such as a 2 MB MX29F1615 in a 512K socket.

## 1.1 (2026-09-29)

- Fix: every newly tested 2 MB chunk is now read back. 1.0 only re-checked the chunks found
  earlier, so missing RAM that doesn't mirror could have been added.
- Fix: with 24-bit autoconfig RAM jumpered on, 1.0's first test used an uninitialised end pointer
  and, depending on leftover register contents, could add no 32-bit RAM at all.
- Bits are tested in registers, so the module runs under the Unicorn-based tests.
- ppiprobe 1.4 shows the resident module's version, and reports neighbouring chunks with the
  same result as one range, in lines of at most 60 characters, so the whole report fits in
  the boot Shell window.
- ppiload: installs the module until the next power-off and reboots, replacing LoadModule.
- The test floppy is built only from this project's files and is part of each release.

## 1.0 (2026-09-29)

- First version: finds the PP&S 2000/040 (manufacturer 2026 or 756, product 105), tests the
  32-bit RAM in 2 MB chunks with mirror detection, and adds it at priority 30 at cold start.
- ppiprobe: report-only probe of the card's memory, with the MMU off.
- mkrom.py: places the module in a Kickstart image's free space and fixes the checksum.
