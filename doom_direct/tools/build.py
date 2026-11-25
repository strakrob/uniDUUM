#!/usr/bin/env python3
"""Build UniDoom Direct with the firmware-published VGA pointer."""
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
from generate_assets import generate
from generate_sounds import generate as generate_sounds
from generate_music import generate as generate_music

ROOT=Path(__file__).resolve().parent.parent
os.chdir(ROOT)
(ROOT/'build').mkdir(exist_ok=True)
level=generate()
generate_sounds()
generate_music()
music=json.loads((ROOT/'build/music.json').read_text())
sine=[int(math.sin(i*math.pi/512)*32767+.5) for i in range(257)]
(ROOT/'src/sine.h').write_text('/* Generated quarter-wave Q15 sine lookup. */\nstatic const uint16_t sine_quarter[257]={'+','.join(map(str,sine))+'};\n')
def find(name, *fallbacks):
    value=shutil.which(name)
    if value: return value
    for f in fallbacks:
        if Path(f).exists(): return f
    raise SystemExit(f'Missing build tool: {name}')
def run(*args): subprocess.run(args,check=True)
clang=find('clang')
lld=os.environ.get('UNIDOOM_DIRECT_LLD') or os.environ.get('UNIDOOM_LLD') or find('ld.lld', '/usr/bin/ld.lld-14')
objcopy=find('llvm-objcopy', '/usr/bin/llvm-objcopy-14')
flags=['--target=arm-none-eabi','-mcpu=cortex-m4','-mthumb',
       '-mfpu=fpv4-sp-d16','-mfloat-abi=hard','-Oz','-ffreestanding',
       '-fno-builtin','-fno-math-errno','-ffp-contract=off','-fno-unwind-tables',
       '-fno-asynchronous-unwind-tables','-Wall','-Wextra','-Werror']
run(clang,*flags,'-c','src/raycaster.c','-o','build/raycaster.o')
run(clang,*flags,'-c','src/unicard_header.S','-o','build/unicard_header.o')
run(lld,'-T','src/unicard.ld','-Map=build/unicard.map','-o','build/unicard.elf',
    'build/unicard_header.o','build/raycaster.o')
run(objcopy,'-O','binary','build/unicard.elf','build/unicard.bin')
# Shared Sharp keyboard mapping; no original demo image is needed.
key_table=(ROOT.parent/'common/key_table.bin').read_bytes()
assert len(key_table)==80
assert hashlib.sha256(key_table).hexdigest()=='9f49c16609b647548d0b89a093331e86eda7d9a9a2cbe13202f27fd93fbd1e51'
(ROOT/'build/key_table.bin').write_bytes(key_table)
run(find('pasmo'),'--bin','src/host.asm','build/host.bin','build/host.sym')
host=(ROOT/'build/host.bin').read_bytes()
assert len(host)+0x3000<0x8000
header=bytearray(128)
header[0]=1
title=b'UNIDOOM DIRECT06'
assert len(title)<=16
header[1:18]=(title+b'\r').ljust(17,b'\r')
struct.pack_into('<HHH',header,18,len(host),0x3000,0x3000)
header[24:]=b'\xff'*104
output=ROOT.parent/'unidoom_direct_v0_6.mzf'
output.write_bytes(header+host)
payload=(ROOT/'build/unicard.bin').read_bytes()
entry,fb=struct.unpack_from('<II',payload)
assert entry&1 and 0x2002000c<=entry<0x20028000
assert fb==0 and payload[8:12]==b'\0'*4
metadata={'file':output.name,'bytes':output.stat().st_size,
          'load':0x3000,'execute':0x3000,'arm_bytes':len(payload),
          'arm_entry':entry,'framebuffer':'runtime firmware pointer',
          'framebuffer_pointer_slot':0x08008228,'framebuffer_base_range_inclusive':[0x10000000,0x10008000],
          'initial_header_framebuffer':fb,'plane_stride':8192,'direct_vga':True,
          'invalid_framebuffer_behavior':'no render/CCM writes; zero pointer; host mutes and stops with red border',
          'visible_bytes_per_plane':8000,'textures':'32x32, packed 4bpp, all 16 colours',
          'map_size':[32,24],'drones':8,'sound_port':'0xF2 SN76489','cheat':'DDQD',
          'music':music['title'],'music_seconds':music['loop_seconds'],
          'music_source_sha256':music['source_sha256'],
          'sector_geometry_different_cells':level['geometry_different_cells'],
          'renderer':'packed scanlines, no opaque-wall overdraw, shaded column cache',
          'asset_codec':level['asset_codec'],
          'sectors':2,'keys_locked_doors_secrets':True,'drone_animation_frames':3,
          'grid_pathfinding':True,'particles':16,'animated_reactors':True,
          'weapons':['pistol','shotgun'],
          'arm_backbuffer':0x20028000,'arm_backbuffer_bytes':32768,
          'sharp_vram_writes':0,'framebuffer_readback_bytes_per_frame':0,
          'frame_divisor':3,'target_fps_at_50hz':50/3,
          'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}
host_symbols={line.split()[0]:int(line.split()[2][:-1],16) for line in
              (ROOT/'build/host.sym').read_text().splitlines()}
nm=find('llvm-nm','/usr/bin/llvm-nm-14')
rows=[line.split() for line in subprocess.check_output([nm,'-n','build/unicard.elf'],text=True).splitlines()]
arm_symbols={row[2]:int(row[0],16) for row in rows if len(row)==3}
budget={'z80_load':0x3000,'z80_image_end':0x3000+len(host),'z80_image_limit':0x8000,
        'z80_image_bytes':len(host),'z80_image_free_bytes':0x5000-len(host),
        'z80_host_and_audio_bytes':host_symbols['arm_payload']-0x3000,
        'arm_payload_bytes':len(payload),'arm_state_bytes':arm_symbols['__state_end']-arm_symbols['__payload_end'],
        'arm_code_state_bytes':arm_symbols['__state_end']-0x20020000,
        'arm_code_state_end':arm_symbols['__state_end'],'arm_project_limit':0x20028000,
        'arm_project_free_bytes':0x20028000-arm_symbols['__state_end'],
        'arm_backbuffer_address':0x20028000,'arm_backbuffer_bytes':32768,
        'arm_total_allocated_bytes':arm_symbols['__state_end']-0x20020000+32768,
        'asset_decoded_bytes':level['asset_raw_bytes'],'asset_compressed_bytes':level['asset_compressed_bytes'],
        'maps_compressed_bytes':level['map_compressed_bytes'],'navigation_scratch_bytes':2304,
        'music_data_bytes':host_symbols['music_data_end']-host_symbols['music_data_start'],
        'music_player_code_bytes':host_symbols['music_player_end']-host_symbols['music_player'],
        'music_state_bytes':host_symbols['music_state_end']-host_symbols['music_state'],
        'z80_music_history_address':0xa000,'z80_music_history_bytes':2048,
        'column_cache_bytes':3072,'column_index_bytes':160,'partial_door_uv_bytes':320,
        'framebuffer_allocation_bytes':32768,'framebuffer_visible_bytes':32000,
        'ccm_outside_framebuffer_reserved_for_firmware':True,
        'asset_bytes':{'texture_32x32_4bpp':512,'sprite_32x32_4bpp':512,'map_32x24_u8':768},
        'limits_note':'Current linker/loader limits; free firmware-owned CCM/main SRAM is not assumed.'}
metadata['memory_budget']=budget
(ROOT/'build/memory.json').write_text(json.dumps(budget,indent=2)+'\n')
(ROOT/'build/build.json').write_text(json.dumps(metadata,indent=2)+'\n')
print(json.dumps(metadata,indent=2))
