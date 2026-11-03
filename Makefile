# Everything runs in the tools container (see docker/Dockerfile), except the
# onerom-* targets: they run the onerom CLI on the host, which owns the USB
# connection. See "Test setup: One ROM" in README.md.
# KICK (only needed for `make rom`) must be inside this directory, since only
# it is mounted.

KICK   ?= amiga_roms/CDTVA500A600A2000.47.115.rom
ROM    := build/$(basename $(notdir $(KICK)))-ppi2000mem
# COPIES=4 also writes $(ROM)-x4.bin, e.g. for a 2 MB MX29F1615 in a 512K socket.
COPIES ?= 1
# Set by the release workflow; mkrelease.sh refuses a tag that doesn't match
# the version in src/ppi2000mem.asm.
RELEASE_TAG ?=
# The One ROM header pin wired to the host's reset line.
ONEROM_RESET_PIN ?= sel_c
# The 512K, byte-swapped image `make onerom-poke` loads.
ONEROM_IMAGE     ?= $(ROM).bin
# Names the default KICK's ROM, so a build from another KICK needs its own config.
ONEROM_CONFIG    ?= tools/onerom-a2000.json

RUN  := docker compose run --rm -T -e RELEASE_TAG=$(RELEASE_TAG) tools
VASM := vasmm68k_mot -Fhunkexe -nosym -quiet
PPS  := vendor/pps040/files/PPS_040-24_2/PPI_040

.PHONY: help image fetch modules test disasm bootdisk rom release clean \
	onerom-menu onerom-poke onerom-flash

help:
	@echo "make image     build the tools container"
	@echo "make modules   assemble ppi2000mem, ppiload and ppiprobe into build/"
	@echo "make test      run the module on an emulated 68040, and mkrom.py (pytest)"
	@echo "make fetch     download the PP&S driver disks into vendor/"
	@echo "make disasm    disassemble Init040 and ppi040.library into build/disasm"
	@echo "make bootdisk  build the bootable test floppy build/pps040-test.adf"
	@echo "make rom       patch KICK with the module into $(ROM).rom/.bin"
	@echo "               (COPIES=4 also writes -x4.bin for a 2 MB chip)"
	@echo "make release   package the binaries, mkrom.py and docs in build/release"
	@echo "make onerom-menu   restart the One ROM and reset the Amiga into the boot menu"
	@echo "make onerom-poke   load ONEROM_IMAGE into the One ROM's RAM and reset the Amiga"
	@echo "                   (default $(ROM).bin; lost when the One ROM restarts)"
	@echo "make onerom-flash  build the ROM, flash ONEROM_CONFIG and reset the Amiga"

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

# .rom for emulators and MapROM, .bin byte-swapped for burning; see COPIES.
rom: modules
	@test -f "$(KICK)" || { echo "No Kickstart image at $(KICK); set KICK=path/to/kick.rom" >&2; exit 1; }
	$(RUN) sh -c 'python tools/mkrom.py --copies $(COPIES) $(KICK) build/ppi2000mem $(ROM) && \
		romtool info $(ROM).rom | grep chk_sum && romtool scan $(ROM).rom | tail -1'

release: modules test
	$(RUN) tools/mkrelease.sh

onerom-menu:
	onerom reboot && onerom control reset --pin $(ONEROM_RESET_PIN)

# Doesn't depend on rom, as ONEROM_IMAGE need not be our build: use
# `make rom onerom-poke` to load a fresh one.
onerom-poke:
	@test -f "$(ONEROM_IMAGE)" || { echo "No image at $(ONEROM_IMAGE); run make rom or set ONEROM_IMAGE" >&2; exit 1; }
	onerom poke --address 0 --input $(ONEROM_IMAGE) && onerom control reset --pin $(ONEROM_RESET_PIN)

# The pin must be reserved on every flash, or the firmware reads the reset line
# as an image select pin.
onerom-flash: rom
	onerom program --config $(ONEROM_CONFIG) --reserve-pin $(ONEROM_RESET_PIN) --reset-host $(ONEROM_RESET_PIN)

clean:
	rm -rf build
