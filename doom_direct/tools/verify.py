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

ROOT=Path(__file__).resolve().parent.parent
os.chdir(ROOT)
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
mzf=(ROOT.parent/'unidoom_direct_v0_6.mzf').read_bytes()
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

libname=os.environ.get('UNIDOOM_DIRECT_Z80EX') or os.environ.get('UNIDOOM_Z80EX','libz80ex.so.1')
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

pointer_report=verify_firmware_video_pointer()
verify_short_taps()

def verify_audio_sequences():
    """Exercise the actual Z80 event selection and every PSG envelope byte."""
    m=Machine();m.run_until(symbols['upload']);m.next_interrupt=1<<60
    m.memory[symbols['music_enabled']]=0
    sounds=json.loads((ROOT/'build/sounds.json').read_text())
    for index,(name,frames) in enumerate(sounds.items()):
        m.arm.u.mem_write(0x2002000b,bytes([1<<index]))
        z.z80ex_set_reg(m.cpu,11,0xcf00)
        struct.pack_into('<H',m.memory,0xcf00,symbols['frame_done'])
        z.z80ex_set_reg(m.cpu,10,symbols['sound_fetch'])
        start=len(m.psg_stream);m.run_until(symbols['frame_done'])
        for _ in frames:
            assert z.z80ex_int(m.cpu)
            m.run_until(symbols['frame_done'])
        expected=[0xe4]
        for lo,hi,tone,noise in frames:
            divider=lo+(hi<<8)
            expected.extend([0x80|(divider&15),(divider>>4)&63,0x90|tone,0xf0|noise])
        assert [v for _,v in m.psg_stream[start:]]==expected,name
        assert m.memory[symbols['sound_left']]==0 and expected[-2:]==[0x9f,0xff]
    # Multiple events select the highest-priority bit, not a random effect.
    m.arm.u.mem_write(0x2002000b,b'\xff')
    z.z80ex_set_reg(m.cpu,11,0xcf00)
    struct.pack_into('<H',m.memory,0xcf00,symbols['frame_done'])
    z.z80ex_set_reg(m.cpu,10,symbols['sound_fetch']);m.run_until(symbols['frame_done'])
    assert struct.unpack_from('<H',m.memory,symbols['sound_ptr'])[0]==symbols['sfx_god']+1
    gaps=[b[0]-a[0] for a,b in zip(m.psg_stream,m.psg_stream[1:])]
    assert min(gaps)>=32,'PSG writes lack required recovery delay'
    m.close()
    return len(sounds)

audio_effects=verify_audio_sequences()

def verify_music():
    """Compare two full Z80-played loops, muting, and percussion arbitration."""
    m=Machine();m.run_until(symbols['upload']);m.next_interrupt=1<<60
    song=json.loads((ROOT/'build/music.json').read_text())
    trace=[];durations=[]
    def irq():
        start=len(m.psg_stream);cycles=m.cycles
        accepted=z.z80ex_int(m.cpu);assert accepted
        m.cycles+=accepted;m.run_until(symbols['upload'])
        durations.append(m.cycles-cycles)
        return [value for _,value in m.psg_stream[start:]]
    def voice(note,latch,attenuation,phase):
        if not note:return [latch|0x1f]
        divider=song['dividers'][note]
        return [latch|(divider&15),(divider>>4)&63,latch|0x10|(attenuation+min(4,phase))]
    expanded=[(lead,bass,drum,phase,duration) for duration,lead,bass,drum in song['records'] for phase in range(duration)]
    loop_ticks=len(expanded)
    assert loop_ticks==song['total_ticks']
    import hashlib
    assert hashlib.sha256((ROOT.parent/'d_e1m1.mid').read_bytes()).hexdigest()==song['source_sha256']
    m.memory[0x9ff0:0xa000]=b'\xa5'*16;m.memory[0xa800:0xa810]=b'\xa5'*16
    for tick in range(loop_ticks*2):
        lead,bass,drum,phase,duration=expanded[tick%loop_ticks]
        command,attenuation=song['percussion'][str(drum)]
        expected=voice(lead,0xa0,7,phase)+voice(bass,0xc0,5,phase)
        expected += [command,0xf0|min(15,attenuation+2*phase)]
        actual=irq()
        assert actual==expected,('Music bytes differ',tick,actual,expected)
        trace.append(actual)
        assert m.memory[symbols['music_phase']]==(phase+1)%duration
        if tick%1000==0:print(f'E1M1 PSG tick {tick+1}/{loop_ticks*2} verified',flush=True)
    assert trace[:loop_ticks]==trace[loop_ticks:],'Music loop is not deterministic'
    assert m.memory[0x9ff0:0xa000]==m.memory[0xa800:0xa810]==b'\xa5'*16,'Music decoder history overflow'
    # B is acted on at key-down, including while ARM rendering is busy.
    m.keys=[ord('B')];irq();assert m.memory[symbols['music_enabled']]==0
    phase=m.memory[symbols['music_phase']];pointer=bytes(m.memory[symbols['music_ptr']:symbols['music_ptr']+2])
    assert irq()==[],'Holding B retriggered the toggle'
    m.keys=[];assert irq()==[]
    assert phase==m.memory[symbols['music_phase']] and pointer==bytes(m.memory[symbols['music_ptr']:symbols['music_ptr']+2])
    m.keys=[ord('B')];assert irq()==[];assert m.memory[symbols['music_enabled']]==1
    m.keys=[];assert irq()==trace[0],'Music did not restart cleanly'
    # A shot overlays the two music voices and owns noise until its last tick.
    m.arm.u.mem_write(0x2002000b,b'\x01')
    z.z80ex_set_reg(m.cpu,11,0xcf00);struct.pack_into('<H',m.memory,0xcf00,symbols['upload'])
    z.z80ex_set_reg(m.cpu,10,symbols['sound_fetch']);m.run_until(symbols['upload'])
    frames=json.loads((ROOT/'build/sounds.json').read_text())['shot']
    for index,(lo,hi,tone,noise) in enumerate(frames):
        actual=irq();divider=lo+(hi<<8)
        assert actual[:4]==[0x80|(divider&15),(divider>>4)&63,0x90|tone,0xf0|noise]
        commands=[b for b in actual[4:] if 0xe0<=b<0xf0]
        assert bool(commands)==(index==len(frames)-1),'Music stole SFX noise or failed to restore percussion'
        assert any(0xb0<=b<=0xbf for b in actual[4:]) and any(0xd0<=b<=0xdf for b in actual[4:])
    assert max(durations)<70000,'Music/keyboard ISR exceeds one modeled 50 Hz interval'
    assert min(b[0]-a[0] for a,b in zip(m.psg_stream,m.psg_stream[1:]))>=32
    (ROOT/'build/music_psg_trace.json').write_text(json.dumps({'tick_hz':50,'ticks':trace},separators=(',',':'))+'\n')
    m.close()
    return {'music_loops_byte_verified':2,'music_ticks_verified':len(trace),
            'music_mute_restart_and_held_key_checked':True,'music_sfx_noise_priority_checked':True,
            'music_source_sha256':song['source_sha256'],'music_seconds':song['loop_seconds'],
            'music_history_wrap_and_guards_checked':True,
            'max_music_keyboard_irq_tstates':max(durations)}

