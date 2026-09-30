#!/bin/bash
# Package the assembled binaries with mkrom.py and the docs into
# build/release/pps040-<version>.zip and a bootable test floppy
# pps040-<version>.adf (see mkbootdisk.sh), plus notes.md (this version's
# CHANGELOG section) for the release page.
# Nothing from AmigaOS or PP&S goes in. Run inside the container: make release
set -euo pipefail

VERSION=$(sed -n 's/^idstring: *dc.b *"ppi2000mem \([0-9][0-9.]*\) (.*/\1/p' src/ppi2000mem.asm)
if [ -z "$VERSION" ]; then
    echo "no version found in src/ppi2000mem.asm" >&2
    exit 1
fi
if [ -n "${RELEASE_TAG:-}" ] && [ "$RELEASE_TAG" != "v$VERSION" ]; then
    echo "tag $RELEASE_TAG doesn't match the module version $VERSION" >&2
    exit 1
fi

NAME=pps040-$VERSION
OUT=build/release
DIR=$OUT/$NAME
rm -rf "$OUT"
mkdir -p "$DIR/docs"

extra=(README.md:README.md CHANGELOG.md:CHANGELOG.md LICENSE:LICENSE docs:docs)
for f in docs/*.md; do
    extra+=("$f:$f")
done
DISK_NAME="pps040 $VERSION" tools/mkbootdisk.sh "${extra[@]}" >/dev/null
cp build/pps040-test.adf "$OUT/$NAME.adf"

cp build/ppi2000mem build/ppiload build/ppiprobe tools/mkrom.py README.md CHANGELOG.md LICENSE "$DIR/"
cp docs/*.md "$DIR/docs/"
(cd "$OUT" && python -m zipfile -c "$NAME.zip" "$NAME")

awk -v v="$VERSION" '$0 ~ "^## " v " " {p=1; next} /^## / {p=0} p' CHANGELOG.md > "$OUT/notes.md"
if ! grep -q '[^[:space:]]' "$OUT/notes.md"; then
    echo "CHANGELOG.md has no section for $VERSION" >&2
    exit 1
fi
echo "$VERSION" > "$OUT/VERSION"
ls -l "$OUT"
