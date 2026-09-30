; ppi2000mem - add the PP&S 2000/040's 32-bit RAM at cold start.
;
; A resident module that replaces "Init040 ADDMEM" (Init040 v2.2, S0_195E;
; see docs/reverse-engineering.md). It runs straight after expansion.library
; has configured the boards, so the RAM is in the system before DOS starts. It
; can be burned into a Kickstart image or loaded with LoadModule.
;
; Changes from the original:
;   - the RAM board is found by its memory flag and its size read from
;     cd_BoardSize, and the jumper byte is read from wherever the I/O board
;     was configured, not a fixed $E90003
;   - caches are pushed before the test pattern is read back
;   - the 2 MB block at $08000000 is tested before anything else, and after
;     each new chunk every earlier chunk is re-checked, so a mirror of the
;     board (fewer SIMMs than the limit allows) ends the probe
; The region names match Init040, so an old "Init040 ADDMEM" left in the
; startup-sequence reports "Memory ALREADY configured" and does nothing.
;
; Bits are tested in a register, never with "btst #n,<memory>": the Unicorn
; emulator behind tests/ aborts on bit operations with memory operands.

        machine 68040

; exec.library
_LVOCloseLibrary        equ -414
_LVOOpenLibrary         equ -552
_LVOAddMemList          equ -618
_LVOCacheClearU         equ -636
AttnFlags               equ $128
MemList                 equ $142
AFB_68040               equ 3

; expansion.library
_LVOFindConfigDev       equ -72
cd_Rom                  equ $10         ; struct ExpansionRom
er_Type                 equ cd_Rom+0
er_Product              equ cd_Rom+1
er_Manufacturer         equ cd_Rom+4
cd_BoardAddr            equ $20
cd_BoardSize            equ $24
ERTB_MEMLIST            equ 5

LN_SUCC                 equ 0
LN_NAME                 equ 10

RTC_MATCHWORD           equ $4afc
RTF_COLDSTART           equ 1
NT_UNKNOWN              equ 0

VERSION                 equ 1
PRIORITY                equ 105         ; after expansion.library (110)

; The card configures two boards, 64K of I/O and the 24-bit RAM, both product
; 105. PP&S used manufacturer IDs 2026 and 756, so accept either.
PPI_MANUFACTURER        equ $7ea
PPI_MANUFACTURER_OLD    equ $2f4
PPI_2000_PRODUCT        equ $69
PPI_STATUS              equ 3           ; jumper byte in the I/O board ($E90003)
PPI_STATUS_4MB_SIMMS    equ 5

MEMF_PUBLIC             equ 1
MEMF_FAST               equ 4
MEM_PRI                 equ 30          ; same as Init040

RAM32_BASE              equ $08000000
ALIAS_BASE              equ $08200000   ; 24-bit RAM also shows up here
CHUNK                   equ $200000
PROBE_LONGS             equ 64
LIMIT_1MB_SIMMS         equ $08800000
LIMIT_4MB_SIMMS         equ $0a000000

        section code,code

; Running the file from the shell does nothing.
start:
        moveq   #-1,d0
        rts

romtag:
        dc.w    RTC_MATCHWORD
        dc.l    romtag
        dc.l    endskip
        dc.b    RTF_COLDSTART,VERSION,NT_UNKNOWN,PRIORITY
        dc.l    name
        dc.l    idstring
        dc.l    init

name:     dc.b  "ppi2000mem",0
idstring: dc.b  "ppi2000mem 1.1 (29.9.2026)",13,10,0
expname:  dc.b  "expansion.library",0
ramname:  dc.b  "PPI 32Bit RAM",0
ramname2: dc.b  "PPI 32Bit RAM ][",0
        even

; d4 = 32-bit base of the probed area, d5 = size of the 24-bit autoconfig RAM,
; d6 = 4 MB SIMMs flag, d7 = card found, a3 = end of good memory, a6 = ExecBase
init:
        movem.l d2-d7/a2-a6,-(sp)
        movea.l 4.w,a6
        move.w  AttnFlags(a6),d0
        btst    #AFB_68040,d0
        beq     .done                   ; 68000 mode: $08000000 isn't there

        lea     ramname(pc),a2
        bsr     findmem
        bne     .done                   ; already added

        ; Scan every board for the card's I/O and RAM boards.
        lea     expname(pc),a1
        moveq   #36,d0
        jsr     _LVOOpenLibrary(a6)
        tst.l   d0
        beq     .done
        movea.l a6,a4
        movea.l d0,a6
        moveq   #0,d5
        moveq   #1,d6                   ; no I/O board: assume 4 MB SIMMs
        moveq   #0,d7
        suba.l  a2,a2
.scan:  movea.l a2,a0
        moveq   #-1,d0
        moveq   #-1,d1
        jsr     _LVOFindConfigDev(a6)
        tst.l   d0
        beq     .scanned
        movea.l d0,a2
        cmpi.b  #PPI_2000_PRODUCT,er_Product(a2)
        bne     .scan
        move.w  er_Manufacturer(a2),d0
        cmpi.w  #PPI_MANUFACTURER,d0
        beq     .ours
        cmpi.w  #PPI_MANUFACTURER_OLD,d0
        bne     .scan
