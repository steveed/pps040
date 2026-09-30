#!/bin/bash
# Download the PP&S 2000/040 driver disks and manual from amiga.resource.cx and
# unpack them into vendor/pps040 (dms/, adf/, files/). Already downloaded files
# are kept. Run inside the tools container: make fetch
set -euo pipefail

SITE=https://amiga.resource.cx
DIR=vendor/pps040
DISKS="PPS_040-23 PPS_040-24 PPS_040-24_2"

mkdir -p "$DIR/dms" "$DIR/adf" "$DIR/files"
for d in $DISKS; do
    [ -f "$DIR/dms/$d.dms" ] || curl -fsSL -o "$DIR/dms/$d.dms" "$SITE/install/$d.dms"
    xdms -q u "$DIR/dms/$d.dms" "+$DIR/adf/$d.adf"
    rm -rf "$DIR/files/$d"
    mkdir "$DIR/files/$d"               # unpacks to files/$d/PPI_040/...
    xdftool "$DIR/adf/$d.adf" unpack "$DIR/files/$d"
done
[ -f "$DIR/Progressive040_2000.pdf" ] ||
    curl -fsSL -o "$DIR/Progressive040_2000.pdf" "$SITE/manual/Progressive040_2000.pdf"
