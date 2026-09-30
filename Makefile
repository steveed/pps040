# Everything runs in the tools container (see docker/Dockerfile).
# KICK (only needed for `make rom`) must be inside this directory, since only
# it is mounted.

KICK   ?= amiga_roms/CDTVA500A600A2000.47.115.rom
ROM    := build/$(basename $(notdir $(KICK)))-ppi2000mem
# Set by the release workflow; mkrelease.sh refuses a tag that doesn't match
# the version in src/ppi2000mem.asm.
RELEASE_TAG ?=

RUN  := docker compose run --rm -T -e RELEASE_TAG=$(RELEASE_TAG) tools
VASM := vasmm68k_mot -Fhunkexe -nosym -quiet
PPS  := vendor/pps040/files/PPS_040-24_2/PPI_040

.PHONY: help image fetch modules test disasm bootdisk rom release clean

help:
	@echo "make image     build the tools container"
	@echo "make modules   assemble ppi2000mem, ppiload and ppiprobe into build/"
	@echo "make test      run the module on an emulated 68040, and mkrom.py (pytest)"
	@echo "make fetch     download the PP&S driver disks into vendor/"
	@echo "make disasm    disassemble Init040 and ppi040.library into build/disasm"
	@echo "make bootdisk  build the bootable test floppy build/pps040-test.adf"
	@echo "make rom       patch KICK with the module into $(ROM)*"
	@echo "make release   package the binaries, mkrom.py and docs in build/release"

image:
	docker compose build tools

# ppi2000mem.bin is the module assembled at address 0, included by ppiload.
modules:
	$(RUN) sh -c 'mkdir -p build && \
		$(VASM) -o build/ppi2000mem src/ppi2000mem.asm && \
		vasmm68k_mot -Fbin -quiet -o build/ppi2000mem.bin src/ppi2000mem.asm && \
		$(VASM) -o build/ppiload src/ppiload.asm && \
		$(VASM) -o build/ppiprobe src/ppiprobe.asm'

test:
	$(RUN) pytest -v tests

fetch:
	$(RUN) tools/fetch.sh

disasm: fetch
	$(RUN) sh -c 'mkdir -p build/disasm && \
		python tools/disasm.py $(PPS)/68040/Init040 > build/disasm/Init040.s && \
		python tools/disasm.py $(PPS)/Libs/ppi040.library > build/disasm/ppi040.library.s'

bootdisk:
	$(RUN) tools/mkbootdisk.sh

# .rom for emulators and MapROM, .bin byte-swapped for burning, and -x4.bin
# with four copies for a 2 MB MX29F1615 / 27C160 in a 512K socket.
rom: modules
	@test -f "$(KICK)" || { echo "No Kickstart image at $(KICK); set KICK=path/to/kick.rom" >&2; exit 1; }
	$(RUN) sh -c 'python tools/mkrom.py $(KICK) build/ppi2000mem $(ROM) && \
		romtool info $(ROM).rom | grep chk_sum && romtool scan $(ROM).rom | tail -1'

release: modules test
	$(RUN) tools/mkrelease.sh

clean:
	rm -rf build
