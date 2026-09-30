; ppiload - install ppi2000mem as a reset-proof module and reboot.
;
; A LoadModule for this one module, so the test floppy needs nothing from
; AmigaOS. The module is copied into chip RAM, which exists at every reset,
; and registered through ExecBase->KickMemPtr/KickTagPtr, so exec runs it at
; the next cold start exactly as if it were in ROM. Switching the power off
; removes it again.
;
; The module is included as a raw binary assembled at address 0, so each
; RomTag pointer holds an offset into the module; ppiload adds the load address.

        machine 68000

; exec.library
_LVOFindResident        equ -96
_LVOForbid              equ -132
_LVOAllocMem            equ -198
_LVOCloseLibrary        equ -414
_LVOOpenLibrary         equ -552
_LVOSumKickData         equ -612
_LVOCopyMem             equ -624
_LVOCacheClearU         equ -636
_LVOColdReboot          equ -726
KickMemPtr              equ $222
KickTagPtr              equ $226
KickCheckSum            equ $22a

; dos.library
_LVODelay               equ -198
_LVOPutStr              equ -948

MEMF_PUBLIC             equ 1
MEMF_CHIP               equ 2
MEMF_CLEAR              equ $10000

RTC_MATCHWORD           equ $4afc
RT_MATCHTAG             equ 2
RT_ENDSKIP              equ 6
RT_NAME                 equ 14
RT_IDSTRING             equ 18
RT_INIT                 equ 22

; The block allocated for the module: a MemList with one MemEntry covering
; the whole block (so exec protects it across resets), the KickTag table,
; then the module itself.
ML_NUMENTRIES           equ 14
ML_ME_ADDR              equ 16
ML_ME_LENGTH            equ 20
TAGS                    equ 24          ; RomTag pointer, link to old table, 0
CODE                    equ 40
MODULE_SIZE             equ modend-modcode
BLOCK_SIZE              equ CODE+MODULE_SIZE

        section code,code

; d7 = return code, a2 = block, a3 = RomTag in the block, a5 = DOSBase,
; a6 = ExecBase
start:
        movem.l d2-d7/a2-a6,-(sp)
        moveq   #20,d7                  ; RETURN_FAIL until installed
        movea.l 4.w,a6
        lea     dosname(pc),a1
        moveq   #37,d0
        jsr     _LVOOpenLibrary(a6)
        tst.l   d0
        beq     .exit
        movea.l d0,a5

        lea     modname(pc),a1
        jsr     _LVOFindResident(a6)
        tst.l   d0
        beq     .install
        lea     s_already(pc),a0
        bsr     print
        moveq   #5,d7                   ; RETURN_WARN
        bra     .close

.install:
        move.l  #BLOCK_SIZE,d0
        move.l  #MEMF_PUBLIC|MEMF_CHIP|MEMF_CLEAR,d1
        jsr     _LVOAllocMem(a6)
        tst.l   d0
        bne     .gotmem
        lea     s_nomem(pc),a0
        bsr     print
        bra     .close
.gotmem:
        movea.l d0,a2
        lea     modcode(pc),a0
        lea     CODE(a2),a1
        move.l  #MODULE_SIZE,d0
        jsr     _LVOCopyMem(a6)

        ; Find the RomTag: the $4AFC whose match pointer is its own offset.
        lea     CODE(a2),a3
        moveq   #0,d0
.find:  cmpi.w  #RTC_MATCHWORD,(a3,d0.l)
        bne     .next
        cmp.l   RT_MATCHTAG(a3,d0.l),d0
        beq     .found
.next:  addq.l  #2,d0
        cmpi.l  #MODULE_SIZE-RT_INIT-4,d0
        bls     .find
        lea     s_notag(pc),a0          ; can't happen with a good build
        bsr     print
        bra     .close
.found: move.l  a3,d1                   ; load address of the module
        adda.l  d0,a3                   ; a3 = RomTag
        add.l   d1,RT_MATCHTAG(a3)
        add.l   d1,RT_ENDSKIP(a3)
        add.l   d1,RT_NAME(a3)
        add.l   d1,RT_IDSTRING(a3)
        add.l   d1,RT_INIT(a3)

        move.w  #1,ML_NUMENTRIES(a2)
        move.l  a2,ML_ME_ADDR(a2)
        move.l  #BLOCK_SIZE,ML_ME_LENGTH(a2)

        lea     s_install(pc),a0
        bsr     print
        movea.l RT_IDSTRING(a3),a0
        bsr     print
        lea     s_reboot(pc),a0
        bsr     print
        exg     a5,a6
        moveq   #50,d1                  ; one second to read it
        jsr     _LVODelay(a6)
        exg     a5,a6

        jsr     _LVOForbid(a6)
        lea     TAGS(a2),a1
        move.l  a3,(a1)
        move.l  KickTagPtr(a6),d0       ; keep any existing KickTags
        beq     .notags
        bset    #31,d0                  ; bit 31 marks a link to another table
.notags:
        move.l  d0,4(a1)
        clr.l   8(a1)
        move.l  KickMemPtr(a6),(a2)     ; MemList ln_Succ: chain the old list
        move.l  a2,KickMemPtr(a6)
        move.l  a1,KickTagPtr(a6)
        jsr     _LVOSumKickData(a6)
        move.l  d0,KickCheckSum(a6)
        jsr     _LVOCacheClearU(a6)
        jsr     _LVOColdReboot(a6)      ; doesn't return

.close:
        movea.l a5,a1
        jsr     _LVOCloseLibrary(a6)
.exit:
        move.l  d7,d0
        movem.l (sp)+,d2-d7/a2-a6
        rts

; print(a0 = string)
print:
        move.l  a6,-(sp)
        move.l  a0,d1
        movea.l a5,a6
        jsr     _LVOPutStr(a6)
        movea.l (sp)+,a6
        rts

dosname:    dc.b "dos.library",0
modname:    dc.b "ppi2000mem",0
s_already:  dc.b "ppi2000mem is already resident. Switch the power off to remove it.",10,0
s_nomem:    dc.b "Not enough chip memory.",10,0
s_notag:    dc.b "No RomTag found in the module.",10,0
s_install:  dc.b "Installing ",0
s_reboot:   dc.b "Rebooting; switch the power off to remove it again.",10,0
        even
version:    dc.b "$VER: ppiload 1.0 (30.9.2026)",0
        even

        cnop    0,4
modcode: incbin "build/ppi2000mem.bin"
modend:
