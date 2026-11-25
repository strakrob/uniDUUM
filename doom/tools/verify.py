#!/usr/bin/env python3
"""Execute the actual Z80 host + ARM payload with an emulated UniCard bus for UniDoom.

Dependencies: Unicorn 2.1+, numpy, Pillow, libz80ex.so.1; clang and llvm-nm.
This verifies CPU code/protocol/VRAM bytes, not electrical timing or firmware.
"""
import ctypes as ct
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

ROOT=Path(__file__).resolve().parent.parent
os.chdir(ROOT)
import numpy as np
from PIL import Image
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS
from unicorn.arm_const import (UC_CPU_ARM_CORTEX_M4,UC_ARM_REG_SP,UC_ARM_REG_LR,
    UC_ARM_REG_PC,UC_ARM_REG_C1_C0_2,UC_ARM_REG_FPEXC)

subprocess.run(['clang','-shared','-fPIC','-O2','-ffp-contract=off',
                '-fno-math-errno','-DUNIDOOM_NATIVE','-Wall','-Wextra','-Werror',
                'src/raycaster.c','-o','build/native.so','-lm'],check=True)
native=ct.CDLL(str(ROOT/'build/native.so'))
native.native_key.argtypes=[ct.c_uint,ct.c_uint]
native.native_frame.restype=ct.POINTER(ct.c_uint8)
native.native_state.argtypes=[ct.c_int]
native.native_x.restype=native.native_y.restype=ct.c_float
native.native_pose.argtypes=native.native_set_pose.argtypes=[ct.c_float,ct.c_float,ct.c_int]
native.native_can_stand.argtypes=[ct.c_float,ct.c_float]
native.native_depth.restype=ct.POINTER(ct.c_float)
nm=shutil.which('llvm-nm') or shutil.which('llvm-nm-14')
symbol_rows=[line.split() for line in subprocess.check_output([nm,'-n','-S','build/unicard.elf'],text=True).splitlines()]
arm_symbols={row[3]:int(row[0],16) for row in symbol_rows if len(row)==4}
arm_sizes={row[3]:int(row[1],16) for row in symbol_rows if len(row)==4}
symbols={line.split()[0]:int(line.split()[2][:-1],16) for line in
         (ROOT/'build/host.sym').read_text().splitlines()}
payload=(ROOT/'build/unicard.bin').read_bytes()
level=json.loads((ROOT/'build/level.json').read_text())
entry,fb=struct.unpack_from('<II',payload)
mzf=(ROOT.parent/'unidoom_v0_1.mzf').read_bytes()
length,load,execute=struct.unpack_from('<HHH',mzf,18)
assert len(mzf)==length+128 and load==execute==0x3000
assert mzf[128:]==(ROOT/'build/host.bin').read_bytes()
assert arm_symbols['__state_end'] <= fb == 0x20028000
assert fb+32768==0x20030000
key_table=(ROOT/'build/key_table.bin').read_bytes()
assert len(key_table)==80

class ARM:
    def __init__(self):
        self.u=Uc(UC_ARCH_ARM,UC_MODE_THUMB|UC_MODE_MCLASS)
        self.u.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_M4)
        self.u.mem_map(0x20000000,0x40000)
        # Deliberately dirty SRAM: entry must initialize every live field.
        self.u.mem_write(0x20020000,b'\xa5'*0x10010)
        self.u.reg_write(UC_ARM_REG_C1_C0_2,0xf<<20)
        self.u.reg_write(UC_ARM_REG_FPEXC,0x40000000)
        self.calls=[]
        native.native_cold()
    def call(self,pointer):
        assert pointer==entry
        key=self.u.mem_read(0x20020008,1)[0]
        buttons=self.u.mem_read(0x2002000a,1)[0]
        self.u.reg_write(UC_ARM_REG_SP,0x20010000)
        self.u.reg_write(UC_ARM_REG_LR,0x20000001)
        self.u.emu_start(pointer,0x20000000,count=1_000_000_000)
        assert self.u.reg_read(UC_ARM_REG_PC)==0x20000000,'ARM instruction limit'
        native.native_key(key,buttons)
        frame=bytes(self.u.mem_read(fb,32768))
        assert frame==ct.string_at(native.native_frame(),32768),f'ARM/native image mismatch, key {key}'
        state=[]
        names=['angle','health','ammo','kills','core','medkit','won','frame','fire_timer',
               'cooldown','hurt_timer','map_on','flashlight','running','auto_mode',
               'tour_index','use_down','walk_phase','message']
        for i,name in enumerate(names):
            value=int.from_bytes(self.u.mem_read(arm_symbols[name],arm_sizes[name]),'little')
            assert value==native.native_state(i),(name,value,native.native_state(i))
            state.append(value)
        for j,name in enumerate(['door_open','door_goal']):
            for i in range(2):
                value=struct.unpack('<I',self.u.mem_read(arm_symbols[name]+4*i,4))[0]
                assert value==native.native_state(19+j*2+i)
                state.append(value)
        for name,getter in [('player_x',native.native_x),('player_y',native.native_y)]:
            actual=bytes(self.u.mem_read(arm_symbols[name],4))
            assert actual==struct.pack('<f',getter()),f'{name} differs'
        for i in range(4):
            hp=struct.unpack('<I',self.u.mem_read(arm_symbols['drones']+16*i+8,4))[0]
            assert hp==native.native_drone(i)
        for address in [arm_symbols['__state_end'],fb-16,fb+32768]:
            assert bytes(self.u.mem_read(address,16))==b'\xa5'*16,f'SRAM guard overwritten at {address:x}'
        for p in range(4): assert not any(frame[p*8192+8000:(p+1)*8192])
        self.calls.append({'key':key,'buttons':buttons,'state':state,'x':native.native_x(),'y':native.native_y(),'sha256':hashlib.sha256(frame).hexdigest()})
        return frame

