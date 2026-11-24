#!/usr/bin/env python3
"""Execute UniDoom Direct's Z80 host and ARM payload, including live CCM writes.

Dependencies: Unicorn 2.1+, numpy, Pillow, libz80ex.so.1; clang and llvm-nm.
This verifies CPU code/protocol/CCM bytes, not electrical timing or firmware.
"""
import ctypes as ct
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

ROOT=Path(__file__).resolve().parent.parent
os.chdir(ROOT)
if Path('/usr/local/tmp/unifractal-python').exists():
    sys.path.insert(0,'/usr/local/tmp/unifractal-python')
import numpy as np
from PIL import Image
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_READ
from unicorn.arm_const import (UC_CPU_ARM_CORTEX_M4,UC_ARM_REG_SP,UC_ARM_REG_LR,
    UC_ARM_REG_PC,UC_ARM_REG_C1_C0_2,UC_ARM_REG_FPEXC)

subprocess.run(['clang','-shared','-fPIC','-O2','-ffp-contract=off',
                '-fno-math-errno','-DUNIDOOM_NATIVE','-Wall','-Wextra','-Werror',
                'src/raycaster.c','-o','build/native.so','-lm'],check=True)
native=ct.CDLL(str(ROOT/'build/native.so'))
native.native_key.argtypes=[ct.c_uint,ct.c_uint]
native.native_frame.restype=ct.POINTER(ct.c_uint8)
native.native_back_frame.restype=ct.POINTER(ct.c_uint8)
native.native_art.restype=ct.POINTER(ct.c_uint8)
native.native_set_video_pointer.argtypes=[ct.c_uint32]
native.native_video_address.restype=ct.c_uint32
native.native_state.argtypes=[ct.c_int]
native.native_x.restype=native.native_y.restype=ct.c_float
native.native_pose.argtypes=native.native_set_pose.argtypes=[ct.c_float,ct.c_float,ct.c_int]
native.native_can_stand.argtypes=[ct.c_float,ct.c_float]
native.native_ai.argtypes=[ct.c_int]
native.native_drone_x.restype=native.native_drone_y.restype=ct.c_float
native.native_depth.restype=ct.POINTER(ct.c_float)
nm=shutil.which('llvm-nm') or shutil.which('llvm-nm-14')
symbol_rows=[line.split() for line in subprocess.check_output([nm,'-n','-S','build/unicard.elf'],text=True).splitlines()]
arm_symbols={row[3]:int(row[0],16) for row in symbol_rows if len(row)==4}
arm_sizes={row[3]:int(row[1],16) for row in symbol_rows if len(row)==4}
symbols={line.split()[0]:int(line.split()[2][:-1],16) for line in
         (ROOT/'build/host.sym').read_text().splitlines()}
payload=(ROOT/'build/unicard.bin').read_bytes()
level=json.loads((ROOT/'build/level.json').read_text())
entry,initial_fb=struct.unpack_from('<II',payload)
fb=0x10001f80 # Test fixture only; production reads the firmware publication.
FLASH_SLOT=0x08008228
mzf=(ROOT.parent/'unidoom_net_v0_3.mzf').read_bytes()
length,load,execute=struct.unpack_from('<HHH',mzf,18)
assert len(mzf)==length+128 and load==execute==0x3000
assert mzf[128:]==(ROOT/'build/host.bin').read_bytes()
assert arm_symbols['__state_end'] <= 0x20028000
assert initial_fb==0 and arm_symbols['video_address']==0x20020004
key_table=(ROOT/'build/key_table.bin').read_bytes()
assert len(key_table)==80

