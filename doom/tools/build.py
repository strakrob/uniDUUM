#!/usr/bin/env python3
"""Build UniDoom using clang, lld, llvm-objcopy and pasmo; no original edits."""
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
from generate_assets import generate

ROOT=Path(__file__).resolve().parent.parent
os.chdir(ROOT)
(ROOT/'build').mkdir(exist_ok=True)
generate()
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
lld=os.environ.get('UNIDOOM_LLD') or find('ld.lld', '/usr/bin/ld.lld-14',
    '/usr/local/tmp/unigray-tools/root/usr/lib/llvm-14/bin/ld.lld')
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
original=(ROOT.parent/'unifractal_v0_2.mzf').read_bytes()
assert hashlib.sha256(original).hexdigest()=='2b1a31fcc5a37ed93ccf59aadb9ffd5c569f76df5a0267e90974edc097a9682c'
# Relocated Z80 key table 0933h..0982h, including arrow/key control codes.
(ROOT/'build/key_table.bin').write_bytes(original[0x933-0x80:0x983-0x80])
run(find('pasmo'),'--bin','src/host.asm','build/host.bin','build/host.sym')
host=(ROOT/'build/host.bin').read_bytes()
assert len(host)+0x3000<0x8000
header=bytearray(128)
header[0]=1
title=b'UNIDOOM V0.1'
header[1:18]=(title+b'\r').ljust(17,b'\r')
struct.pack_into('<HHH',header,18,len(host),0x3000,0x3000)
header[24:]=b'\xff'*104
output=ROOT.parent/'unidoom_v0_1.mzf'
output.write_bytes(header+host)
payload=(ROOT/'build/unicard.bin').read_bytes()
entry,fb=struct.unpack_from('<II',payload)
assert entry&1 and 0x2002000c<=entry<0x20028000
assert fb==0x20028000 and payload[8:12]==b'\0'*4
metadata={'file':output.name,'bytes':output.stat().st_size,
          'load':0x3000,'execute':0x3000,'arm_bytes':len(payload),
          'arm_entry':entry,'framebuffer':fb,
          'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}
(ROOT/'build/build.json').write_text(json.dumps(metadata,indent=2)+'\n')
print(json.dumps(metadata,indent=2))