libname=os.environ.get('UNIDOOM_Z80EX','libz80ex.so.1')
try: z=ct.CDLL(libname)
except OSError as exc:
    raise SystemExit('Install libz80ex1 or set UNIDOOM_Z80EX to its shared library') from exc
MR=ct.CFUNCTYPE(ct.c_uint8,ct.c_void_p,ct.c_uint16,ct.c_int,ct.c_void_p)
MW=ct.CFUNCTYPE(None,ct.c_void_p,ct.c_uint16,ct.c_uint8,ct.c_void_p)
PR=ct.CFUNCTYPE(ct.c_uint8,ct.c_void_p,ct.c_uint16,ct.c_void_p)
PW=ct.CFUNCTYPE(None,ct.c_void_p,ct.c_uint16,ct.c_uint8,ct.c_void_p)
IR=ct.CFUNCTYPE(ct.c_uint8,ct.c_void_p,ct.c_void_p)
z.z80ex_create.argtypes=[MR,ct.c_void_p,MW,ct.c_void_p,PR,ct.c_void_p,PW,ct.c_void_p,IR,ct.c_void_p]
z.z80ex_create.restype=ct.c_void_p
z.z80ex_step.argtypes=[ct.c_void_p]
z.z80ex_get_reg.argtypes=[ct.c_void_p,ct.c_int]; z.z80ex_get_reg.restype=ct.c_uint16
z.z80ex_set_reg.argtypes=[ct.c_void_p,ct.c_int,ct.c_uint16]
z.z80ex_destroy.argtypes=[ct.c_void_p]
z.z80ex_int.argtypes=[ct.c_void_p]
z.z80ex_int.restype=ct.c_int