class ARM:
    def __init__(self,published=fb):
        self.u=Uc(UC_ARCH_ARM,UC_MODE_THUMB|UC_MODE_MCLASS)
        self.u.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_M4)
        self.u.mem_map(0x20000000,0x40000)
        self.u.mem_map(0x10000000,0x10000)
        self.u.mem_map(0x08008000,0x1000)
        self.u.mem_write(0x08008000,b'\xa5'*0x1000)
        self.u.mem_write(FLASH_SLOT,struct.pack('<I',published))
        # Deliberately dirty SRAM: entry must initialize every live field.
        self.u.mem_write(0x20020000,b'\xa5'*0x10010)
        self.u.mem_write(0x10000000,b'\xa5'*0x10000)
        self.u.reg_write(UC_ARM_REG_C1_C0_2,0xf<<20)
        self.u.reg_write(UC_ARM_REG_FPEXC,0x40000000)
        self.calls=[]
        self.fb=None;self.flash_reads=[];self.flash_writes=0
        self.live_writes=0;self.back_snapshot=None;self.bad_video_write=False
        def video_write(uc,access,address,size,value,data):
            offset=address-self.fb if self.fb is not None else -1
            if not 0<=offset<32768 or offset%8192+size>8000:self.bad_video_write=True
            if self.back_snapshot is None:self.back_snapshot=bytes(uc.mem_read(0x20028000,32768))
            self.live_writes+=size
        self.u.hook_add(UC_HOOK_MEM_WRITE,video_write,begin=0x10000000,end=0x1000ffff)
        def flash_read(uc,access,address,size,value,data):self.flash_reads.append((address,size))
        def flash_write(uc,access,address,size,value,data):self.flash_writes+=size
        self.u.hook_add(UC_HOOK_MEM_READ,flash_read,begin=FLASH_SLOT,end=FLASH_SLOT+3)
        self.u.hook_add(UC_HOOK_MEM_WRITE,flash_write,begin=0x08008000,end=0x08008fff)
        native.native_cold()
    def call(self,pointer):
        assert pointer==entry
        key=self.u.mem_read(0x20020008,1)[0]
        buttons=self.u.mem_read(0x2002000a,1)[0]
        published=struct.unpack('<I',self.u.mem_read(FLASH_SLOT,4))[0]
        self.fb=published if 0x10000000<=published<=0x10008000 else None
        before_ccm=bytes(self.u.mem_read(0x10000000,65536))
        before_user=bytearray(self.u.mem_read(0x20020000,65536))
        before_flash=bytes(self.u.mem_read(0x08008000,0x1000))
        self.u.reg_write(UC_ARM_REG_SP,0x20010000)
        self.u.reg_write(UC_ARM_REG_LR,0x20000001)
        self.live_writes=0;self.back_snapshot=None;self.bad_video_write=False
        self.flash_reads=[];self.flash_writes=0
        self.u.emu_start(pointer,0x20000000,count=1_000_000_000)
        assert self.u.reg_read(UC_ARM_REG_PC)==0x20000000,'ARM instruction limit'
        native.native_set_video_pointer(published);native.native_key(key,buttons)
        assert self.flash_reads==[(FLASH_SLOT,4)],'Firmware pointer was not read once as a uint32'
        assert self.flash_writes==0 and bytes(self.u.mem_read(0x08008000,0x1000))==before_flash
        assert self.u.mem_read(0x2002000b,1)[0]==native.native_sound(),'Sound event differs'
        resolved=struct.unpack('<I',self.u.mem_read(0x20020004,4))[0]
        assert resolved==native.native_video_address()==(published if self.fb is not None else 0)
        if self.fb is None:
            assert self.live_writes==0 and self.back_snapshot is None and not self.bad_video_write
            assert bytes(self.u.mem_read(0x10000000,65536))==before_ccm
            before_user[4:8]=b'\0'*4;before_user[11]=0
            assert bytes(self.u.mem_read(0x20020000,65536))==before_user,'Invalid pointer changed game/backbuffer state'
            self.calls.append({'key':key,'buttons':buttons,'valid_video':False,'published':hex(published)})
            return None
        destination=self.fb
        frame=bytes(self.u.mem_read(destination,32768))
        back=bytes(self.u.mem_read(0x20028000,32768))
        assert back==ct.string_at(native.native_back_frame(),32768)
        native_frame=ct.string_at(native.native_frame(),32768)
        for p in range(4):
            start=p*8192
            assert frame[start:start+8000]==back[start:start+8000]==native_frame[start:start+8000],f'ARM/native image mismatch, key {key}'
        assert self.live_writes==32000 and not self.bad_video_write
        assert self.back_snapshot==back,'Rendering continued after presenting began'
        assert bytes(self.u.mem_read(arm_symbols['art'],level['asset_raw_bytes']))==ct.string_at(native.native_art(),level['asset_raw_bytes'])
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
        assert arm_sizes['drones']==8*20
        positions=[]
        for i in range(8):
            base=arm_symbols['drones']+20*i
            hp=struct.unpack('<I',self.u.mem_read(base+8,4))[0]
            assert hp==native.native_drone(i)
            for offset,getter in [(0,native.native_drone_x),(4,native.native_drone_y)]:
                assert bytes(self.u.mem_read(base+offset,4))==struct.pack('<f',getter(i)),('Drone position differs',i)
            positions.append([native.native_drone_x(i),native.native_drone_y(i)])
        for i,name in enumerate(['god_mode','cheat_pos','cheat_message','ai_on','sector','blue_key',
                                 'secret_found','notice','tour_x','tour_y','nav_seed','weapon']):
            value=int.from_bytes(self.u.mem_read(arm_symbols[name],arm_sizes[name]),'little',signed=name=='nav_seed')
            assert value==native.native_state(23+i),(name,value,native.native_state(23+i))
        for address in [arm_symbols['__state_end'],0x20028000-16,0x20030000]:
            assert bytes(self.u.mem_read(address,16))==b'\xa5'*16,f'RAM guard overwritten at {address:x}'
        after_ccm=bytes(self.u.mem_read(0x10000000,65536));offset=destination-0x10000000
        assert after_ccm[:offset]==before_ccm[:offset] and after_ccm[offset+32768:]==before_ccm[offset+32768:]
        for p in range(4):
            start=p*8192+8000;end=(p+1)*8192
            assert frame[start:end]==before_ccm[offset+start:offset+end],'VGA padding changed'
            assert back[start:end]==b'\xa5'*192,'Backbuffer padding changed'
        self.calls.append({'key':key,'buttons':buttons,'state':state,'x':native.native_x(),'y':native.native_y(),
                           'god':native.native_state(23),'sound':native.native_sound(),'drones':positions,
                           'sector':native.native_state(27),'blue_key':native.native_state(28),
                           'secret':native.native_state(29),'weapon':native.native_state(34),
                           'valid_video':True,'resolved_framebuffer':hex(destination),
                           'sha256':hashlib.sha256(frame).hexdigest()})
        return frame

