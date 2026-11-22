ENTRY(doom_direct_entry)
firmware_video_pointer = 0x08008228;
__video_size = 0x8000;
__back_buffer = 0x20028000;
__back_end = 0x20030000;
SECTIONS {
  . = 0x20020000;
  .header : { KEEP(*(.header)) }
  .text : { *(.text*) *(.rodata*) }
  . = ALIGN(16);
  __payload_end = .;
  .bss (NOLOAD) : { *(.bss*) *(COMMON) }
  __state_end = .;
  ASSERT(__state_end <= 0x20028000, "UniCard code/state exceeds project SRAM limit")
  ASSERT(__back_end - __back_buffer == 32768 && __back_end == 0x20030000,
         "ARM backbuffer must fit the original 64 KB OpenCPU allocation")
  /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) *(.note*) }
}
