.syntax unified
.thumb
.section .header,"a",%progbits
.word doom_entry
.word 0x20028000
.global abi
abi:
.byte 0,0,0,0