libname=os.environ.get('UNIDOOM_DIRECT_Z80EX','libz80ex.so.1')
fallback=Path('/usr/local/tmp/unigray-tools/root/usr/lib/x86_64-linux-gnu/libz80ex.so.1')
try: z=ct.CDLL(libname)
except OSError:
    if not fallback.exists(): raise SystemExit('Install libz80ex1 or set UNIDOOM_DIRECT_Z80EX')
    z=ct.CDLL(str(fallback))
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
    def __init__(self,corrupt=False,published=fb):
        self.arm=ARM(published); self.memory=bytearray(65536)
        self.memory[load:load+length]=mzf[128:]
        self.vram=[bytearray(b'\x6d'*8192) for _ in range(4)]
        self.vram_reads=self.vram_writes=0
        self.vram_mapped=False
        self.wf=0; self.border=0; self.column=0; self.keys=[]
        self.command=0; self.args=[]; self.remaining=0; self.cursor=0
        self.busy=0; self.corrupt=corrupt; self.error=None
        self.blocks=[]; self.uploads=0; self.selected=[]
        self.cycles=0; self.next_interrupt=70000
        self.interrupts=0; self.frame_starts=[]
        self.psg_stream=[]
        self.callbacks=(MR(self.read_memory),MW(self.write_memory),
                        PR(self.read_port),PW(self.write_port),IR(lambda *_:0))
        mr,mw,pr,pw,ir=self.callbacks
        self.cpu=z.z80ex_create(mr,None,mw,None,pr,None,pw,None,ir,None)
        z.z80ex_set_reg(self.cpu,10,execute)
    def read_memory(self,ctx,address,m1,data):
        if self.vram_mapped and 0x8000<=address<0xa000:
            self.vram_reads+=1
            self.error=AssertionError('Sharp VRAM read in direct renderer')
            return self.vram[0][address-0x8000]
        return self.memory[address]
    def write_memory(self,ctx,address,value,data):
        if self.vram_mapped and 0x8000<=address<0xa000:
            self.vram_writes+=1
            self.error=AssertionError('Sharp VRAM write in direct renderer')
            for p in range(4):
                if self.wf&(1<<p): self.vram[p][address-0x8000]=value
        else: self.memory[address]=value
    def read_port(self,ctx,port,data):
        p=port&255
        if p==0xe0:
            self.vram_mapped=True
        if p==0xe1:
            self.vram_mapped=False
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
        elif p==0xf2:self.psg_stream.append((self.cycles,value))
        elif p==0xcc:
            raise AssertionError('GDG plane write selection in direct renderer')
        elif p==0xcf and port>>8==6: self.border=value
        elif p==0x50:
            assert self.remaining==0,'Previous UniCard block was not consumed'
            assert value!=0xce,'Framebuffer readback in direct renderer'
            self.command=value; self.args=[]
        elif p==0x51:
            if self.command in [0xca,0xcd]:
                self.args.append(value)
                if len(self.args)==4:
                    address=int.from_bytes(bytes(self.args),'little')
                    if self.command==0xca: self.cursor=address
                    else:
                        self.frame_starts.append((self.cycles,self.interrupts))
                        self.arm.call(address); self.busy=1
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
                    self.interrupts+=1
                    self.cycles+=accepted
                    self.next_interrupt=self.cycles+70000
        raise AssertionError('Z80 instruction limit')
    def frame(self,key=0):
        self.keys=[] if key==0 else [key] if isinstance(key,int) else list(key)
        self.run_until(symbols['frame_done'])
        actual=bytes(self.arm.u.mem_read(self.arm.fb,32768))
        assert b''.join(self.vram)==b'\x6d'*32768,'Sharp VRAM changed'
        assert self.vram_reads==self.vram_writes==0
        assert not self.blocks and not self.selected and not self.vram_mapped
        if len(self.frame_starts)>1:
            previous,current=self.frame_starts[-2:]
            assert current[1]-previous[1]>=3,'Render not paced by three VBLANKs'
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
    # Type the whole cheat while no ARM frames are consumed. Its final event
    # must survive the busy interval, rather than losing letters in a mailbox.
    for key in 'DDQD':
        tap.keys=[ord(key)];assert z.z80ex_int(tap.cpu);tap.run_until(symbols['upload'])
        tap.keys=[];assert z.z80ex_int(tap.cpu);tap.run_until(symbols['upload'])
    assert tap.memory[symbols['pending_key']]==254,'Fast DDQD lost during ARM work'
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

