ENTRY(doom_entry)
SECTIONS {
  . = 0x20020000;
  .header : { KEEP(*(.header)) }
  .text : { *(.text*) *(.rodata*) }
  . = ALIGN(16);
  __payload_end = .;
  .bss (NOLOAD) : { *(.bss*) *(COMMON) }
  __state_end = .;
  ASSERT(__state_end <= 0x20028000, "UniCard code/state overlaps framebuffer")
  /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) *(.note*) }
}