music_report=verify_music()
machine=Machine()
cases=[('boot',0),('walk1',ord('W')),('walk2',ord('W')),
       ('turn_walk',[ord('W'),ord('D')]),('turn',ord('D')),('release',0),
       ('fire1',32),('fire2',32),('fire3',32),('fire4',32),('fire5',32),('fire_release',0),
       ('map',ord('M')),('map_hold',ord('M')),('map_release',0),('light',ord('L')),
       ('run',ord('Z')),('reset',ord('R')),('strafe_l',ord('Q')),('strafe_r',ord('E')),
       ('use_far',ord('F')),('release2',0),('tour',ord('P')),('tour2',0),('tour3',0),
       ('manual',ord('W')),('reset2',ord('R')),('combo',[ord('W'),32,ord('F')]),
       ('release3',0),('escape',27),
       ('cheat_d1',ord('D')),('cheat_release1',0),('cheat_d2',ord('D')),('cheat_release2',0),
       ('cheat_q',ord('Q')),('cheat_release3',0),('cheat_on',ord('D')),('cheat_release4',0),
       ('off_d1',ord('D')),('off_release1',0),('off_d2',ord('D')),('off_release2',0),
       ('off_q',ord('Q')),('off_release3',0),('cheat_off',ord('D')),('off_release4',0),
       ('music_off',ord('B')),('music_release',0),('music_on',ord('B')),('music_release2',0),
       ('sector2',ord('2')),('sector2_walk',ord('W')),('sector1',ord('1')),
       ('shotgun',ord('V')),('shotgun_fire',32),('pistol',ord('V'))]
observed={}
for i,(name,keys) in enumerate(cases):
    data=machine.frame(keys);observed[name]=machine.arm.calls[-1]
    observed[name]['music_enabled']=machine.memory[symbols['music_enabled']]
    if name=='boot':image(data).resize((960,600),Image.Resampling.NEAREST).save('previews/boot.png')
    if i%8==0:print(f'Z80/ARM control frame {i+1}/{len(cases)} verified',flush=True)