def verify_firmware_video_pointer():
    valid=[0x10000000,fb,0x10004000,0x10008000,0x10000001,0x10007fff]
    invalid=[0,0xffffffff,FLASH_SLOT,0x0fffffff,0x10008001,0x20028000,0x40000000]
    for address in valid:
        arm=ARM(address);arm.u.mem_write(0x20020000,payload);arm.call(entry)
        assert arm.calls[-1]['resolved_framebuffer']==hex(address)
        assert arm.u.mem_read(0x20020009,1)==b'\x01'
    for address in invalid:
        arm=ARM(address);arm.u.mem_write(0x20020000,payload)
        arm.u.mem_write(0x20020004,struct.pack('<I',fb)) # stale valid header must be cleared
        arm.call(entry)
        assert arm.u.mem_read(0x20020009,1)==b'\x00','Invalid firmware initialized the game'
        assert arm.calls[-1]['valid_video'] is False
    # Recover from invalid metadata before initialization, without any stale base.
    arm.u.mem_write(FLASH_SLOT,struct.pack('<I',0x10004000));arm.call(entry)
    assert arm.calls[-1]['resolved_framebuffer']=='0x10004000'
    # The host accepts a new base on the next frame, including a different bank
    # half; a later bad publication fails instead of using the preceding base.
    moved=Machine();moved.frame()
    moved.arm.u.mem_write(FLASH_SLOT,struct.pack('<I',0x10008000));moved.frame()
    assert moved.arm.calls[-1]['resolved_framebuffer']=='0x10008000'
    moved.arm.u.mem_write(FLASH_SLOT,struct.pack('<I',0x10008001))
    moved.run_until(symbols['failed']);moved.run_until(symbols['failure_loop'])
    assert moved.arm.calls[-1]['valid_video'] is False and moved.border==10
    assert [v for _,v in moved.psg_stream[-4:]]==[0x9f,0xbf,0xdf,0xff]
    assert not z.z80ex_int(moved.cpu)
    moved.close()
    for address in (0,0xffffffff,0x10008001):
        bad=Machine(published=address)
        bad.run_until(symbols['failed']);bad.run_until(symbols['failure_loop'])
        assert bad.border==10 and len(bad.arm.calls)==1 and not bad.arm.calls[0]['valid_video']
        assert [v for _,v in bad.psg_stream[-4:]]==[0x9f,0xbf,0xdf,0xff] and not z.z80ex_int(bad.cpu)
        assert bad.vram_reads==bad.vram_writes==0
        bad.close()
    print('Firmware VGA pointer: bounds, unaligned buffers, relocation and host failure verified',flush=True)
    return {'pointer_slot':hex(FLASH_SLOT),'accepted_bases':[hex(x) for x in valid],
            'rejected_values':[hex(x) for x in invalid],'little_endian_word_read_each_frame':True,
            'flash_unchanged':True,'invalid_pointer_no_initialization_or_framebuffer_writes':True,
            'runtime_relocation_and_stale_pointer_rejection':True,'host_invalid_pointer_muted_red_border':True}

