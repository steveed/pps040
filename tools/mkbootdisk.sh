#!/bin/bash
# Build build/pps040-test.adf: a bootable floppy with ppiprobe, ppiload and
# the ppi2000mem module, built only from this repository's own files. The
# Shell and its built-in commands (Echo) come from the Kickstart ROM, and
# there's no SetPatch, so MMULib never loads and the MMU stays off for
# ppiprobe. Extra files to add can be passed as "source:disk/path" pairs.
# Run inside the tools container: make bootdisk
set -euo pipefail

OUT=build/pps040-test.adf
VASM="vasmm68k_mot -Fhunkexe -nosym -quiet"

mkdir -p build
$VASM -o build/ppi2000mem src/ppi2000mem.asm
vasmm68k_mot -Fbin -quiet -o build/ppi2000mem.bin src/ppi2000mem.asm
$VASM -o build/ppiload src/ppiload.asm
$VASM -o build/ppiprobe src/ppiprobe.asm

cmd=(xdftool "$OUT" create + format "${DISK_NAME:-PPS040Test}" ffs + boot install
     + makedir S + write bootdisk/Startup-Sequence S/Startup-Sequence
     + write build/ppiprobe ppiprobe + write build/ppiload ppiload
     + write build/ppi2000mem ppi2000mem)
for pair in "$@"; do
    src=${pair%%:*}
    dst=${pair#*:}
    if [ -d "$src" ]; then
        cmd+=(+ makedir "$dst")
    else
        cmd+=(+ write "$src" "$dst")
    fi
done
rm -f "$OUT"
"${cmd[@]}" >/dev/null
xdftool "$OUT" list
