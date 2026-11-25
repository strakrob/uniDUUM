#!/usr/bin/env python3
"""Count actual Cortex-M4 instructions for fixed views; no hardware FPS claim."""
import argparse,json,struct,subprocess,shutil
from pathlib import Path
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_MODE_MCLASS,UC_HOOK_BLOCK
from unicorn.arm_const import UC_CPU_ARM_CORTEX_M4,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_C1_C0_2,UC_ARM_REG_FPEXC
p=argparse.ArgumentParser();p.add_argument('--build',type=Path,default=Path(__file__).resolve().parent.parent/'build');p.add_argument('--output',type=Path);p.add_argument('--video-address',type=lambda s:int(s,0),default=0x10001f80);a=p.parse_args()
nm=shutil.which('llvm-nm') or shutil.which('llvm-nm-14')
if not nm:raise SystemExit('Profiling requires llvm-nm')
rows=[line.split() for line in subprocess.check_output([nm,'-n','-S',str(a.build/'unicard.elf')],text=True).splitlines()]
symbols={r[3]:int(r[0],16) for r in rows if len(r)==4}
sizes={r[3]:int(r[1],16) for r in rows if len(r)==4}
functions=[(int(r[0],16)&~1,int(r[1],16),r[3]) for r in rows if len(r)==4 and r[2] in ('t','T') and int(r[1],16)]
u=Uc(UC_ARCH_ARM,UC_MODE_THUMB|UC_MODE_MCLASS);u.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_M4)
u.mem_map(0x20000000,0x40000);u.mem_map(0x10000000,0x10000)
u.mem_map(0x08008000,0x1000);u.mem_write(0x08008228,struct.pack('<I',a.video_address))
payload=(a.build/'unicard.bin').read_bytes();entry=struct.unpack_from('<I',payload)[0]
u.mem_write(0x20020000,payload);u.reg_write(UC_ARM_REG_C1_C0_2,0xf<<20);u.reg_write(UC_ARM_REG_FPEXC,0x40000000)
def call():
 u.reg_write(UC_ARM_REG_SP,0x20010000);u.reg_write(UC_ARM_REG_LR,0x20000001);u.emu_start(entry,0x20000000,count=100000000)
cache={};counts={}
def block(uc,pc,size,data):
 if pc not in cache:
  code=uc.mem_read(pc,size);i=0;n=0
  while i<len(code):
   word=code[i]|code[i+1]<<8;i+=4 if word>>11 in (29,30,31) else 2;n+=1
  name=next((name for start,length,name in functions if start<=pc<start+length),'other')
  cache[pc]=(n,name)
 n,name=cache[pc];counts[name]=counts.get(name,0)+n
u.hook_add(UC_HOOK_BLOCK,block)
call();u.mem_write(symbols['ai_on'],bytes(sizes['ai_on']))
views=[('start',3.5,8.5,0),('close_door',7.24,3.5,512),('corner',1.24,1.24,640),('long_hall',3.5,21.5,0)]
report=[]
for name,x,y,angle in views:
 for key,value in [('player_x',x),('player_y',y)]:u.mem_write(symbols[key],struct.pack('<f',value))
 u.mem_write(symbols['angle'],struct.pack('<I',angle));u.mem_write(symbols['frame'],struct.pack('<I',1))
 counts.clear();call()
 destination=struct.unpack('<I',u.mem_read(0x20020004,4))[0]
 if not destination:raise SystemExit('Invalid firmware-published video pointer')
 frame=bytes(u.mem_read(destination,32768));(a.build/(name+'.frame')).write_bytes(frame)
 report.append({'view':name,'instructions':sum(counts.values()),'functions':dict(sorted(counts.items(),key=lambda x:-x[1]))})
print(json.dumps(report,indent=2))
if a.output:a.output.write_text(json.dumps(report,indent=2)+'\n')
