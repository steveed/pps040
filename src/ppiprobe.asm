; ppiprobe - report where the PP&S 2000/040's RAM answers. Adds nothing.
;
; Run from a Shell with the MMU off (boot with no startup-sequence), since
; MMULib marks unused addresses invalid. For every 2 MB chunk from $08000000 to
; $09FFFFFF it reports whether the chunk holds RAM, mirrors an earlier chunk,
; or is the same memory as the card's 24-bit autoconfig RAM. Every location
; written is restored before interrupts are enabled again, and no test pattern
; is written into memory the system already uses.

        machine 68040

; exec.library
_LVOSupervisor          equ -30
_LVOFindResident        equ -96
_LVOForbid              equ -132
_LVOPermit              equ -138
_LVODisable             equ -120
_LVOEnable              equ -126
_LVOCloseLibrary        equ -414
_LVOTypeOfMem           equ -534
_LVOOpenLibrary         equ -552
_LVOCacheClearU         equ -636
AttnFlags               equ $128
MemList                 equ $142
AFB_68040               equ 3
LN_SUCC                 equ 0
LN_PRI                  equ 9
LN_NAME                 equ 10
mh_Attributes           equ 14
mh_Lower                equ 20
mh_Upper                equ 24

; dos.library
_LVOVPrintf             equ -954

; expansion.library
_LVOFindConfigDev       equ -72
er_Type                 equ $10
er_Product              equ $11
er_Manufacturer         equ $14
cd_BoardAddr            equ $20
cd_BoardSize            equ $24
ERTB_MEMLIST            equ 5

PPI_MANUFACTURER        equ $7ea
PPI_MANUFACTURER_OLD    equ $2f4
PPI_2000_PRODUCT        equ $69
PPI_STATUS              equ 3

RAM32_BASE              equ $08000000
CHUNK_SHIFT             equ 21          ; 2 MB
NCHUNKS                 equ 16          ; up to $0A000000, as Init040 probes
PROBE_LONGS             equ 64
TOP_LONG                equ (1<<CHUNK_SHIFT)-4

ST_INUSE                equ 1
ST_ALIAS                equ 2

        section code,code

start:
        movem.l d2-d7/a2-a6,-(sp)
        lea     vars,a3
        movea.l 4.w,a6
        lea     dosname(pc),a1
        moveq   #37,d0
        jsr     _LVOOpenLibrary(a6)
        tst.l   d0
        beq     .nodos
        movea.l d0,a4

        lea     s_header(pc),a0
        bsr     print0
        bsr     showresident
        btst    #AFB_68040,AttnFlags+1(a6)
        bne     .is040
        lea     s_not040(pc),a0
        bsr     print0
        bra     .close
.is040:
        move.l  a5,-(sp)
        lea     gettc(pc),a5
        jsr     _LVOSupervisor(a6)
        movea.l (sp)+,a5
        move.l  d0,-(sp)
        bsr     listmem
        move.l  (sp)+,d0
        btst    #15,d0
        beq     .mmuoff
        lea     s_mmuon(pc),a0
        bsr     print0
        bra     .close
.mmuoff:
        bsr     scanboards
        tst.l   v_found(a3)
        bne     .found
        lea     s_noboard(pc),a0
        bsr     print0
        bra     .close
.found:
        bsr     probe
        bsr     report
.close:
        movea.l a4,a1
        jsr     _LVOCloseLibrary(a6)
.nodos:
        movem.l (sp)+,d2-d7/a2-a6
        moveq   #0,d0
        rts

gettc:
        movec   tc,d0
        rte

; print(a0 = format, a1 = argument array); print0 takes no arguments.
print0:
        suba.l  a1,a1
print:
        movem.l d2/a6,-(sp)
        move.l  a0,d1
        move.l  a1,d2
        movea.l a4,a6
        jsr     _LVOVPrintf(a6)
        movem.l (sp)+,d2/a6
        rts

; Report whether exec knows the ppi2000mem module, and from where.
showresident:
        lea     modname(pc),a1
        jsr     _LVOFindResident(a6)
        lea     s_nomodule(pc),a0
        tst.l   d0
        beq     .print
        lea     v_args(a3),a1
        move.l  d0,(a1)
        movea.l d0,a0
        move.l  18(a0),4(a1)            ; rt_IdString, ends in CR/LF
        lea     s_module(pc),a0
        bra     print
.print: bra     print0

; Print the system memory list: mh_Lower-mh_Upper, size, attributes,
; priority, name.
listmem:
        move.l  a2,-(sp)
        lea     s_memlist(pc),a0
        bsr     print0
        jsr     _LVOForbid(a6)
        movea.l MemList(a6),a2
