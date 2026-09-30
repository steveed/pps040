"""Run ppi2000mem's init routine on an emulated 68040 against simulated boards.

The module is assembled from src/, loaded like mkrom.py loads it, and its
RomTag init routine is called the way exec calls it at cold start, on the fake
Amiga in amiga.py.

Run: make test
"""
import pytest

from amiga import MB, RAM32, Amiga, Card, Machine, Region


def run(module_code, machine, entry_regs=0x11110000):
    amiga = Amiga(machine, entry_regs)
    return amiga.run(amiga.load_module(*module_code))


def block(base, mb, name="PPI 32Bit RAM"):
    return (base, mb * MB, 5, 30, name)


# Register contents at entry are whatever exec left there; try two extremes
# so a register the module forgets to set is caught either way.
ENTRY = pytest.mark.parametrize("entry_regs", [0x00000000, 0xFFFFF000])


@ENTRY
def test_0mb_autoconfig_32mb_is_one_block(module_code, entry_regs):
    emu = run(module_code, Machine(card=Card(installed_mb=32)), entry_regs)
    assert emu.added == [block(RAM32, 32)]


@ENTRY
def test_2mb_autoconfig_skips_the_24bit_alias(module_code, entry_regs):
    emu = run(module_code, Machine(card=Card(installed_mb=32, ram24_mb=2)), entry_regs)
    assert emu.added == [block(RAM32, 2), block(0x08400000, 28, "PPI 32Bit RAM ][")]
    assert emu.alias_writes == []


@ENTRY
@pytest.mark.parametrize("unpopulated", ["mirror", "ones", "lastbus"])
def test_16mb_stops_at_the_end_of_the_simms(module_code, entry_regs, unpopulated):
    card = Card(installed_mb=16, unpopulated=unpopulated)
    emu = run(module_code, Machine(card=card), entry_regs)
    assert emu.added == [block(RAM32, 16)]


@ENTRY
@pytest.mark.parametrize("unpopulated", ["mirror", "ones", "lastbus"])
def test_16mb_with_2mb_autoconfig(module_code, entry_regs, unpopulated):
    card = Card(installed_mb=16, ram24_mb=2, unpopulated=unpopulated)
    emu = run(module_code, Machine(card=card), entry_regs)
    assert emu.added == [block(RAM32, 2), block(0x08400000, 12, "PPI 32Bit RAM ][")]
    assert emu.alias_writes == []


def test_faulty_chunk_ends_the_block(module_code):
    card = Card(installed_mb=32, faulty_chunk=5)
    emu = run(module_code, Machine(card=card))
    assert emu.added == [block(RAM32, 10)]


def test_1mb_simms_stop_at_8mb(module_code):
    card = Card(installed_mb=8, simms_4mb=False, unpopulated="ones")
    emu = run(module_code, Machine(card=card))
    assert emu.added == [block(RAM32, 8)]


def test_old_manufacturer_id_is_accepted(module_code):
    emu = run(module_code, Machine(card=Card(manufacturer=0x2F4)))
    assert emu.added == [block(RAM32, 32)]


def test_68000_mode_adds_nothing(module_code):
    emu = run(module_code, Machine(cpu_040=False))
    assert emu.added == [] and emu.calls == []


def test_already_added_adds_nothing(module_code):
    ppi = Region(RAM32 + 0x20, RAM32 + 32 * MB, 5, 30, "PPI 32Bit RAM")
    emu = run(module_code, Machine(memory=[ppi]))
    assert emu.added == []
    assert "OpenLibrary" not in emu.calls


def test_no_card_adds_nothing(module_code):
    emu = run(module_code, Machine(card=None))
    assert emu.added == []
    assert emu.calls.count("OpenLibrary") == emu.calls.count("CloseLibrary")
