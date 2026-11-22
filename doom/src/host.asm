; UniDoom MZ-800 host. UniCard protocol and planar transfer from UniFractal.
; Direct load at 3000h avoids relocation and the CG-ROM window at 1000h.
        org 03000h
start:  di
        ld sp,0d000h
        out (0e0h),a             ; low ROM off
        out (0e1h),a             ; high ROM off
        ld a,2
        out (0ceh),a             ; 320x200 / 16 colours
        in a,(0e0h)              ; VRAM window on
        ld bc,001cfh
        xor a
scroll_reset:
        out (c),a
        inc b
        bit 2,b
        jr z,scroll_reset
        out (c),a                ; 04cf
        inc b
        out (c),a                ; 05cf
        inc b
        out (c),a                ; 06cf border black
        out (0f0h),a
        ld a,011h
        out (0f0h),a
        ld a,022h
        out (0f0h),a
        ld a,033h
        out (0f0h),a
        ld a,040h
        out (0f0h),a             ; identity palette group 0
        ld a,08ah
        out (0d3h),a             ; PPI: keyboard A out / B in
        ld a,00fh
        out (0cch),a             ; SINGLE write to all four planes
        ld hl,08000h
        ld de,08001h
        ld bc,01fffh
        ld (hl),0
        ldir
        call keyboard_init
        call upload
frame_loop:
        di
        ld a,(pending_key)
        ld e,a
        xor a
        ld (pending_key),a
        ei
        call native_call
        call copy_frame
        jp frame_loop            ; always animate, including key=0

; Preserve the scaffold's 50 Hz PIO/VBLANK IM2 keyboard service. Events are
; retained during ARM computation/VRAM transfer; arrows repeat every 6 ticks.
keyboard_init:
        xor a
        ld (pending_key),a
        ld (held_key),a
        ld (repeat_ticks),a
        ld (buttons),a
        ld a,high key_vector
        ld i,a
        im 2
        ld hl,pio_config
        ld bc,006fch
        otir
        ei
        ret
keyboard_irq:
        push af
        push bc
        push de
        push hl
        call scan_key
        ld hl,held_key
        cp (hl)
        jr z,key_held
        ld (hl),a
        or a
        jr z,key_released
        ld (pending_key),a
key_released:
        xor a
        ld (repeat_ticks),a
        jr key_irq_done
key_held:
        cp 'u'
        jr z,key_repeat
        cp 'd'
        jr z,key_repeat
        cp 'l'
        jr z,key_repeat
        cp 'r'
        jr nz,key_irq_done
key_repeat:
        ld hl,repeat_ticks
        inc (hl)
        ld a,(hl)
        cp 6
        jr c,key_irq_done
        ld (hl),0
        ld a,(held_key)
        ld (pending_key),a
key_irq_done:
        pop hl
        pop de
        pop bc
        pop af
        ei
        reti

; Read the whole matrix: event byte plus simultaneous held movement/actions.
scan_key:
        xor a
        ld (scanned_key),a
        ld hl,key_table
        ld c,0
        ld d,0
scan_column:
        ld a,c
        out (0d0h),a
        in a,(0d1h)
        ld e,a
        ld b,8
scan_bit:
        rlc e
        jr c,next_key_bit
        ld a,(hl)
        cp 'u'
        jr z,forward_key
        cp 'W'
        jr z,forward_key
        cp 'd'
        jr z,back_key
        cp 'S'
        jr z,back_key
        cp 'l'
        jr z,left_key
        cp 'A'
        jr z,left_key
        cp 'r'
        jr z,right_key
        cp 'D'
        jr z,right_key
        cp 'Q'
        jr z,strafe_left_key
        cp 'E'
        jr z,strafe_right_key
        cp ' '
        jr z,fire_key
        cp 'F'
        jr nz,other_key
        set 7,d
other_key:
        or a
        jr z,next_key_bit
        ld (scanned_key),a        ; controls take priority over movement events
        jr next_key_bit
forward_key: set 0,d
        jr movement_key
back_key: set 1,d
        jr movement_key
