"""Run ppiprobe on the fake Amiga and check its report.

ppiprobe writes test patterns into the card's memory with interrupts off, so
besides the report these tests check that every byte of the SIMMs, including
the live 24-bit RAM, is exactly as it was before.
"""
import os

from amiga import MB, RAM32, Amiga, Card, Machine, Region

IDSTRING = "ppi2000mem 1.1 (29.9.2026)\r\n"


WIDTH = 60      # the boot Shell window is about 61 columns wide


def probe(path, machine):
    amiga = Amiga(machine)
    before = None
    if machine.card:
        amiga.simms[:] = os.urandom(len(amiga.simms))
        before = bytes(amiga.simms)
    amiga.run(amiga.load_program(path))
    if before is not None:
        assert bytes(amiga.simms) == before, "ppiprobe left memory changed"
    lines = amiga.output.splitlines()
    assert [line for line in lines if len(line) > WIDTH] == []
    return lines


def section(lines, label):
    """The lines of one labelled section, labels and indent removed."""
    out, inside = [], False
    for line in lines:
        if line.startswith(label):
            inside = True
        elif line[:1] != " ":
            inside = False
        if inside:
            out.append(line[9:])
    return out


def test_0mb_autoconfig(ppiprobe_path):
    lines = probe(ppiprobe_path, Machine(card=Card(installed_mb=32)))
    assert lines[0].startswith("ppiprobe 1.4")
    assert "Module:  ppi2000mem not resident" in lines
    assert section(lines, "Boards:") == ["$00E90000     64K I/O 2026/105 jumpers $A0"]
    assert section(lines, "32-bit:") == ["$08000000-$09FFFFFF  32 MB RAM"]


def test_2mb_autoconfig_finds_the_alias(ppiprobe_path):
    lines = probe(ppiprobe_path, Machine(card=Card(installed_mb=32, ram24_mb=2)))
    assert section(lines, "Boards:") == [
        "$00E90000     64K I/O 2026/105 jumpers $A0",
        "$00200000   2048K RAM 2026/105",
    ]
    assert section(lines, "32-bit:") == [
        "$08000000-$081FFFFF   2 MB RAM",
        "$08200000-$083FFFFF   2 MB same as 24-bit $00200000",
        "$08400000-$09FFFFFF  28 MB RAM",
    ]


def test_with_the_module_in_rom_it_fits_one_screen(ppiprobe_path):
    """The reference machine: 2 MB autoconfig, module resident, RAM added."""
    added = [Region(RAM32 + 0x20, RAM32 + 2 * MB, 5, 30, "PPI 32Bit RAM"),
             Region(0x08400020, 0x0A000000, 5, 30, "PPI 32Bit RAM ][")]
    machine = Machine(card=Card(installed_mb=32, ram24_mb=2), memory=added,
                      resident=IDSTRING)
    lines = probe(ppiprobe_path, machine)
    assert "Module:  $00048000 ppi2000mem 1.1 (29.9.2026)" in lines
    assert section(lines, "Memory:") == [
        "$08000020   2047K pri  30 PPI 32Bit RAM",
        "$08400020  28671K pri  30 PPI 32Bit RAM ][",
        "$00200020   2047K pri   0 expansion memory",
        "$00001020   2043K pri -10 chip memory",
    ]
    assert section(lines, "32-bit:") == [
        "$08000000-$081FFFFF   2 MB in memory list",
        "$08200000-$083FFFFF   2 MB same as 24-bit $00200000",
        "$08400000-$09FFFFFF  28 MB in memory list",
    ]
    assert len(lines) <= 12


def test_16mb_mirror(ppiprobe_path):
    lines = probe(ppiprobe_path, Machine(card=Card(installed_mb=16)))
    assert section(lines, "32-bit:") == [
        "$08000000-$08FFFFFF  16 MB RAM",
        "$09000000-$09FFFFFF  16 MB mirror of $08000000",
    ]


def test_16mb_open_bus(ppiprobe_path):
    lines = probe(ppiprobe_path, Machine(card=Card(installed_mb=16, unpopulated="ones")))
    assert section(lines, "32-bit:") == [
        "$08000000-$08FFFFFF  16 MB RAM",
        "$09000000-$09FFFFFF  16 MB no RAM",
    ]


def test_faulty_chunk_gets_its_own_line(ppiprobe_path):
    lines = probe(ppiprobe_path, Machine(card=Card(installed_mb=32, faulty_chunk=5)))
    assert section(lines, "32-bit:") == [
        "$08000000-$089FFFFF  10 MB RAM",
        "$08A00000-$08BFFFFF   2 MB UNRELIABLE (32/64 ok)",
        "$08C00000-$09FFFFFF  20 MB RAM",
    ]


def test_mmu_on_lists_memory_but_touches_nothing(ppiprobe_path):
    amiga = Amiga(Machine(mmu_on=True, card=Card(ram24_mb=2)))
    amiga.run(amiga.load_program(ppiprobe_path))
    assert "The MMU is on" in amiga.output
    assert "Memory:" in amiga.output and "32-bit:" not in amiga.output
    assert amiga.card_writes == []


def test_68000_mode(ppiprobe_path):
    lines = probe(ppiprobe_path, Machine(cpu_040=False))
    assert any("not a 68040" in line for line in lines)
    assert not any(line.startswith("32-bit:") for line in lines)


def test_no_card(ppiprobe_path):
    lines = probe(ppiprobe_path, Machine(card=None))
    assert any("No PP&S 2000/040 autoconfig board found" in line for line in lines)
