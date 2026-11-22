#!/usr/bin/env python3
"""Real Z80/ARM peers against an emulated NET card and the included relay."""
from emulation import *
from relay import Relay,Peer
from skin_helpers import native_skins,arm_skins
from unicorn.arm_const import UC_ARM_REG_R0

class NetARM(ARM):
    def call(self,pointer):
        assert pointer==entry
        self.fb=struct.unpack('<I',self.u.mem_read(FLASH_SLOT,4))[0]
        before=bytes(self.u.mem_read(0x10000000,65536))
        self.u.reg_write(UC_ARM_REG_SP,0x20010000);self.u.reg_write(UC_ARM_REG_LR,0x20000001)
        self.live_writes=0;self.back_snapshot=None;self.bad_video_write=False;self.flash_reads=[]
        self.u.emu_start(pointer,0x20000000,count=100_000_000)
        assert self.u.reg_read(UC_ARM_REG_PC)==0x20000000
        assert self.flash_reads==[(FLASH_SLOT,4)]
        assert self.live_writes==32000 and not self.bad_video_write
        back=bytes(self.u.mem_read(0x20028000,32768));assert self.back_snapshot==back
        after=bytes(self.u.mem_read(0x10000000,65536));off=self.fb-0x10000000
        assert before[:off]==after[:off] and before[off+32768:]==after[off+32768:]
        for p in range(4):
            assert after[off+p*8192:off+p*8192+8000]==back[p*8192:p*8192+8000]
            assert after[off+p*8192+8000:off+(p+1)*8192]==before[off+p*8192+8000:off+(p+1)*8192]
        for address in [arm_symbols['__state_end'],0x20028000-16,0x20030000]:
            assert bytes(self.u.mem_read(address,16))==b'\xa5'*16
        self.calls.append({'net':bytes(self.u.mem_read(0x2002000c,24)).hex()})
        return bytes(self.u.mem_read(self.fb,32768))
    def state(self):
        names=['peers','world_map','door_open','door_goal','frame','won','sector','secret_found']
        return b''.join(bytes(self.u.mem_read(arm_symbols[n],arm_sizes[n])) for n in names)
    def net(self,slot,mask,tick,inputs,ui=0):
        blob=struct.pack('<BBBBHH4sBB8sBB',2,slot,mask,ui,tick,0,b'TEST',0,mask,bytes(inputs),0,4)
        self.u.mem_write(0x2002000c,blob);self.call(entry)
        return struct.unpack('<H',self.u.mem_read(0x20020012,2))[0]
    def peers(self):return bytes(self.u.mem_read(arm_symbols['peers'],arm_sizes['peers']))

