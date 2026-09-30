# pps040

Modern memory support for the **Progressive Peripherals & Software 2000/040**, a 1991 68040
accelerator for the Amiga 2000.

The card's 32-bit RAM doesn't autoconfigure. Its original driver, `Init040`, adds it from the
startup-sequence, was written for OS 2.x, locks up with newer 68040 libraries and leaves memory
unused. This project replaces it with **ppi2000mem**, a small resident module burned into the
Kickstart ROM. It adds all the card's RAM at cold start, before DOS and MMULib, so the memory
behaves as if it autoconfigured.

On the reference machine (AmigaOS 3.2.3, MMULib, 32 MB on the card) that meant all 32 MB in use
instead of 30, with the 32-bit RAM preferred over the slow 24-bit RAM, and no startup-sequence
changes other than deleting the old `AddMem`.

## What's here

| Path                     | What                                                              |
|--------------------------|-------------------------------------------------------------------|
| `src/ppi2000mem.asm`     | the ROM module (68040 assembly)                                   |
| `src/ppiprobe.asm`       | Shell tool that reports where the card's RAM answers; adds nothing |
| `src/ppiload.asm`        | installs the module until power-off and reboots, to try it without burning a ROM |
| `tools/mkrom.py`         | puts the module into a Kickstart image and fixes the checksum     |
| `tools/mkbootdisk.sh`    | builds the bootable test floppy (no AmigaOS files needed)         |
| `tools/disasm.py`        | disassembler for AmigaOS executables, used on the PP&S software   |
| `tools/fetch.sh`         | downloads the original PP&S driver disks                          |
| `tools/mkrelease.sh`     | packages a release (zip and ADF)                                  |
| `tests/`                 | runs the module on an emulated 68040 against simulated cards, and mkrom.py against a synthetic Kickstart |
| `docs/hardware.md`       | the card: jumpers, memory layout, measurements                    |
| `docs/reverse-engineering.md` | what the original driver does and how ppi2000mem differs     |
| `docs/rom.md`            | testing, building, burning, MMULib setup                          |

## Using a release

Each [release](../../releases) has a zip with `ppi2000mem`, `ppiload`, `ppiprobe`, `mkrom.py` and
the docs, and a bootable test floppy (ADF) with the same Amiga files; no AmigaOS or PP&S files.
Boot the floppy to probe the card, and type `ppiload` to try the module until the next power-off. To patch your own 512K Kickstart image (Python 3.8+, no other
packages):

```
python3 mkrom.py CDTVA500A600A2000.47.115.rom ppi2000mem kick-ppi2000mem
```

This writes `kick-ppi2000mem.rom`, `.bin` and `-x4.bin`. Try the module with `ppiload` before
burning; see [docs/rom.md](docs/rom.md).

## Building from source


- Docker. Everything runs in the `tools` container (vasm, amitools, xdms, Capstone, Unicorn,
  pytest); `make image` builds it.
- For `make rom` only: your own Kickstart image. It isn't included and can't be. By default
  the Makefile uses `amiga_roms/CDTVA500A600A2000.47.115.rom` (the 3.2.3 A500/A600/A2000 ROM);
  set `KICK` to use another, inside this directory.

## Quick start

```
make image       # build the tools container
make test        # run the module against the simulated cards
make bootdisk    # build/pps040-test.adf: probe the card, try the module with ppiload
make rom         # build/<kickstart>-ppi2000mem{.rom,.bin,-x4.bin}
```

Then follow [docs/rom.md](docs/rom.md): probe first, try the module with ppiload, and only then
burn.

`make release` packages `build/release/pps040-<version>.zip` and `.adf`. GitHub Actions
(`.github/workflows/build.yml`) does the same on every push and keeps the package as a run
artifact. To publish a release:

1. Bump the version in the `idstring` line of `src/ppi2000mem.asm`.
2. Add a `## X.Y (date)` section to `CHANGELOG.md`; it becomes the release notes.
3. Tag and push: `git tag vX.Y && git push origin vX.Y`. The workflow refuses a tag that doesn't
   match the module version.

To read the original driver: `make disasm` downloads the PP&S disks into `vendor/` and writes
the listings to `build/disasm/`.

## Status

Burned and in daily use on one A2000 with a 32 MB card, with 0 MB and 2 MB of autoconfig RAM.
The Zeus, Mercury and other PP&S cards aren't supported (the module leaves them alone); see the
notes at the end of [docs/reverse-engineering.md](docs/reverse-engineering.md).

## Not included

Kickstart ROMs, AmigaOS files and anything built from them (patched ROMs) are © Hyperion
Entertainment. The PP&S driver software, its disassembly and its manual are PP&S's.
`amiga_roms/`, `vendor/` and `build/` are git-ignored for that reason. The test
floppy contains only this project's files.

## Thanks

- [amiga.resource.cx](https://amiga.resource.cx/exp/progressive2040) for keeping the PP&S disks,
  manual and jumper table available.
- The [old PP&S 040 FAQ](https://www.dpmworld.net/AmigaGallery/pps/pps040_orig.html), whose
  AddMem addresses were the first clue to the memory layout.
- Thomas Richter's MMULib, and the vasm, amitools, Capstone and Unicorn projects.

## License

MIT, see [LICENSE](LICENSE). Covers this repository's own code and documentation only.