.loop:  tst.l   LN_SUCC(a2)
        beq     .done
        lea     v_args(a3),a1
        move.l  mh_Lower(a2),d0
        move.l  d0,(a1)
        move.l  mh_Upper(a2),d1
        subq.l  #1,d1
        move.l  d1,4(a1)
        move.l  mh_Upper(a2),d1
        sub.l   d0,d1
        moveq   #10,d0
        lsr.l   d0,d1
        move.l  d1,8(a1)
        moveq   #0,d0
        move.w  mh_Attributes(a2),d0
        move.l  d0,12(a1)
        move.b  LN_PRI(a2),d0
        ext.w   d0
        ext.l   d0
        move.l  d0,16(a1)
        lea     s_noname(pc),a0
        move.l  LN_NAME(a2),d0
        beq     .named
        movea.l d0,a0
.named: move.l  a0,20(a1)
        lea     s_memline(pc),a0
        bsr     print
        movea.l LN_SUCC(a2),a2
        bra     .loop
.done:  jsr     _LVOPermit(a6)
        movea.l (sp)+,a2
        rts

; chunkaddr(d0 = index): a2 = address of that chunk
chunkaddr:
        moveq   #CHUNK_SHIFT,d1
        lsl.l   d1,d0
        addi.l  #RAM32_BASE,d0
        movea.l d0,a2
        rts

; List the card's autoconfig boards and remember the 24-bit RAM board.
scanboards:
        movem.l d2/a2/a5,-(sp)
        lea     expname(pc),a1
        moveq   #36,d0
        jsr     _LVOOpenLibrary(a6)
        tst.l   d0
        beq     .out
        movea.l d0,a5
        lea     s_boards(pc),a0
        bsr     print0
        suba.l  a2,a2
.scan:  movea.l a2,a0
        moveq   #-1,d0
        moveq   #-1,d1
        exg     a5,a6
        jsr     _LVOFindConfigDev(a6)
        exg     a5,a6
        tst.l   d0
        beq     .done
        movea.l d0,a2
        cmpi.b  #PPI_2000_PRODUCT,er_Product(a2)
        bne     .scan
        move.w  er_Manufacturer(a2),d0
        cmpi.w  #PPI_MANUFACTURER,d0
        beq     .ours
        cmpi.w  #PPI_MANUFACTURER_OLD,d0
        bne     .scan
.ours:  moveq   #1,d0
        move.l  d0,v_found(a3)
        lea     v_args(a3),a1
        move.l  cd_BoardAddr(a2),(a1)
        move.l  cd_BoardSize(a2),d0
        moveq   #10,d1
        lsr.l   d1,d0
        move.l  d0,4(a1)
        moveq   #0,d0
        move.w  er_Manufacturer(a2),d0
        move.l  d0,8(a1)
        moveq   #0,d0
        move.b  er_Product(a2),d0
        move.l  d0,12(a1)
        btst    #ERTB_MEMLIST,er_Type(a2)
        beq     .io
        move.l  cd_BoardAddr(a2),v_r24base(a3)
        move.l  cd_BoardSize(a2),v_r24size(a3)
        lea     s_ramboard(pc),a0
        bsr     print
        bra     .scan
.io:    movea.l cd_BoardAddr(a2),a0
        moveq   #0,d0
        move.b  PPI_STATUS(a0),d0
        move.l  d0,16(a1)
        lea     s_ioboard(pc),a0
        bsr     print
        bra     .scan
.done:  movea.l a5,a1
        jsr     _LVOCloseLibrary(a6)
.out:   movem.l (sp)+,d2/a2/a5
        rts

; Probe every chunk with interrupts off; results go to v_state, v_alias,
; v_good and v_mirror.
probe:
        movem.l d2-d7/a2/a5,-(sp)
        jsr     _LVODisable(a6)

        ; Pass 1: skip chunks the system uses; find the 24-bit alias.
        moveq   #0,d7
.p1:    move.l  d7,d0
        bsr     chunkaddr
        moveq   #0,d6
        moveq   #0,d2                   ; 24-bit address this chunk aliases
        movea.l a2,a1
        jsr     _LVOTypeOfMem(a6)
        tst.l   d0
        bne     .inuse
        lea     TOP_LONG(a2),a1
        jsr     _LVOTypeOfMem(a6)
        tst.l   d0
        beq     .alias
.inuse: moveq   #ST_INUSE,d6
        bra     .store
.alias: ; Change the top long of this chunk and see whether the same long in
        ; any 2 MB slice of the 24-bit RAM changes with it.
        move.l  v_r24base(a3),d3
        move.l  v_r24size(a3),d0
        beq     .store
        add.l   d3,d0
        movea.l d0,a5                   ; a5 = end of the 24-bit RAM
