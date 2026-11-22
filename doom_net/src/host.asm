; UniDoom Direct host: upload/input/call only. No Sharp VRAM accesses/copies.
; Direct load at 3000h avoids relocation and the CG-ROM window at 1000h.
FRAME_DIVISOR equ 3               ; 50 Hz PIO/VBLANK / 3 = up to 16.7 FPS
        org 03000h
start:  di
        ld sp,0d000h
        out (0e0h),a             ; low ROM off
        out (0e1h),a             ; high ROM off
        ld a,2
        out (0ceh),a             ; 320x200 / 16 colours
        in a,(0e1h)              ; CPU VRAM window OFF: direct VGA is ARM-owned
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
        call sound_init
        call keyboard_init
        call upload
frame_loop:
        di
        ld a,(frame_ticks)
        cp FRAME_DIVISOR
        jr c,wait_frame
        xor a
        ld (frame_ticks),a
        ld a,(pending_key)
        ld e,a
        xor a
        ld (pending_key),a
        ei
        call net_cycle
        jr nc,render_frame
        ld a,FRAME_DIVISOR-1     ; poll again next 50 Hz tick, without rendering
        ld (frame_ticks),a
        jp frame_done
render_frame:
        xor a
        ld (frame_ticks),a       ; relay waits belong to this frame
        call native_call
        call verify_video        ; ARM returns zero when firmware pointer is invalid
        call sound_fetch
        call net_after
frame_done:
        jp frame_loop            ; ARM has already written the live VGA buffer
wait_frame:
        ei
        halt
        jp frame_loop

; Preserve the scaffold's 50 Hz PIO/VBLANK IM2 keyboard service. Events are
; retained during ARM computation; arrows repeat every 6 ticks.
keyboard_init:
        xor a
        ld (pending_key),a
        ld (held_key),a
        ld (repeat_ticks),a
        ld (buttons),a
        ld (cheat_state),a
        ld a,FRAME_DIVISOR
        ld (frame_ticks),a        ; render first frame immediately after upload
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
        ld hl,(net_clock)
        inc hl
        ld (net_clock),hl
        ld hl,frame_ticks
        ld a,(hl)
        cp FRAME_DIVISOR
        jr nc,ticks_saturated
        inc (hl)
ticks_saturated:
        call sound_tick          ; sound envelopes run at 50 Hz during ARM calls
        call music_tick          ; independent of ARM rendering and frame pacing
        call scan_key
        ld hl,held_key
        cp (hl)
        jr z,key_held
        ld (hl),a
        or a
        jr z,key_released
        ld (pending_key),a
        cp 'B'
        call z,music_toggle
        ld a,(net_mode)
        or a
        ld a,(pending_key)
        call z,cheat_key           ; capture DDQD even while ARM is busy
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

; Recognize key DOWN transitions at 50 Hz, independent of rendering speed.
; Final event FEh toggles god mode on ARM. Repeated D prefixes are retained.
cheat_key:
        ld b,a
        ld a,(cheat_state)
        cp 2
        jr z,cheat_need_q
        cp 3
        jr z,cheat_final_d
        ld a,b
        cp 'D'
        jr nz,cheat_clear
        ld a,(cheat_state)
        inc a
        jr cheat_store
cheat_need_q:
        ld a,b
        cp 'D'
        ret z
        cp 'Q'
        jr nz,cheat_clear
        ld a,3
        jr cheat_store
cheat_final_d:
        ld a,b
        cp 'D'
        jr nz,cheat_clear
        ld a,254
        ld (pending_key),a
cheat_clear:
        xor a
cheat_store:
        ld (cheat_state),a
        ret

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
        call net_copy
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

; Header +04h is zero on failure, otherwise a validated 1000xxxxh VGA base.
; Inspect its high byte after every call; invalid/old firmware stops safely.
verify_video:
        ld a,0cah
        out (050h),a
        ld a,7
        out (051h),a
        xor a
        out (051h),a
        ld a,2
        out (051h),a
        ld a,020h
        out (051h),a
        ld a,0cch
        out (050h),a
        in a,(051h)
        cp 010h
        jp nz,failed
        ret

; ARM event bitmask at ABI +0Bh. Read one byte; never read back the screen.
sound_fetch:
        ld a,0cah
        out (050h),a
        ld a,11
        out (051h),a
        xor a
        out (051h),a
        ld a,2
        out (051h),a
        ld a,020h
        out (051h),a
        ld a,0cch
        out (050h),a
        in a,(051h)
        or a
        ret z
        di
        ld de,0
        ld b,8
sound_priority:
        rrca
        jr nc,sound_next_bit
        ld d,e
sound_next_bit:
        inc e
        djnz sound_priority
        ld l,d
        ld h,0
        add hl,hl
        ld de,sfx_table
        add hl,de
        ld e,(hl)
        inc hl
        ld d,(hl)
        ex de,hl
        ld a,(hl)
        inc hl
        ld (sound_left),a
        ld (sound_ptr),hl
        ld a,0e4h               ; white noise, fixed divider
        call psg_write
        ei
        ret
sound_init:
        xor a
        ld (sound_left),a
        call music_init
sound_mute:
        ld a,09fh
        call psg_write
        ld a,0bfh
        call psg_write
        ld a,0dfh
        call psg_write
        ld a,0ffh
        jp psg_write
sound_tick:
        ld a,(sound_left)
        or a
        ret z
        dec a
        ld (sound_left),a
        ld hl,(sound_ptr)
        ld e,(hl)
        inc hl
        ld d,(hl)
        inc hl
        ld c,(hl)
        inc hl
        ld b,(hl)
        inc hl
        ld (sound_ptr),hl
        ld a,e
        and 15
        or 080h                 ; tone channel 0: low four divider bits
        call psg_write
        ld a,e
        rrca
        rrca
        rrca
        rrca
        and 15
        ld e,a
        ld a,d
        rlca
        rlca
        rlca
        rlca
        or e
        and 63
        call psg_write
        ld a,c
        or 090h
        call psg_write
        ld a,b
        or 0f0h
        jp psg_write
psg_write:
        out (0f2h),a
        push bc                 ; give the PSG ample time between writes
        ld b,4
psg_delay:
        djnz psg_delay
        pop bc
        ret

; Music owns tone channels 1/2. Sound effects own tone 0 and have priority
; over music percussion on the shared noise channel. AF/BC/DE/HL are saved
; by keyboard_irq, so no alternate registers or extra stack are needed here.
music_player:
music_init:
        ld a,1
        ld (music_enabled),a
music_restart:
        xor a
        ld (music_phase),a
        ld hl,music_song
        ld (music_ptr),hl
        ld hl,MUSIC_RECORD_COUNT
        ld (music_records_left),hl
        xor a
        ld (music_lz_left),a
        ld (music_lz_bits),a
        ld hl,0a000h
        ld (music_lz_write),hl
        ret
music_toggle:
        ld a,(music_enabled)
        xor 1
        ld (music_enabled),a
        jr nz,music_restart
        ld a,0bfh
        call psg_write
        ld a,0dfh
        call psg_write
        ld a,(sound_left)
        or a
        ret nz
        ld a,0ffh
        jp psg_write
music_tick:
        ld a,(music_enabled)
        or a
        ret z
        ld a,(music_phase)
        or a
        jr nz,music_play_notes
        ld hl,(music_records_left)
        ld a,h
        or l
        call z,music_restart
        ld hl,(music_records_left)
        dec hl
        ld (music_records_left),hl
        call music_read
        ld (music_duration),a
        call music_read
        ld (music_lead),a
        call music_read
        ld (music_bass),a
        call music_read
        ld (music_drum),a
music_play_notes:
        ld a,(music_lead)
        ld c,0a0h               ; channel 1 frequency latch
        ld b,7                  ; lead envelope attenuation
        call music_voice
        ld a,(music_bass)
        ld c,0c0h               ; channel 2 frequency latch
        ld b,5
        call music_voice
        ld a,(sound_left)
        or a
        jr nz,music_advance      ; SFX has exclusive use of noise while active
        ld a,(music_drum)
        add a,a
        ld l,a
        ld h,0
        ld de,music_drums
        add hl,de
        ld a,(hl)
        call psg_write
        inc hl
        ld a,(music_phase)
        cp 8
        jr nc,music_drum_silent
        add a,a
        add a,(hl)
        cp 16
        jr c,music_drum_volume
music_drum_silent:
        ld a,15
music_drum_volume:
        or 0f0h
        call psg_write
music_advance:
        ld a,(music_phase)
        inc a
        ld hl,music_duration
        cp (hl)
        jr c,music_store_phase
        xor a
music_store_phase:
        ld (music_phase),a
        ret

; A=note index, C=frequency latch, B=initial attenuation.
music_voice:
        or a
        jr z,music_rest
        add a,a
        ld l,a
        ld h,0
        ld de,music_notes
        add hl,de
        ld e,(hl)
        inc hl
        ld d,(hl)
        ld a,e
        and 15
        or c
        call psg_write
        ld a,e
        rrca
        rrca
        rrca
        rrca
        and 15
        ld e,a
        ld a,d
        rlca
        rlca
        rlca
        rlca
        or e
        and 63
        call psg_write
        ld a,(music_phase)
        cp 5
        jr c,music_voice_decay
        ld a,4
music_voice_decay:
        add a,b
        jr music_voice_volume
music_rest:
        ld a,15
music_voice_volume:
        or c
        or 010h
        jp psg_write
; Streaming LZSS: eight token flags, 11-bit distance, 5-bit length.
; The 2 KB history is ordinary Sharp RAM A000h..A7FFh, outside VRAM.
; AF/BC/DE/HL are caller-saved inside the already protected keyboard IRQ.
music_read:
        ld a,(music_lz_left)
        or a
        jr z,music_lz_token
        ld hl,(music_lz_match)
        ld a,(hl)
        inc hl
        res 3,h
        ld (music_lz_match),hl
        ld hl,music_lz_left
        dec (hl)
        jr music_lz_emit
music_lz_token:
        ld a,(music_lz_bits)
        or a
        jr nz,music_lz_flag
        ld hl,(music_ptr)
        ld a,(hl)
        inc hl
        ld (music_ptr),hl
        ld (music_lz_flags),a
        ld a,8
        ld (music_lz_bits),a
music_lz_flag:
        ld hl,music_lz_bits
        dec (hl)
        ld a,(music_lz_flags)
        srl a
        ld (music_lz_flags),a
        jr c,music_lz_reference
        ld hl,(music_ptr)
        ld a,(hl)
        inc hl
        ld (music_ptr),hl
music_lz_emit:
        ld hl,(music_lz_write)
        ld (hl),a
        inc hl
        res 3,h
        ld (music_lz_write),hl
        ret
music_lz_reference:
        ld hl,(music_ptr)
        ld e,(hl)
        inc hl
        ld d,(hl)
        inc hl
        ld (music_ptr),hl
        ld a,e
        and 31
        add a,3
        ld (music_lz_left),a
        ld b,5
music_lz_shift:
        srl d
        rr e
        djnz music_lz_shift
        inc de
        ld hl,(music_lz_write)
        or a
        sbc hl,de
        ld a,h
        and 7
        or 0a0h
        ld h,a
        ld (music_lz_match),hl
        jp music_read
music_player_end:
music_drums: db 0e4h,15,0e2h,7,0e5h,8,0e4h,12

failed: di
        call sound_mute
        ld bc,006cfh
        ld a,10                  ; bright red border: interface/timeout failure
        out (c),a
failure_loop:
        jr failure_loop
pending_key: db 0
held_key: db 0
repeat_ticks: db 0
buttons: db 0
scanned_key: db 0
frame_ticks: db 0
sound_left: db 0
cheat_state: db 0
sound_ptr: dw 0
music_state:
music_enabled: db 0
music_phase: db 0
music_ptr: dw 0
music_lead: db 0
music_bass: db 0
music_drum: db 0
music_duration: db 1
music_records_left: dw 0
music_lz_left: db 0
music_lz_bits: db 0
music_lz_flags: db 0
music_lz_write: dw 0
music_lz_match: dw 0
music_state_end:
        include "build/network.inc"
        include "src/network.asm"
        include "build/sfx.inc"
        include "build/music.inc"
pio_config: db 0,0ffh,03fh,097h,0dfh,083h
key_table:
        incbin "build/key_table.bin"
        defs (256-($ & 255)) & 255
key_vector:
        dw keyboard_irq
arm_payload:
        incbin "build/unicard.bin"
arm_payload_end:
