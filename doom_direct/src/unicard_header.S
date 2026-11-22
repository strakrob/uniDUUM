.syntax unified
.thumb
.section .header,"a",%progbits
.word doom_direct_entry
.global video_address
video_address:
.word 0
.global abi
abi:
.byte 0,0,0,0