.slice: movea.l d3,a0
        adda.l  #TOP_LONG,a0
        move.l  (a0),d4                 ; 24-bit original
        move.l  TOP_LONG(a2),d5         ; 32-bit original
        move.l  d4,d0
        not.l   d0
        move.l  d0,TOP_LONG(a2)
        jsr     _LVOCacheClearU(a6)
        movea.l d3,a0
        adda.l  #TOP_LONG,a0
        move.l  d4,d0
        not.l   d0
        cmp.l   (a0),d0
        seq     d1
        move.l  d5,TOP_LONG(a2)         ; restore the 32-bit side, then the
        move.l  d4,(a0)                 ; 24-bit side (same cell if aliased)
        move.b  d1,-(sp)
        jsr     _LVOCacheClearU(a6)
        tst.b   (sp)+
        beq     .nextslice
        moveq   #ST_ALIAS,d6
        move.l  d3,d2
        bra     .store
.nextslice:
        addi.l  #1<<CHUNK_SHIFT,d3
        cmpa.l  d3,a5
        bhi     .slice
.store: lea     v_state(a3),a0
        move.l  d6,(a0,d7.l*4)
        lea     v_alias(a3),a0
        move.l  d2,(a0,d7.l*4)
        lea     v_mirror(a3),a0
        clr.l   (a0,d7.l*4)
        lea     v_good(a3),a0
        clr.l   (a0,d7.l*4)
        addq.l  #1,d7
        cmpi.l  #NCHUNKS,d7
        bcs     .p1

        ; Pass 2: save the start of every free chunk and write its pattern.
        moveq   #0,d7
.p2:    lea     v_state(a3),a0
        tst.l   (a0,d7.l*4)
        bne     .p2next
        move.l  d7,d0
        bsr     chunkaddr
        bsr     savearea
        movea.l a2,a0
        moveq   #PROBE_LONGS-1,d1
.wr:    move.l  a0,d0
        not.l   d0
        move.l  d0,(a0)+
        dbf     d1,.wr
.p2next:
        addq.l  #1,d7
        cmpi.l  #NCHUNKS,d7
        bcs     .p2
        jsr     _LVOCacheClearU(a6)

        ; Pass 3: count matching longs; a chunk holding a later chunk's
        ; pattern is the same memory as that chunk.
        moveq   #0,d7
.p3:    lea     v_state(a3),a0
        tst.l   (a0,d7.l*4)
        bne     .p3next
        move.l  d7,d0
        bsr     chunkaddr
        movea.l a2,a0
        moveq   #0,d5
        moveq   #PROBE_LONGS-1,d1
.cnt:   move.l  a0,d0
        not.l   d0
        cmp.l   (a0)+,d0
        bne     .miss
        addq.l  #1,d5
.miss:  dbf     d1,.cnt
        tst.l   d5
        bne     .keep
        move.l  (a2),d4                 ; whose pattern is this?
        move.l  d7,d6
.who:   addq.l  #1,d6
        cmpi.l  #NCHUNKS,d6
        bcc     .keep
        move.l  d6,d0
        moveq   #CHUNK_SHIFT,d1
        lsl.l   d1,d0
        addi.l  #RAM32_BASE,d0
        not.l   d0
        cmp.l   d0,d4
        bne     .who
        lea     v_mirror(a3),a0         ; chunk d6 mirrors chunk d7
        move.l  d7,d0
        addq.l  #1,d0
        move.l  d0,(a0,d6.l*4)
        moveq   #PROBE_LONGS,d5
.keep:  lea     v_good(a3),a0
        move.l  d5,(a0,d7.l*4)
.p3next:
        addq.l  #1,d7
        cmpi.l  #NCHUNKS,d7
        bcs     .p3

        ; Pass 4: restore in reverse, so a mirrored chunk gets its own
        ; original contents back last.
        moveq   #NCHUNKS-1,d7
.p4:    lea     v_state(a3),a0
        tst.l   (a0,d7.l*4)
        bne     .p4next
        move.l  d7,d0
        bsr     chunkaddr
        bsr     restorearea
.p4next:
        dbf     d7,.p4
        jsr     _LVOCacheClearU(a6)
        jsr     _LVOEnable(a6)
        movem.l (sp)+,d2-d7/a2/a5
        rts

; savearea / restorearea: copy the first PROBE_LONGS longs of chunk d7 (at a2)
; to or from its save slot.
savearea:
        bsr     saveslot
        movea.l a2,a0
        moveq   #PROBE_LONGS-1,d1
.cp:    move.l  (a0)+,(a1)+
        dbf     d1,.cp
        rts
restorearea:
        bsr     saveslot
        movea.l a2,a0
        moveq   #PROBE_LONGS-1,d1
.cp:    move.l  (a1)+,(a0)+
        dbf     d1,.cp
        rts
saveslot:
        lea     v_save(a3),a1
        move.l  d7,d0
        lsl.l   #8,d0                   ; PROBE_LONGS * 4 bytes per chunk
        adda.l  d0,a1
        rts