class Card:
    def __init__(self,relay,supported=True):
        self.relay=relay;self.peer=Peer();self.supported=supported
        self.state=1;self.slot=0;self.members=0;self.ready=0;self.slots=4;self.nbytes=1
        self.mask=0;self.frames={};self.avail=-1;self.seed=0;self.start=65535
        self.cmd=0;self.args=[];self.out=bytearray();self.st=[0,0,0,0];self.stpos=0
        self.status_selected=False;self.pending=0;self.log=[];self.err=0
    def pump(self):
        while self.peer.output:
            m=self.peer.output.popleft();op=m['op']
            if op=='room':
                self.state=2;self.slot=m['slot'];self.slots=m.get('slots',self.slots);self.nbytes=m.get('bytes',self.nbytes)
                self.code=m['code'];self.settings=bytes.fromhex(m.get('settings','0200'));self.frames={};self.avail=-1
            elif op=='members':self.members=m['count'];self.ready=m['ready']
            elif op=='start':self.state=3;self.seed=m['seed'];self.start=m['frame'];self.mask=m['mask'];self.frames={};self.avail=-1
            elif op=='input':self.frames.setdefault(m['frame'],{})[m['slot']]=bytes.fromhex(m['data'])
            elif op=='desync':self.state=4
            elif op=='dropped':self.state=5
            elif op=='error':self.err=m['code']
    def send(self,m):self.relay.handle(self.peer,m);self.pump()
    def command(self,value):
        if value==3:
            self.status_selected=True;self.stpos=0
            if self.pending:
                self.pending-=1
                if not self.pending:self.st=[2,self.cmd,len(self.out),0]
            return
        self.status_selected=False;self.cmd=value;self.args=[];self.out=bytearray();self.st=[1,value,0,0]
        if value==4:self.st=[0,0,0,0];self.pending=0
        elif value in (6,0x95,0xa0,0xa3):self.execute()
    def write(self,value):
        self.args.append(value)
        lengths={0xa1:23,0xa2:9,0xa4:1,0xa5:6,0xa6:2,0xa7:4}
        if len(self.args)==lengths[self.cmd]:self.execute()
    def execute(self):
        self.pump();p=bytes(self.args);cmd=self.cmd;self.err=0;out=b''
        if cmd==6:out=bytes([3,0,ord('U'),0])
        elif cmd==0x95:
            if self.supported:out=bytes([0,0,0,8])+bytes(12)
            else:self.st=[0x82,cmd,1,0];return # old firmware's stale OUTPUT bit
        elif cmd==0xa0:out=bytes([self.state,self.slot,self.members,self.ready,0,0,0,self.err])
        elif cmd==0xa1:
            game,build=struct.unpack_from('<HH',p)
            self.send(dict(op='create',game=game,build=build,slots=p[4],bytes=p[5],settings=p[7:7+p[6]].hex()))
            if not self.err:out=self.code.encode()+b'\r'+bytes([self.slot])
        elif cmd==0xa2:
            game,build=struct.unpack_from('<HH',p)
            self.send(dict(op='join',game=game,build=build,code=p[4:8].decode()))
            if not self.err:out=bytes([self.slot,self.slots,self.nbytes,len(self.settings)])+self.settings.ljust(16,b'\0')
        elif cmd==0xa3:self.relay.leave(self.peer);self.state=1
        elif cmd==0xa4:
            self.send(dict(op='ready',ready=p[0]));out=struct.pack('<HH',self.seed if self.state==3 else 65535,self.start)
        elif cmd==0xa5:
            f=struct.unpack_from('<H',p)[0];data=p[2:2+self.nbytes]
            self.frames.setdefault(f,{})[self.slot]=data
            self.send(dict(op='input',frame=f,data=data.hex()))
        elif cmd==0xa6:
            f=struct.unpack('<H',p)[0]
            while self.mask and sum(1<<i for i in self.frames.get(self.avail+1,{}))&self.mask==self.mask:self.avail+=1
            out=struct.pack('<H',self.avail if self.avail>=0 else 65535)
            out+=b''.join(self.frames.get(f,{}).get(i,bytes(self.nbytes)) if 0<=f<=self.avail else bytes(self.nbytes) for i in range(self.slots))
        elif cmd==0xa7:
            f,h=struct.unpack('<HH',p);self.send(dict(op='hash',frame=f,hash=h))
        else:raise AssertionError(hex(cmd))
        self.out=bytearray(out);self.log.append((cmd,p,bytes(out)))
        if self.err:self.st=[0x80,cmd,self.err,0]
        elif cmd in (0xa1,0xa2):self.pending=3;self.st=[0x40,cmd,0,0]
        else:self.st=[2 if out else 0,cmd,len(out),0]
    def read_status(self):
        value=self.st[self.stpos];self.stpos=min(3,self.stpos+1);return value
    def read(self):assert self.out;return self.out.pop(0)

class NetMachine(Machine):
    def __init__(self,relay,supported=True):
        super().__init__();self.arm=NetARM();self.card=Card(relay,supported);self.card_active=False
    def read_port(self,ctx,port,data):
        try:
            if port&255==0x50 and self.card_active:return self.card.read_status()
            if port&255==0x51 and self.card_active:return self.card.read()
            return super().read_port(ctx,port,data)
        except BaseException as exc:self.error=exc;return 255
    def _write_port(self,port,value):
        p=port&255
        if p==0x50:
            if value in [3,4,6,0x95,*range(0xa0,0xaa)]:
                self.card_active=True;self.card.command(value);return
            self.card_active=False
        if p==0x51 and self.card_active:self.card.write(value);return
        super()._write_port(port,value)
    def field(self,n):return self.memory[symbols['net_'+n]]
    def key(self,k):self.frame(ord(k) if isinstance(k,str) else k);self.frame()