left_key: set 2,d
        jr movement_key
right_key: set 3,d
        jr movement_key
strafe_left_key: set 4,d
        jr movement_key
strafe_right_key: set 5,d
        jr movement_key
fire_key: set 6,d
movement_key:
        ld a,(scanned_key)
        or a
        jr nz,next_key_bit
        ld a,(hl)
        ld (scanned_key),a
next_key_bit:
        inc hl
        dec b
        jp nz,scan_bit
        inc c
        ld a,c
        cp 10
        jp nz,scan_column
        ld a,d
        ld (buttons),a
        ld a,(scanned_key)
        ret

; Set cursor to 20020000h. Payload includes entry/FB pointers and ABI bytes.
code_address:
        ld a,0cah
        out (050h),a
        xor a
        out (051h),a
        out (051h),a
        ld a,2
        out (051h),a
        ld a,020h
        out (051h),a
        ret
upload:
        xor a
        out (050h),a
        call code_address
        ld hl,arm_payload
        ld de,arm_payload_end-arm_payload
        ld c,051h
upload_byte:
        ld a,0cbh
        out (050h),a
        outi
        dec de
        ld a,d
        or e
        jr nz,upload_byte
        call code_address
        ld hl,arm_payload
        ld de,arm_payload_end-arm_payload
verify_byte:
        ld a,0cch
        out (050h),a
        in a,(051h)
        cp (hl)
        jp nz,failed
        inc hl
        dec de
        ld a,d
        or e
        jr nz,verify_byte
        ret

; E = event. Native call status is busy while data port returns CDh.
native_call:
        ld a,0cah
        out (050h),a
        ld a,8
        out (051h),a
        xor a
        out (051h),a
        ld a,2
        out (051h),a
        ld a,020h
        out (051h),a
        ld a,0cbh
        out (050h),a
        ld a,e
        out (051h),a
        ld a,0cah
        out (050h),a
        ld a,10
        out (051h),a
        xor a
        out (051h),a
        ld a,2
        out (051h),a
        ld a,020h
        out (051h),a
        ld a,0cbh
        out (050h),a
        ld a,(buttons)
        out (051h),a             ; +0ah held mask; +09h init flag is preserved
        ld a,0cdh
        out (050h),a
        ld hl,arm_payload
        ld b,4
call_pointer:
        ld a,(hl)
        out (051h),a
        inc hl
        djnz call_pointer
        ld de,0
wait_native:
        ld b,64
poll_delay:
        djnz poll_delay
        in a,(051h)
        cp 0cdh
        ret nz
        dec de
        ld a,d
        or e
        jr nz,wait_native
        jp failed                ; bounded wait; no infinite busy loop

; Read 4x8192 bytes into the GDG's same 8000h window, plane by plane.
copy_frame:
        ld a,0cah
        out (050h),a
        ld hl,arm_payload+4
        ld b,4
frame_pointer:
        ld a,(hl)
        out (051h),a
        inc hl
        djnz frame_pointer
        ld hl,08000h
        ld d,1
next_plane:
        ld c,0cch
        out (c),d
        ld c,051h
next_block:
        ld a,0ceh
        out (050h),a
        ld a,16
        out (c),a
        ini
        ini
        ini
        ini
        ini
        ini
        ini
        ini
        ini
        ini
        ini
        ini
        ini
        ini
        ini
        ini
        bit 5,h
        jr z,next_block
        res 5,h
        rlc d
        bit 4,d
        jr z,next_plane
frame_done:
        ret

failed: ld bc,006cfh
        ld a,10                  ; bright red border: interface/timeout failure
        out (c),a
failure_loop:
        jr failure_loop
pending_key: db 0
held_key: db 0
repeat_ticks: db 0
buttons: db 0
scanned_key: db 0
pio_config: db 0,0ffh,03fh,097h,0dfh,083h
key_table:
        incbin "build/key_table.bin"
        defs (256-($ & 255)) & 255
key_vector:
        dw keyboard_irq
arm_payload:
        incbin "build/unicard.bin"
arm_payload_end:
