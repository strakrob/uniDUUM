; Independent implementation of BomberNet's game-independent NET API.
; UniCard mk3b Ethernet firmware owns TCP; Z80 owns rooms and lockstep.
; ARM owns the game. Networking never interrupts an ARM command.
net_cycle:
        ld a,e
        ld (net_event),a
        ld a,(net_mode)
        cp 2
        jr nz,net_event_saved
        ld a,e
        cp 'M'
        jr z,net_save_view
        cp 'L'
        jr nz,net_event_saved
net_save_view:
        ld (net_local_event),a
net_event_saved:
        ld a,(net_mode)
        or a
        jp z,net_offline
        ld a,e
        cp 27
        jp z,net_cancel
        ld a,(net_ui)
        cp 5
        jp nc,net_return
        cp 3
        jp z,net_select_count
        cp 2
        jp z,net_enter_code
        ld a,(net_mode)
        cp 2
        jp z,net_running
        jp net_lobby
net_offline:
        ld a,e
        cp 'H'
        jp z,net_host
        cp 'J'
        jp nz,net_return
        call net_detect
        jp nz,net_missing
        ld a,1
        ld (net_mode),a
        inc a
        ld (net_ui),a
        xor a
        ld (net_code_pos),a
        ld hl,net_code
        ld b,4
net_clear_code:
        ld (hl),a
        inc hl
        djnz net_clear_code
        jp net_no_event
net_host:
        call net_detect
        jp nz,net_missing
        ld a,1
        ld (net_mode),a
        ld a,3
        ld (net_ui),a
        jp net_no_event
net_select_count:
        ld a,(net_event)
        sub '0'
        cp 2
        jp c,net_no_event
        cp 5
        jp nc,net_no_event
        ld (net_slots),a
        ld (net_create_params+4),a
        ld a,0a1h
        out (050h),a
        ld hl,net_create_params
        ld bc,01751h
        otir
        call net_output
        jp nz,net_error
        ld hl,net_reply
        ld b,6
        call net_read
        ld hl,net_reply
        ld de,net_code
        ld bc,4
        ldir
        xor a
        ld (net_slot),a
        ld (net_sector),a
        ld a,1
        ld (net_ui),a
        jp net_no_event
net_enter_code:
        ld a,(net_event)
        cp 8
        jp z,net_backspace
        cp 127
        jp z,net_backspace
        cp 'A'
        jp c,net_no_event
        cp 'Z'+1
        jp nc,net_no_event
        ld hl,net_code
        ld a,(net_code_pos)
        ld c,a
        ld b,0
        add hl,bc
        ld a,(net_event)
        ld (hl),a
        ld a,c
        inc a
        ld (net_code_pos),a
        cp 4
        jp nz,net_no_event
        ld a,0a2h
        out (050h),a
        ld hl,net_create_params
        ld bc,00451h
        otir
        ld hl,net_code
        ld bc,00451h
        otir
        ld a,13
        out (051h),a
        call net_output
        jp nz,net_error
        ld hl,net_reply
        ld b,20
        call net_read
        ld a,(net_reply)
        cp 4
        jp nc,net_bad_param
        ld (net_slot),a
        ld a,(net_reply+1)
        cp 2
        jp c,net_bad_param
        cp 5
        jp nc,net_bad_param
        ld (net_slots),a
        ld a,(net_reply+2)
        cp 2
        jp nz,net_bad_param
        ld a,(net_reply+3)
        cp 2
        jp nz,net_bad_param
        ld a,(net_reply+4)
        cp 2
        jp nz,net_bad_param
        ld a,(net_reply+5)
        cp 2
        jp nc,net_bad_param
        ld (net_sector),a
        ld a,1
        ld (net_ui),a
        jp net_no_event
net_backspace:
        ld a,(net_code_pos)
        or a
        jp z,net_no_event
        dec a
        ld (net_code_pos),a
        ld l,a
        ld h,0
        ld de,net_code
        add hl,de
        ld (hl),0
        jp net_no_event
net_lobby:
        call net_get_status
        jp nz,net_error
        ld a,(net_reply)
        cp 3
        jp z,net_start
        cp 2
        jp nz,net_dropped
        ld a,(net_reply+2)
        ld (net_mask),a          ; lobby: count, game: participant mask
        ld a,(net_reply+3)
        ld (net_ready_mask),a
        ld a,(net_event)
        cp ' '
        jp nz,net_no_event
        ld a,(net_mask)
        cp 2
        jp c,net_no_event
        ld a,(net_slot)
        or a
        jp nz,net_ready
        ; Host starts only after exactly the selected player count has joined.
        ld a,(net_slots)
        ld b,a
        ld a,(net_mask)
        cp b
        jp nz,net_no_event
        ; Host must also be last to ready.
        call net_member_mask
        and 0feh
        ld b,a
        ld a,(net_ready_mask)
        and b
        cp b
        jp nz,net_no_event
net_ready:
        ld a,0a4h
        out (050h),a
        ld a,1
        out (051h),a
        call net_output
        jp nz,net_error
        ld hl,net_reply
        ld b,4
        call net_read
        jp net_no_event
net_start:
        ld a,0a4h
        out (050h),a
        ld a,1
        out (051h),a
        call net_output
        jp nz,net_error
        ld hl,net_reply+8
        ld b,4
        call net_read
        ld hl,(net_reply+10)
        ld a,h
        or l
        jp nz,net_bad_param      ; this build starts at frame 0 only
        ld (net_frame),hl
        ld a,(net_reply+2)
        ld (net_mask),a
        call net_member_mask
        ld (net_mask),a
        ld a,2
        ld (net_mode),a
        xor a
        ld (net_ui),a
        ld (net_wait_visible),a
        ld (net_sent),a
        ld (net_queued),a
        ld (net_input),a
        ld (net_input+1),a
        call net_load_players
        ; Prime the two-frame input delay with neutral controls.
        ld hl,0
        call net_send_frame
        jp nz,net_error
        ld hl,1
        call net_send_frame
        jp nz,net_error
        call net_reset_clock
        ld a,4
        ld (net_ui),a
        xor a
        ld (net_event),a
        jp net_hold_frame        ; first game image waits for complete frame 0
net_member_mask:
        ld a,(net_mask)
        ld b,a
        ld a,1
net_mask_shift:
        add a,a
        djnz net_mask_shift
        dec a
        ret
net_running:
        call net_get_status
        jp nz,net_error
        ld a,(net_reply)
        cp 4
        jp z,net_desync
        cp 3
        jp nz,net_dropped
        ld a,(net_sent)
        or a
        jp z,net_sample
        ld a,(net_event)
        or a
        jp z,net_poll
        ld (net_queued),a
        jp net_poll
net_sample:
        ld a,(net_queued)
        or a
        jp nz,net_use_queued
        ld a,(net_event)
net_use_queued:
        ld (net_input),a
        xor a
        ld (net_queued),a
        ld a,(buttons)
        ld (net_input+1),a
        ; Recover movement/use short taps that ended between game frames.
        and 63
        jp nz,net_send_delayed
        ld a,(net_input)
        ld hl,net_tap_table
        ld b,13
net_tap_find:
        cp (hl)
        inc hl
        jp z,net_tap_found
        inc hl
        djnz net_tap_find
        jp net_send_delayed
net_tap_found:
        ld a,(net_input+1)
        or (hl)
        ld (net_input+1),a
net_send_delayed:
        ld hl,(net_frame)
        inc hl
        inc hl
        call net_send_frame
        jp nz,net_error
        ld a,1
        ld (net_sent),a
net_poll:
        ld a,0a6h
        out (050h),a
        ld hl,(net_frame)
        call net_write_word
        call net_output
        jp nz,net_error
        xor a
        ld hl,net_reply
        ld b,10
net_clear_reply:
        ld (hl),a
        inc hl
        djnz net_clear_reply
        ld a,(net_slots)
        add a,a
        add a,2
        ld b,a
        ld hl,net_reply
        call net_read
        ld hl,(net_reply)
        ld a,h
        and l
        inc a
        jp z,net_wait_frame      ; FFFF means no complete frame, not newest
        ld de,(net_frame)
        or a
        sbc hl,de
        jp c,net_wait_frame
        ld hl,net_reply+2
        ld de,net_keys
        ld bc,8
        ldir
        xor a
        ld (net_ui),a
        ld (net_wait_visible),a
        jp net_return
net_wait_frame:
        call net_check_clock
        ld a,12
        jp nc,net_error
        ; A single late packet is normal. Keep the completed VGA frame intact.
        ld a,(net_wait_visible)
        or a
        jp nz,net_hold_frame
        ld hl,(net_clock)
        ld de,(net_stall_start)
        or a
        sbc hl,de
        ld de,40                 ; 800 ms before showing a persistent stall
        or a
        sbc hl,de
        jp c,net_hold_frame
        ld a,1
        ld (net_wait_visible),a
        ld a,4
        ld (net_ui),a
        jp net_return            ; show warning once, simulation stays frozen
net_hold_frame:
        ld a,(net_event)
        ld e,a
        scf
        ret
net_send_frame:
        ld a,0a5h
        out (050h),a
        call net_write_word
        ld hl,net_input
        ld bc,00451h
        otir
        jp net_wait
net_after:
        ld a,(net_mode)
        cp 2
        ret nz
        ld a,(net_ui)
        or a
        ret nz
        ; Read only the two-byte state fingerprint at ABI +18h decimal.
        ld a,0cah
        out (050h),a
        ld hl,18
        call net_write_word
        ld hl,02002h
        call net_write_word
        ld a,0cch
        out (050h),a
        in a,(051h)
        ld (net_hash),a
        ld a,0cch
        out (050h),a
        in a,(051h)
        ld (net_hash+1),a
        ld hl,(net_frame)
        ld a,l
        and 15
        jp nz,net_advance
        push hl
        ld a,0a7h
        out (050h),a
        call net_write_word
        ld hl,(net_hash)
        call net_write_word
        call net_wait
        pop hl
        jp nz,net_error
net_advance:
        inc hl
        ld (net_frame),hl
        ld de,60000
        or a
        sbc hl,de
        ld a,15
        jp nc,net_error
        xor a
        ld (net_sent),a
        jp net_reset_clock
net_copy:
        ld a,0cah
        out (050h),a
        ld hl,12
        call net_write_word
        ld hl,02002h
        call net_write_word
        ld hl,net_blob
        ld b,24
net_copy_byte:
        ld a,0cbh
        out (050h),a
        ld a,(hl)
        out (051h),a
        inc hl
        djnz net_copy_byte
        ret
net_detect:
        ld a,6
        out (050h),a
        call net_status4
        ld a,(net_status)
        cp 2
        ret nz
        ld a,(net_status+1)
        cp 6
        ret nz
        ld a,(net_status+2)
        cp 4
        ret nz
        ld hl,net_reply
        ld b,4
        call net_read
        ld a,095h
        out (050h),a
        call net_status4
        ld a,(net_status)
        and 082h
        cp 2
        ret nz
        ld a,(net_status+1)
        cp 095h
        ret nz
        ld a,(net_status+2)
        cp 16
        ret c
        ld hl,net_reply
        ld b,16
        call net_read
        ld a,(net_reply+3)
        and 8
        cp 8
        ret
net_get_status:
        ld a,0a0h
        out (050h),a
        call net_output
        ret nz
        ld hl,net_reply
        ld b,8
        call net_read
        xor a
        ret
net_output:
        call net_wait
        ret nz
        ld a,(net_status)
        and 2
        jp z,net_no_output
        xor a
        ret
net_no_output:
        ld a,255
        or a
        ret
; net_wait returns Z for success and NZ for a device error.
net_wait:
        call net_begin_wait
net_wait_loop:
        call net_status4
        ld a,(net_status)
        bit 7,a
        jp nz,net_device_error
        bit 6,a
        jp nz,net_in_progress
        and 1
        jp nz,net_incomplete
        xor a
        ret
net_in_progress:
        ld a,(held_key)
        cp 27
        jp z,net_incomplete
        call net_check_wait
        jp c,net_progress_alive
        ld a,12
        or a
        ret
net_progress_alive:
        halt
        jp net_wait_loop
net_device_error:
        ld a,(net_status+2)
        or a
        ret nz
net_incomplete:
        ld a,10
        or a
        ret
net_status4:
        ld a,3
        out (050h),a
        ld hl,net_status
        ld bc,00450h
        inir
        ret
net_read:
        ld c,051h
        inir
        ret
net_write_word:
        ld a,l
        out (051h),a
        ld a,h
        out (051h),a
        ret
net_begin_wait:
        ld hl,(net_clock)
        ld (net_wait_start),hl
        ret
net_reset_clock:
        ld hl,(net_clock)
        ld (net_stall_start),hl
        ret
net_check_clock:
        ld de,(net_stall_start)
        jp net_check_elapsed
net_check_wait:
        ld de,(net_wait_start)
net_check_elapsed:
        ld hl,(net_clock)
        or a
        sbc hl,de
        ld de,500
        or a
        sbc hl,de                ; carry means less than ten seconds
        ret
net_cancel:
        ld a,0a3h
        out (050h),a
        call net_wait
        call net_restore_drones
        xor a
        ld (net_mode),a
        ld (net_ui),a
        ld (net_queued),a
        ld (cheat_state),a
        ld (net_local_event),a
        jp net_no_event
net_missing:
        ld a,1
        ld (net_mode),a
        ld a,6
        ld (net_ui),a
        jp net_no_event
net_bad_param:
        ld a,10
        jp net_error
net_desync:
        ld a,13
        jp net_error
net_dropped:
        ld a,14
net_error:
        push af
        ld a,4
        out (050h),a             ; cancel pending repository command
        pop af
        ld (net_error_code),a
        ld a,5
        ld (net_ui),a
        ld a,1
        ld (net_mode),a
net_no_event:
        xor a
        ld (net_event),a
net_return:
        ld a,(net_event)
        ld e,a
        ld a,(net_mode)
        cp 2
        jr nz,net_return_ready
        ld a,(net_local_event)
        or a
        jr z,net_return_ready
        ld e,a
        xor a
        ld (net_local_event),a
net_return_ready:
        or a                    ; carry clear: render this host iteration
        ret
net_tap_table: db 'u',1,'W',1,'d',2,'S',2,'l',4,'A',4,'r',8,'D',8,'Q',16,'E',32,' ',64,'F',128,'f',128
net_create_params: dw 05544h,NET_BUILD
        db 2,2,2,2,0
        defs 14
net_blob:
net_mode: db 0
net_slot: db 0
net_mask: db 0
net_ui: db 0
net_frame: dw 0
net_hash: dw 0
net_code: defs 4
net_error_code: db 0
net_ready_mask: db 0
net_keys: defs 8
net_sector: db 0
net_slots: db 4
net_blob_end:
net_local_event: db 0
net_wait_visible: db 0
net_skins: db 0
net_event: db 0
net_code_pos: db 0
net_sent: db 0
net_queued: db 0
net_input: defs 4
net_status: defs 4
net_reply: defs 20
net_clock: dw 0
net_stall_start: dw 0
net_wait_start: dw 0

; Three 32x32 4bpp frames reuse the drone slots during deathmatch.
; Store both sets in Sharp RAM; ARM's 64 KB allocation does not grow.
net_load_players:
        ld a,1
        ld (net_skins),a
        ld hl,marine_frames
        jp net_skin_upload
net_restore_drones:
        ld a,(net_skins)
        or a
        ret z
        xor a
        ld (net_skins),a
        ld hl,drone_frames
net_skin_upload:
        push ix
        ld ix,skin_addresses
        ld a,3
net_skin_next:
        push af
        ld a,0cah
        out (050h),a
        ld b,4
net_skin_address:
        ld a,(ix+0)
        inc ix
        out (051h),a
        djnz net_skin_address
        ld de,512
net_skin_byte:
        ld a,0cbh
        out (050h),a
        ld a,(hl)
        out (051h),a
        inc hl
        dec de
        ld a,d
        or e
        jr nz,net_skin_byte
        pop af
        dec a
        jr nz,net_skin_next
        pop ix
        ret
        include "build/skins.inc"
marine_frames:
        incbin "build/marines.bin"
drone_frames:
        incbin "build/drones.bin"