assert observed['walk1']['buttons']==observed['walk2']['buttons']==1
assert observed['walk1']['x']>observed['boot']['x'] and observed['walk2']['x']>observed['walk1']['x']
assert observed['turn_walk']['buttons']==9 and observed['turn_walk']['state'][0]>0
assert observed['turn_walk']['x']>observed['walk2']['x']
assert observed['release']['buttons']==0
assert observed['fire1']['state'][2]==71 and observed['fire5']['state'][2]==70
assert observed['map']['state'][11]==observed['map_hold']['state'][11]==1
assert observed['light']['state'][12]==0 and observed['run']['state'][13]==1
assert observed['reset']['sha256']==observed['boot']['sha256']
assert abs(observed['strafe_r']['y']-8.5)<1e-5
assert observed['tour']['state'][14]==1 and observed['tour3']['x']>observed['tour']['x']
assert observed['manual']['state'][14]==0
assert observed['combo']['buttons']==(1|64|128)
assert observed['escape']['sha256']==observed['boot']['sha256']
assert observed['cheat_on']['god']==1 and observed['cheat_on']['sound']&128
assert observed['cheat_off']['god']==0 and observed['cheat_off']['sound']&128
assert observed['walk2']['drones']!=observed['boot']['drones']
assert observed['music_off']['music_enabled']==observed['music_release']['music_enabled']==0
assert observed['music_on']['music_enabled']==1
assert observed['sector2']['sector']==1 and observed['sector1']['sector']==0
assert observed['shotgun']['weapon']==1 and observed['shotgun_fire']['state'][2]==70
assert observed['pistol']['weapon']==0

def fixture_pose(x,y,angle):
    for name,value in [('player_x',x),('player_y',y)]:machine.arm.u.mem_write(arm_symbols[name],struct.pack('<f',value))
    machine.arm.u.mem_write(arm_symbols['angle'],struct.pack('<I',angle))
    native.native_set_pose(x,y,angle)

# Locked door is denied before collecting the key, then opens normally.
fixture_pose(7.8,3.5,512)
machine.frame(ord('F'))
assert machine.arm.calls[-1]['state'][21]==0 and not machine.arm.calls[-1]['blue_key']
fixture_pose(9.5,6.5,0);machine.frame(0)
assert machine.arm.calls[-1]['blue_key']==1

# Inspect an actual lifting door through the Z80/ARM path at every stage.
for name,value in [('player_x',7.8),('player_y',3.5)]:
    machine.arm.u.mem_write(arm_symbols[name],struct.pack('<f',value))
machine.arm.u.mem_write(arm_symbols['angle'],struct.pack('<I',512))
machine.arm.u.mem_write(arm_symbols['auto_mode'],struct.pack('<I',0))
native.native_set_pose(7.8,3.5,512)
machine.arm.u.mem_write(arm_symbols['ai_on'],(0).to_bytes(arm_sizes['ai_on'],'little'))
native.native_ai(0)
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
fixture_pose(5.5,9.5,256);machine.frame(ord('F'))
assert machine.arm.calls[-1]['secret']==1
fixture_pose(*level['core'],0);machine.frame(0)
fixture_pose(*level['exit'],0);machine.frame(0)
assert machine.arm.calls[-1]['state'][6]==1
machine.frame(ord('N'));assert machine.arm.calls[-1]['sector']==1 and not machine.arm.calls[-1]['blue_key']
image(machine.frame(ord('M'))).resize((960,600),Image.Resampling.NEAREST).save('previews/sector2.png')
calls=machine.arm.calls
assert machine.uploads==len(payload)+2*len(calls)
frame_intervals=[b[0]-a[0] for a,b in zip(machine.frame_starts,machine.frame_starts[1:])]
machine.close()

bad=Machine(corrupt=True)
bad.run_until(symbols['failed']);bad.run_until(symbols['failure_loop'])
assert bad.border==10 and not bad.arm.calls
assert [v for _,v in bad.psg_stream[-4:]]==[0x9f,0xbf,0xdf,0xff] and not z.z80ex_int(bad.cpu)
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
        'framebuffer':'runtime from 0x08008228','default_fixture_framebuffer':hex(fb),'direct_framebuffer_bytes':32768,
        'framebuffer_readback_bytes_per_frame':0,'blocks_per_frame':0,
        'sharp_vram_reads':machine.vram_reads,'sharp_vram_writes':machine.vram_writes,
        'ccm_outside_framebuffer_unchanged':True,'arm_backbuffer':hex(0x20028000),
        'render_complete_before_present_checked':True,'present_bytes_per_frame':32000,
        'compressed_art_arm_native_exact':True,'keys_secrets_sectors_and_shotgun_through_z80':True,
        'three_vblank_frame_pacing_checked':True,
        'sound_effects_byte_verified':audio_effects,'sound_event_arm_native_comparison':True,
        'moving_drone_positions_exactly_compared':8,'ddqd_toggle_through_z80_keyboard':True,
        'visible_plane_bytes':8000,'all_plane_padding_unchanged':True,
        'emulated_z80_tstates_between_frames':[min(frame_intervals),max(frame_intervals)],
        'mzf_sha256':hashlib.sha256(mzf).hexdigest(),'calls':calls}
report.update(check_scene(native,image,indices))
report.update(music_report)
report['firmware_video_pointer']=pointer_report
(ROOT/'build/verification.json').write_text(json.dumps(report,indent=2)+'\n')
print('PASS: ARM backbuffer -> CCM, zero Sharp VRAM access/readback, compressed assets, sectors, gameplay, music and sound.')