.ours:  moveq   #1,d7
        move.b  er_Type(a2),d0
        btst    #ERTB_MEMLIST,d0
        beq     .io
        move.l  cd_BoardSize(a2),d5
        bra     .scan
.io:    movea.l cd_BoardAddr(a2),a0
        move.b  PPI_STATUS(a0),d0
        btst    #PPI_STATUS_4MB_SIMMS,d0
        sne     d6
        andi.l  #1,d6
        bra     .scan
.scanned:
        movea.l a6,a1
        movea.l a4,a6
        jsr     _LVOCloseLibrary(a6)
        tst.l   d7
        beq     .done                   ; not a 2000/040

        ; The d5 bytes of 24-bit RAM also appear at $08200000, so the 32-bit
        ; block starts after them. With no 24-bit RAM it starts at $08000000.
        move.l  #RAM32_BASE,d4
        tst.l   d5
        beq     .sized
        move.l  #ALIAS_BASE,d4
        add.l   d5,d4
.sized:
        ; With 24-bit RAM configured, $08000000 holds 2 MB of 32-bit RAM of its
        ; own. Test it first: it is where a mirror of the board shows up first.
        suba.l  a5,a5                   ; a5 = 1 if the $08000000 block is good
        tst.l   d5
        beq     .nolow
        movea.l #RAM32_BASE,a0
        bsr     testchunk
        bne     .done                   ; odd board: probing on could hit the
        movea.w #1,a5                   ; 24-bit RAM through a mirror
.nolow:
        movea.l d4,a3
        tst.l   d6
        bne     .probe
        cmpi.l  #$800000,d5
        beq     .probed                 ; 1 MB SIMMs, all 8 MB went to 24-bit
.probe:
        movea.l a3,a0
        bsr     testchunk
        bne     .probed
        bsr     checkall
        bne     .probed                 ; a3 mirrors a chunk already found
        adda.l  #CHUNK,a3
        move.l  #LIMIT_1MB_SIMMS,d0
        tst.l   d6
        beq     .limit
        move.l  #LIMIT_4MB_SIMMS,d0
.limit: cmpa.l  d0,a3
        bcs     .probe
.probed:
        move.l  a3,d3
        sub.l   d4,d3                   ; d3 = size of the block at d4
        lea     ramname(pc),a1
        cmpa.w  #0,a5
        beq     .main
        move.l  #CHUNK,d0
        movea.l #RAM32_BASE,a0
        bsr     addmem
        lea     ramname2(pc),a1
.main:
        tst.l   d3
        beq     .done
        move.l  d3,d0
        movea.l d4,a0
        bsr     addmem
.done:
        movem.l (sp)+,d2-d7/a2-a6
        moveq   #0,d0
        rts

; addmem(d0 = size, a0 = base, a1 = name)
addmem:
        move.l  d2,-(sp)
        moveq   #MEMF_PUBLIC|MEMF_FAST,d1
        moveq   #MEM_PRI,d2
        jsr     _LVOAddMemList(a6)
        move.l  (sp)+,d2
        rts

; testchunk(a0 = address): write ~address to the first PROBE_LONGS longs,
; push the caches and read them back. Z set if the memory is good.
testchunk:
        move.l  a0,-(sp)
        moveq   #PROBE_LONGS-1,d1
.fill:  move.l  a0,d0
        not.l   d0
        move.l  d0,(a0)+
        dbf     d1,.fill
        movea.l (sp)+,a0
        bra     checkchunk

; checkall: Z set if every chunk that passed so far (the $08000000 block if
; a5 is set, then d4 up to a3) still holds its own pattern.
checkall:
        cmpa.w  #0,a5
        beq     .body
        movea.l #RAM32_BASE,a0
        bsr     checkchunk
        bne     .out
.body:  movea.l d4,a0
.loop:  cmpa.l  a3,a0
        bcc     .ok
        bsr     checkchunk
        bne     .out
        adda.l  #CHUNK,a0
        bra     .loop
.ok:    moveq   #0,d0
.out:   rts

; checkchunk(a0 = address): Z set if the test pattern is still there.
checkchunk:
        movem.l a0/a2,-(sp)
        movea.l a0,a2
        jsr     _LVOCacheClearU(a6)
        moveq   #PROBE_LONGS-1,d1
.cmp:   move.l  a2,d0
        not.l   d0
        cmp.l   (a2)+,d0
        dbne    d1,.cmp
        movem.l (sp)+,a0/a2
        rts

; findmem(a2 = name): Z clear if a MemHeader with that name exists.
findmem:
        movem.l a3/a4,-(sp)
        movea.l MemList(a6),a0
.loop:  tst.l   LN_SUCC(a0)
        beq     .none
        move.l  LN_NAME(a0),d0
        beq     .next
        movea.l d0,a3
        movea.l a2,a4
.cmp:   move.b  (a3)+,d0
        cmp.b   (a4)+,d0
        bne     .next
        tst.b   d0
        bne     .cmp
        moveq   #1,d0                   ; found: Z clear
        bra     .out
.next:  movea.l LN_SUCC(a0),a0
        bra     .loop
.none:  moveq   #0,d0
.out:   movem.l (sp)+,a3/a4
        rts

endskip:
