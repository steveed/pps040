# The PP&S 2000/040 card

Progressive Peripherals & Software, 1991. An A2000 CPU-slot card with a 68040 at 28 MHz, clocked
independently of the motherboard, and eight 30-pin SIMM sockets for up to 32 MB. The card has an
MMU and an FPU. Background and adverts: [amiga.resource.cx](https://amiga.resource.cx/exp/progressive2040).

## Jumpers

From the resource.cx page (ON = jumper fitted):

| Jumpers    | Setting                   | Meaning                                  |
|------------|---------------------------|------------------------------------------|
| A1/A2/B3   | OFF/ON/ON                 | 0 MB autoconfig (24-bit) RAM             |
|            | OFF/ON/OFF                | 2 MB autoconfig RAM                      |
|            | ON/OFF/ON                 | 4 MB autoconfig RAM                      |
|            | ON/OFF/OFF                | 8 MB autoconfig RAM                      |
| A3/A4      | ON/OFF · OFF/ON           | 68000 · 68040                            |
| B1         | ON · OFF                  | page-mode · nibble-mode SIMMs            |
| B2         | ON · OFF                  | 1 MB · 4 MB SIMMs                        |
| B4         | ON · OFF                  | German · B2000 motherboard               |
| C1/C2      | ON/OFF · OFF/ON           | cache enabled · disabled                 |
| C3/C4      | ON/OFF · OFF/ON           | burst enabled · disabled                 |

SIMMs are fitted in groups of four: 1 MB SIMMs give 4 or 8 MB, 4 MB SIMMs give 16 or 32 MB.

## What the card looks like to the system

The card autoconfigures as up to two Zorro II boards, both product 105:

- **A 64K I/O board**, normally at $E90000. Offset 3 is a read-only jumper byte:
  bits 1 and 6 reflect the autoconfig RAM jumpers, bit 5 is set for 4 MB SIMMs. Seen with 4 MB
  SIMMs: $A0 with 0 MB autoconfig, $EC with 2 MB autoconfig (bit 6 set; bits 2 and 3 also
  changed between the two readings, possibly from the cache and burst jumpers).
- **The 24-bit autoconfig RAM** (2, 4 or 8 MB, normally from $200000), only when jumpered on.
  This is the only fast RAM a Zorro II DMA controller such as the A2091 can reach.

The rest of the SIMM memory is 32-bit RAM from $08000000. It does not autoconfigure; software has
to add it (originally `Init040 ADDMEM`, here the ppi2000mem ROM module). The part of the SIMMs
used as 24-bit RAM also appears in the 32-bit area, starting at $08200000, so that range is left
out. `ppiprobe` confirmed this on the reference card: writing at $08200000 changes $00200000. See [reverse-engineering.md](reverse-engineering.md) for the full layout per jumper setting.

## Reference machine

Measured on the A2000 this project was developed on: Kickstart/AmigaOS 3.2.3 (47.115), MMULib
(68040.library 46.3, 680x0.library 46.1), A2091 with GuruROM, ZuluSCSI, Prelude sound card,
A2065 Ethernet, 32 MB of SIMMs on the card.

### Before (AddMem in the startup-sequence)

The startup-sequence had `C:AddMem $08400000 $09ffffff` after SetPatch and `MuFastROM`.

| Region                  | Size  | Pri | Notes                                              |
|-------------------------|-------|-----|----------------------------------------------------|
| $00200000–$003FFFFF     | 2 MB  | 0   | 24-bit autoconfig RAM, full (256 bytes free)       |
| $08400000–$09FFFFFF     | 28 MB | 0   | added late; name was garbage                       |
| $00000000–$001FFFFF     | 2 MB  | -10 | chip RAM                                           |

- $08000000–$081FFFFF was never added: 2 MB of RAM lost, marked blank in the MMU table.
- Both fast regions had priority 0 and the 24-bit one came first, so CPU libraries
  (68040.library, 680x0.library, asl, amigaguide) were loaded into the slow 24-bit RAM.
- Autoconfig boards: PP&S I/O at $E90000 (64K), PP&S RAM at $200000 (2 MB), A2091 at $EA0000,
  Prelude at $EB0000, A2065 at $EC0000.

### After (ppi2000mem in ROM)

With 2 MB autoconfig and the module in ROM, the memory list shows "PPI 32Bit RAM" (2 MB at
$08000000) and "PPI 32Bit RAM ][" (28 MB at $08400000), both at priority 30, above the 24-bit
expansion memory (priority 0) and chip RAM (-10): all 32 MB in use. See the `ppiprobe` output in
[rom.md](rom.md).

With 0 MB autoconfig, `ppiprobe` (MMU off) found only the I/O board (manufacturer 2026, jumper
byte $A0) and RAM in all 16 chunks from $08000000 to $09FFFFFF, with no mirrors. With the module
loaded, the memory list showed one region, "PPI 32Bit RAM", $08000020–$09FFFFFF, 32767K, priority
30, attributes $0005 (public, fast). With 2 MB autoconfig the module adds 2 MB at $08000000 and
28 MB at $08400000 instead.

## Disk speed (A2091)

| A2091 ROM | Card setting        | Speed         | Why                                         |
|-----------|---------------------|---------------|---------------------------------------------|
| 7.0       | 2 MB autoconfig     | ~52 KB/s      | falls back to CPU byte transfers            |
| GuruROM   | 2 MB autoconfig     | ~1.4–1.77 MB/s| DMA into the 24-bit RAM, CPU copies it on   |
| GuruROM   | 0 MB autoconfig     | ~300 KB/s     | DMA only into chip RAM                      |

Keep 2 MB of autoconfig RAM with an A2091: the 24-bit block is the DMA target, and with the
32-bit RAM at priority 30 the system leaves it free for that. A controller that uses programmed
I/O instead of DMA (for example a modern Zorro II IDE card) doesn't need it.

## Things that bit us

- **SIMMs and the card itself.** Unexplained memory trouble turned out to be a broken trace and a
  failing Samsung memory controller chip. AmigaTestKit found both.
- **SCSI termination.** Running without the active terminator corrupted data on the disk; the
  first sign was ShowConfig crashing with `80000004` (illegal instruction). Replace damaged files
  from the OS disks and check the partition with DiskDoctor.
- **LoadModule and power cycling.** One `80000004` Guru appeared right after a quick power cycle
  while testing with LoadModule. A half-faded copy of the module surviving in RAM would explain it,
  but so would the SCSI problem above. When testing with LoadModule, leave the power off for ten
  seconds or more.