class Machine:
    def __init__(self,corrupt=False):
        self.arm=ARM(); self.memory=bytearray(65536)
        self.memory[load:load+length]=mzf[128:]
        self.vram=[bytearray(8192) for _ in range(4)]
        self.wf=0; self.border=0; self.column=0; self.keys=[]
        self.command=0; self.args=[]; self.remaining=0; self.cursor=0
        self.busy=0; self.corrupt=corrupt; self.error=None
        self.blocks=[]; self.uploads=0; self.selected=[]
        self.cycles=0; self.next_interrupt=70000
        self.callbacks=(MR(self.read_memory),MW(self.write_memory),
                        PR(self.read_port),PW(self.write_port),IR(lambda *_:0))
        mr,mw,pr,pw,ir=self.callbacks
        self.cpu=z.z80ex_create(mr,None,mw,None,pr,None,pw,None,ir,None)
        z.z80ex_set_reg(self.cpu,10,execute)
    def read_memory(self,ctx,address,m1,data):
        if 0x8000<=address<0xa000: return self.vram[0][address-0x8000]
        return self.memory[address]
    def write_memory(self,ctx,address,value,data):
        if 0x8000<=address<0xa000:
            for p in range(4):
                if self.wf&(1<<p): self.vram[p][address-0x8000]=value
        else: self.memory[address]=value
    def read_port(self,ctx,port,data):
        p=port&255
        if p==0xd1:
            value=255
            for key in self.keys:
                i=key_table.index(key)
                if self.column==i//8:value &= ~(0x80>>(i%8))
            return value
        if p==0x51:
            if self.command==0xcd:
                if self.busy: self.busy-=1; return 0xcd
                return 0
            value=self.arm.u.mem_read(self.cursor,1)[0]
            self.cursor+=1
            if self.corrupt and self.command==0xcc: value^=1
            if self.command==0xce: self.remaining-=1
            return value
        return 255
    def write_port(self,ctx,port,value,data):
        try: self._write_port(port,value)
        except BaseException as exc: self.error=exc
    def _write_port(self,port,value):
        p=port&255
        if p==0xd0: self.column=value&15
        elif p==0xcc:
            assert value<16,'Unexpected GDG write mode'
            self.wf=value
            if value in [1,2,4,8]: self.selected.append(value)
        elif p==0xcf and port>>8==6: self.border=value
        elif p==0x50:
            assert self.remaining==0,'Previous UniCard block was not consumed'
            self.command=value; self.args=[]
        elif p==0x51:
            if self.command in [0xca,0xcd]:
                self.args.append(value)
                if len(self.args)==4:
                    address=int.from_bytes(bytes(self.args),'little')
                    if self.command==0xca: self.cursor=address
                    else: self.arm.call(address); self.busy=1
            elif self.command==0xcb:
                self.arm.u.mem_write(self.cursor,bytes([value])); self.cursor+=1
                self.uploads+=1
            elif self.command==0xce:
                assert value==16
                self.remaining=value; self.blocks.append(value)
            else: raise AssertionError(f'Unexpected data write command {self.command:x}')
    def run_until(self,target,limit=500000):
        for _ in range(limit):
            self.cycles+=z.z80ex_step(self.cpu)
            if self.error: raise self.error
            pc=z.z80ex_get_reg(self.cpu,10)
            if pc==target: return
            assert pc!=symbols['failure_loop'],'Z80 host reported interface failure'
            if self.cycles>=self.next_interrupt:
                accepted=z.z80ex_int(self.cpu)
                if accepted:
                    self.cycles+=accepted
                    self.next_interrupt=self.cycles+70000
        raise AssertionError('Z80 instruction limit')
    def frame(self,key=0):
        self.keys=[] if key==0 else [key] if isinstance(key,int) else list(key)
        # Sample a key at a VBLANK immediately before consuming the event.
        if z.z80ex_get_reg(self.cpu,10)==symbols['frame_done']:
            assert z.z80ex_int(self.cpu)
            self.run_until(symbols['frame_done'])
        self.run_until(symbols['frame_done'])
        actual=b''.join(self.vram)
        assert actual==bytes(self.arm.u.mem_read(fb,32768)),'Z80/GDG framebuffer mismatch'
        assert self.selected[-4:]==[1,2,4,8]
        assert len(self.blocks)%2048==0
        return actual
    def close(self): z.z80ex_destroy(self.cpu)

def verify_short_taps():
    tap=Machine()
    tap.run_until(symbols['upload']) # IRQ configured, before any native call
    registers=[0,1,2,3,8,9,11]       # AF BC DE HL IX IY SP
    before=[z.z80ex_get_reg(tap.cpu,r) for r in registers]
    tap.keys=[ord(' ')]
    assert z.z80ex_int(tap.cpu)
    tap.run_until(symbols['upload'])
    assert tap.memory[symbols['pending_key']]==ord(' ')
    tap.keys=[]
    assert z.z80ex_int(tap.cpu)
    tap.run_until(symbols['upload'])
    assert tap.memory[symbols['pending_key']]==ord(' '),'Release lost a short tap'
    assert before==[z.z80ex_get_reg(tap.cpu,r) for r in registers],'IRQ clobbered a register'
    tap.close()

def image(data):
    p=np.frombuffer(data,dtype=np.uint8).reshape(4,8192)[:,:8000]
    bits=np.unpackbits(p,axis=1,bitorder='little').reshape(4,200,320)
    indices=np.sum(bits*np.array([1,2,4,8])[:,None,None],axis=0).astype(np.uint8)
    pal=[]
    for c in range(16):
        low,high=(85,255) if c&8 else (0,170)
        pal.extend([high if c&2 else low,high if c&4 else low,high if c&1 else low])
    im=Image.fromarray(indices,'P'); im.putpalette(pal+[0]*(768-len(pal)))
    return im

def indices(data):
    p=np.frombuffer(data,dtype=np.uint8).reshape(4,8192)[:,:8000]
    bits=np.unpackbits(p,axis=1,bitorder='little').reshape(4,200,320)
    return np.sum(bits*np.array([1,2,4,8])[:,None,None],axis=0).astype(np.uint8)

verify_short_taps()
machine=Machine()
cases=[('boot',0),('walk1',ord('W')),('walk2',ord('W')),
       ('turn_walk',[ord('W'),ord('D')]),('turn',ord('D')),('release',0),
       ('fire1',32),('fire2',32),('fire3',32),('fire4',32),('fire5',32),('fire_release',0),
       ('map',ord('M')),('map_hold',ord('M')),('map_release',0),('light',ord('L')),
       ('run',ord('Z')),('reset',ord('R')),('strafe_l',ord('Q')),('strafe_r',ord('E')),
       ('use_far',ord('F')),('release2',0),('tour',ord('P')),('tour2',0),('tour3',0),
       ('manual',ord('W')),('reset2',ord('R')),('combo',[ord('W'),32,ord('F')]),
       ('release3',0),('escape',27)]
observed={}
for i,(name,keys) in enumerate(cases):
    data=machine.frame(keys);observed[name]=machine.arm.calls[-1]
    if name=='boot':image(data).resize((960,600),Image.Resampling.NEAREST).save('previews/boot.png')
    if i%8==0:print(f'Z80/ARM control frame {i+1}/{len(cases)} verified',flush=True)
assert observed['walk1']['buttons']==observed['walk2']['buttons']==1
assert observed['walk1']['x']>observed['boot']['x'] and observed['walk2']['x']>observed['walk1']['x']
assert observed['turn_walk']['buttons']==9 and observed['turn_walk']['state'][0]>0
assert observed['turn_walk']['x']>observed['walk2']['x']
assert observed['release']['buttons']==0
assert observed['fire1']['state'][2]==35 and observed['fire5']['state'][2]==34
assert observed['map']['state'][11]==observed['map_hold']['state'][11]==1
assert observed['light']['state'][12]==0 and observed['run']['state'][13]==1
assert observed['reset']['sha256']==observed['boot']['sha256']
assert abs(observed['strafe_r']['y']-8.5)<1e-5
assert observed['tour']['state'][14]==1 and observed['tour3']['x']>observed['tour']['x']
assert observed['manual']['state'][14]==0
assert observed['combo']['buttons']==(1|64|128)
assert observed['escape']['sha256']==observed['boot']['sha256']

# Inspect an actual lifting door through the Z80/ARM path at every stage.
for name,value in [('player_x',7.8),('player_y',3.5)]:
    machine.arm.u.mem_write(arm_symbols[name],struct.pack('<f',value))
machine.arm.u.mem_write(arm_symbols['angle'],struct.pack('<I',512))
machine.arm.u.mem_write(arm_symbols['auto_mode'],struct.pack('<I',0))
native.native_set_pose(7.8,3.5,512)
machine.frame(0)
assert machine.arm.calls[-1]['state'][19]==0
machine.frame(ord('F'))
assert machine.arm.calls[-1]['state'][21]==1
for i in range(18):
    data=machine.frame(0)
    if i==7:image(data).resize((960,600),Image.Resampling.NEAREST).save('previews/door.png')
assert machine.arm.calls[-1]['state'][19]==16
for _ in range(8):machine.frame(ord('W'))
assert machine.arm.calls[-1]['x']<6.5,'Could not walk through open doorway'
machine.frame(ord('F'));machine.frame(0)
assert machine.arm.calls[-1]['state'][19]==16 and machine.arm.calls[-1]['state'][21]==1,'Door crushed player'
calls=machine.arm.calls
assert machine.uploads==len(payload)+2*len(calls)
machine.close()

bad=Machine(corrupt=True)
bad.run_until(symbols['failed']);bad.run_until(symbols['failure_loop'])
assert bad.border==10 and not bad.arm.calls
bad.close()
timeout=Machine()
timeout.run_until(symbols['wait_native']);timeout.busy=2
z.z80ex_set_reg(timeout.cpu,2,1)
timeout.run_until(symbols['failed']);timeout.close()

from verify_scene import check_scene
report={'host_arm_frames':len(calls),'exact_native_comparison':True,
        'simultaneous_keys_checked':True,'held_movement_and_autofire_checked':True,
        'door_opening_and_safe_closing_checked':True,'short_taps_and_irq_registers_checked':True,
        'upload_failure_checked':True,'busy_timeout_checked':True,
        'framebuffer_bytes_per_frame':32768,'blocks_per_frame':2048,
        'mzf_sha256':hashlib.sha256(mzf).hexdigest(),'calls':calls}
report.update(check_scene(native,image,indices))
(ROOT/'build/verification.json').write_text(json.dumps(report,indent=2)+'\n')
print('PASS: Z80+ARM, held/multiple keys, ray depth, sprites, doors, collision, shooting, objective and guided tour.')