report:
        movem.l d2-d7/a2,-(sp)
        lea     s_chunks(pc),a0
        bsr     print0
        moveq   #0,d4                   ; MB of 32-bit-only RAM
        moveq   #0,d5                   ; MB shared with the 24-bit RAM
        moveq   #0,d7
.loop:  move.l  d7,d0
        bsr     chunkaddr
        lea     v_args(a3),a1
        move.l  a2,(a1)
        lea     v_state(a3),a0
        move.l  (a0,d7.l*4),d0
        btst    #0,d0
        beq     .notinuse
        lea     s_inuse(pc),a0
        bra     .out
.notinuse:
        btst    #1,d0
        beq     .notalias
        lea     v_alias(a3),a0
        move.l  (a0,d7.l*4),4(a1)
        addq.l  #2,d5
        lea     s_alias(pc),a0
        bra     .out
.notalias:
        lea     v_mirror(a3),a0
        move.l  (a0,d7.l*4),d0
        beq     .notmirror
        subq.l  #1,d0
        moveq   #CHUNK_SHIFT,d1
        lsl.l   d1,d0
        addi.l  #RAM32_BASE,d0
        move.l  d0,4(a1)
        lea     s_mirror(pc),a0
        bra     .out
.notmirror:
        lea     v_good(a3),a0
        move.l  (a0,d7.l*4),d0
        move.l  d0,4(a1)
        bne     .some
        lea     s_none(pc),a0
        bra     .out
.some:  cmpi.l  #PROBE_LONGS,d0
        bne     .flaky
        addq.l  #2,d4
        lea     s_ram(pc),a0
        bra     .out
.flaky: lea     s_flaky(pc),a0
.out:   bsr     print
        addq.l  #1,d7
        cmpi.l  #NCHUNKS,d7
        bcs     .loop
        lea     v_args(a3),a1
        move.l  d4,(a1)
        move.l  d5,4(a1)
        lea     s_total(pc),a0
        bsr     print
        movem.l (sp)+,d2-d7/a2
        rts

dosname:    dc.b "dos.library",0
modname:    dc.b "ppi2000mem",0
s_module:   dc.b "ppi2000mem module: resident at $%08lx, %s",0
s_nomodule: dc.b "ppi2000mem module: not resident",10,0
expname:    dc.b "expansion.library",0
s_header:   dc.b "ppiprobe 1.2 - PP&S 2000/040 memory probe (adds nothing)",10,0
s_not040:   dc.b "The CPU is not a 68040. Is the card switched to 68000 mode?",10,0
s_mmuon:    dc.b "The MMU is on, so the unused addresses cannot be probed safely.",10
            dc.b "Boot with no startup-sequence and run ppiprobe again.",10,0
s_noboard:  dc.b "No PP&S 2000/040 autoconfig board found; not probing.",10,0
s_memlist:  dc.b 10,"System memory list:",10,0
s_memline:  dc.b "  $%08lx-$%08lx %6ldK  attr $%04lx  pri %4ld  %.24s",10,0
s_noname:   dc.b "(no name)",0
s_boards:   dc.b 10,"PP&S autoconfig boards:",10,0
s_ramboard: dc.b "  $%08lx %5ldK  RAM  manufacturer %ld, product %ld",10,0
s_ioboard:  dc.b "  $%08lx %5ldK  I/O  manufacturer %ld, product %ld, "
            dc.b "jumper byte $%02lx",10,0
s_chunks:   dc.b 10,"32-bit area, 2 MB chunks:",10,0
s_inuse:    dc.b "  $%08lx  already in the system memory list, not tested",10,0
s_alias:    dc.b "  $%08lx  same memory as the 24-bit RAM at $%08lx",10,0
s_mirror:   dc.b "  $%08lx  mirror of $%08lx",10,0
s_none:     dc.b "  $%08lx  no RAM",10,0
s_ram:      dc.b "  $%08lx  RAM",10,0
s_flaky:    dc.b "  $%08lx  UNRELIABLE: %ld of 64 test longs correct",10,0
s_total:    dc.b 10,"32-bit-only RAM: %ld MB, shared with the 24-bit RAM: %ld MB",10,0
        even

        section vars,bss
vars:
v_found     equ 0
v_r24base   equ 4
v_r24size   equ 8
v_args      equ 12                      ; 8 longs
v_state     equ v_args+8*4              ; NCHUNKS longs each
v_alias     equ v_state+NCHUNKS*4
v_mirror    equ v_alias+NCHUNKS*4
v_good      equ v_mirror+NCHUNKS*4
v_save      equ v_good+NCHUNKS*4        ; NCHUNKS * PROBE_LONGS longs
v_end       equ v_save+NCHUNKS*PROBE_LONGS*4
        ds.b    v_end