def relay_checks():
    r=Relay();a,b,c,d=[Peer() for _ in range(4)]
    r.handle(a,dict(op='create',game=0x5544,build=1,slots=4,bytes=2,settings='0100'))
    code=a.room.code
    r.handle(b,dict(op='join',game=0x424e,build=1,code=code));assert b.output.pop()['code']==7
    r.handle(b,dict(op='join',game=0x5544,build=2,code=code));assert b.output.pop()['code']==6
    for p in [b,c,d]:r.handle(p,dict(op='join',game=0x5544,build=1,code=code))
    for p in [b,c,d]:r.handle(p,dict(op='ready',ready=1))
    assert not a.room.running
    r.handle(a,dict(op='ready',ready=1));assert a.room.running
    assert [p.slot for p in [a,b,c,d]]==list(range(4))
    for i,p in enumerate([a,b,c,d]):r.handle(p,dict(op='input',frame=0,data=bytes([i,255-i]).hex()))
    r.handle(a,dict(op='hash',frame=0,hash=123));r.handle(b,dict(op='hash',frame=0,hash=124))
    assert any(m['op']=='desync' for m in c.output)
    r.leave(b);assert any(m['op']=='dropped' for m in a.output)
    for count in (2,3,4):
        r=Relay();peers=[Peer() for _ in range(count)]
        r.handle(peers[0],dict(op='create',game=0x5544,build=2,slots=count,bytes=2,settings='0200'))
        room=peers[0].room
        r.handle(peers[0],dict(op='ready',ready=1));assert not room.running
        for index,p in enumerate(peers[1:],1):
            r.handle(p,dict(op='join',game=0x5544,build=2,code=room.code))
            r.handle(p,dict(op='ready',ready=1))
            assert room.running==(index==count-1)
    print('Relay: exact 2/3/4-player readiness, game/build isolation, inputs, desync/drop PASS',flush=True)

def arm_checks():
    a,b=NetARM(),NetARM()
    for p in (a,b):
        p.u.mem_write(0x20020000,payload);p.call(entry);arm_skins(p,ROOT,arm_symbols)
    native.native_net.argtypes=[ct.c_uint,ct.c_uint,ct.c_uint,ct.POINTER(ct.c_uint8)]
    native.native_net_hash.restype=ct.c_uint
    native.native_peers.restype=ct.c_void_p
    native.native_cold();native.native_key(0,0);native_skins(native,ROOT)
    hashes=[]
    for tick in range(10):
        keys=bytes([ord('V') if tick==3 else ord('N') if tick==7 else 0,1 if tick<4 else 64,0,8,0,16,0,2])
        h=a.net(0,15,tick,keys);assert b.net(3,15,tick,keys)==h
        assert a.state()==b.state(),'Different local cameras changed the shared state'
        native.native_net(0,15,tick,(ct.c_uint8*8).from_buffer_copy(keys))
        assert native.native_net_hash()==h,'ARM/native state hash differs'
        assert ct.string_at(native.native_peers(),arm_sizes['peers'])==a.peers()
        assert ct.string_at(native.native_back_frame(),32768)==bytes(a.u.mem_read(0x20028000,32768))
        hashes.append(h)
    before=a.state();a.net(0,15,9,bytes(8),ui=4);assert a.state()==before,'Waiting advanced simulation'
    a.net(0,15,9,bytes(8));assert a.state()==before,'Duplicate tick ran twice'
    image(bytes(a.u.mem_read(fb,32768))).resize((960,600),Image.Resampling.NEAREST).save('previews/deathmatch.png')
    image(bytes(b.u.mem_read(fb,32768))).resize((960,600),Image.Resampling.NEAREST).save('previews/deathmatch_peer.png')
    print('Two actual Cortex-M4 peers: four players, camera-independent hashes, stall/duplicate freeze PASS',flush=True)
    return hashes

def z80_checks():
    relay=Relay();a=NetMachine(relay);b=NetMachine(relay)
    for p in (a,b):p.frame()
    a.key('H');assert a.field('mode')==1 and a.field('ui')==3 and a.card.peer.room is None
    a.key('1');assert a.field('ui')==3,'Invalid player count created a room'
    a.key('2');assert a.field('ui')==1 and a.field('slots')==2
    # A legal code that is also the offline cheat must remain typeable.
    room=a.card.peer.room;relay.rooms.pop((room.game,room.code));room.code='DDQD'
    relay.rooms[room.game,room.code]=room
    a.memory[symbols['net_code']:symbols['net_code']+4]=b'DDQD';code='DDQD'
    a.key(' ');assert a.card.state==2,'Host started with one player'
    b.key('J')
    for ch in code:b.key(ch)
    assert b.field('slot')==1 and b.field('ui')==1
    a.key(' ');assert a.card.state==2,'Host started before joiner ready'
    b.key(' ');a.key(' ')
    for _ in range(8):a.frame();b.frame()
    assert a.field('mode')==b.field('mode')==2
    for _ in range(10):a.frame(ord('W'));b.frame(ord('D'))
    a.card.pump();b.card.pump();assert a.card.state==b.card.state==3
    hashes=a.card.peer.room.hashes
    # Physical host upload switches all three frames to the marine artwork.
    for p in (a,b):
        data=b''.join(bytes(p.arm.u.mem_read(arm_symbols['art']+4096+slot*512,512)) for slot in (0,3,4))
        assert data==(ROOT/'build/marines.bin').read_bytes()
    # Brief packet waits must preserve VGA bytes and run no ARM render call.
    for _ in range(6):
        count=len(a.arm.calls);a.frame()
        if len(a.arm.calls)==count:break
    else:raise AssertionError('Peer did not reach the missing-input frame')
    before=a.arm.state();pixels=bytes(a.arm.u.mem_read(fb,32768));calls=len(a.arm.calls)
    a.frame(ord('M'));a.frame();a.frame()
    assert a.arm.state()==before and len(a.arm.calls)==calls
    assert bytes(a.arm.u.mem_read(fb,32768))==pixels,'Transient stall flashed the VGA image'
    assert a.field('wait_visible')==0
    # After 800ms there is one warning render, never repeated every poll.
    for _ in range(45):a.frame()
    assert a.field('wait_visible')==1 and len(a.arm.calls)==calls+1
    assert a.arm.state()==before,'A sustained stall advanced game simulation'
    assert struct.unpack('<I',a.arm.u.mem_read(arm_symbols['map_on'],4))[0]==1,'A local key was lost while waiting'
    for _ in range(3):a.frame()
    assert len(a.arm.calls)==calls+1
    # Feed the missing peer and recover without another warning.
    for _ in range(3):b.frame();a.frame()
    assert a.field('wait_visible')==0

    assert hashes and all(len(set(h.values()))==1 for h in hashes.values())
    # Compare peers at the same completed frame after deliberately slowing one.
    for _ in range(16):
        last=[struct.unpack('<H',p.arm.u.mem_read(arm_symbols['processed_tick'],2))[0] for p in (a,b)]
        if last[0]==last[1]:break
        (a if last[0]<last[1] else b).frame()
    else:raise AssertionError(('Peers failed to catch up',last))
    assert a.arm.state()==b.arm.state(),('Shared state mismatch at equal frame',last)
    b.key(27);a.frame();assert a.field('ui')==5 and a.field('error_code')==14
    a.key(27);assert a.field('mode')==0
    restored=b''.join(bytes(a.arm.u.mem_read(arm_symbols['art']+4096+slot*512,512)) for slot in (0,3,4))
    assert restored==(ROOT/'build/drones.bin').read_bytes(),'Marine graphics leaked into single-player'
    for p in (a,b):
        assert p.vram_reads==p.vram_writes==0
        assert any(cmd==0xa5 and len(params)==6 for cmd,params,out in p.card.log)
        sent=[struct.unpack_from('<H',params)[0] for cmd,params,out in p.card.log if cmd==0xa5]
        assert sent[:3]==[0,1,2] and len(sent)==len(set(sent)),'Input was duplicated while stalled'
        p.close()
    old=NetMachine(Relay(),supported=False);old.frame();old.key('H');assert old.field('ui')==6
    old.key(27);assert old.field('mode')==0;old.close()
    bad=NetMachine(Relay());bad.frame();bad.key('J')
    for ch in 'ZZZZ':bad.key(ch)
    assert bad.field('ui')==5 and bad.field('error_code')==7;bad.close()
    # Exercise the ten-second async timeout with actual VBLANK interrupts.
    timeout=NetMachine(Relay());timeout.frame()
    timeout.memory[symbols['net_mode']]=1
    timeout.card.command(0xa1);timeout.card.pending=100000;timeout.card_active=True
    timeout.card.st=[0x40,0xa1,0,0]
    z.z80ex_set_reg(timeout.cpu,11,0xcf00)
    struct.pack_into('<H',timeout.memory,0xcf00,symbols['frame_done'])
    z.z80ex_set_reg(timeout.cpu,10,symbols['net_wait'])
    # Fast-forward idle HALT T-states; execute all 500 real IRQ handlers.
    z.z80ex_doing_halt.argtypes=[ct.c_void_p];z.z80ex_doing_halt.restype=ct.c_int
    for _ in range(2_000_000):
        timeout.cycles+=z.z80ex_step(timeout.cpu)
        if timeout.error:raise timeout.error
        if z.z80ex_get_reg(timeout.cpu,10)==symbols['frame_done']:break
        if z.z80ex_doing_halt(timeout.cpu):timeout.cycles=max(timeout.cycles,timeout.next_interrupt)
        if timeout.cycles>=timeout.next_interrupt:
            accepted=z.z80ex_int(timeout.cpu)
            if accepted:
                timeout.interrupts+=1;timeout.cycles+=accepted
                timeout.next_interrupt=timeout.cycles+70000
    else:raise AssertionError('Timeout instruction budget')
    assert z.z80ex_get_reg(timeout.cpu,0)>>8==12
    assert not(z.z80ex_get_reg(timeout.cpu,0)&0x40),'Timeout returned a success Z flag'
    assert struct.unpack_from('<H',timeout.memory,symbols['net_clock'])[0]>=500
    timeout.close()
    print('Two real Z80 hosts + ARM + card/relay: create/join/ready/input/hash/drop/offline/timeout PASS',flush=True)
    return {'room':code,'hash_frames':list(hashes),'common_states_equal':True}

def count_checks():
    for count in (3,4):
        relay=Relay();machines=[NetMachine(relay) for _ in range(count)]
        for m in machines:m.frame()
        host=machines[0];host.key('H');assert host.field('ui')==3
        host.key(str(count));assert host.field('slots')==count
        code=bytes(host.memory[symbols['net_code']:symbols['net_code']+4]).decode()
        for index,m in enumerate(machines[1:],1):
            m.key('J')
            for c in code:m.key(c)
            assert m.field('slots')==count and m.field('slot')==index
            m.key(' ')
            if index<count-1:
                host.key(' ');assert host.card.peer.room.running is False,'Partial lobby started early'
        host.key(' ')
        for _ in range(5):
            for m in machines:m.frame()
        assert all(m.field('mode')==2 and m.field('mask')==(1<<count)-1 for m in machines)
        for m in machines:
            polls=[out for cmd,args,out in m.card.log if cmd==0xa6]
            assert polls and all(len(out)==2+count*2 for out in polls)
            m.close()
        print(f'Exact {count}-player lobby and real Z80/ARM match PASS',flush=True)

if __name__=='__main__':
    relay_checks();hashes=arm_checks();z80_report=z80_checks();count_checks()
    report=dict(mzf_sha256=hashlib.sha256(mzf).hexdigest(),arm_hashes=hashes,z80=z80_report,actual_z80_and_cortex_m4=True,sharp_vram_accesses=0,exact_player_counts=[2,3,4],
                transient_wait_preserves_frame=True,sustained_wait_single_warning=True,
                marines_uploaded_and_drones_restored=True)
    (ROOT/'build/network_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print('PASS: UniDoom NET multiplayer emulation')
