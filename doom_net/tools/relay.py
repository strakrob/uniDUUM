#!/usr/bin/env python3
"""UniDoom NET LAN relay: BomberNet-compatible JSON lines over TCP (8766).

Independent implementation of the documented game-independent protocol.
Python standard library only. It carries inputs, not rendered video.
"""
import argparse
import asyncio
from collections import deque
import json
import secrets
import socket
from datetime import datetime

class Peer:
    def __init__(self, emit=None):
        self.output=deque();self.emit=emit or self.output.append
        self.room=None;self.slot=-1

class Room:
    def __init__(self,game,build,slots,nbytes,settings,code):
        self.game=game;self.build=build;self.slots=slots;self.nbytes=nbytes
        self.settings=settings;self.code=code;self.peers={};self.ready=0
        self.required=slots if game==0x5544 and bytes.fromhex(settings)[:1]==b'\x02' else 1
        self.running=False;self.dropped=False;self.hashes={};self.seed=secrets.randbelow(65536)
    def send(self,message,exclude=None):
        for peer in list(self.peers.values()):
            if peer is not exclude:
                try:peer.emit(message)
                except (ConnectionError,RuntimeError):pass
    def members(self):self.send(dict(op='members',count=len(self.peers),ready=self.ready))

class Relay:
    def __init__(self,log=None):self.rooms={};self.log=log or (lambda text:None)
    def error(self,peer,code,text):
        self.log(f'ERROR {code}: {text}')
        peer.emit(dict(op='error',code=code,text=text))
    def leave(self,peer):
        room=peer.room
        if room is None:return
        slot=peer.slot;room.peers.pop(slot,None);room.ready&=~(1<<slot)
        room.dropped=True
        self.log(f'ROOM {room.code}: P{slot+1} disconnected; match stopped')
        room.send(dict(op='dropped',slot=slot));room.members()
        peer.room=None;peer.slot=-1
        if not room.peers:self.rooms.pop((room.game,room.code),None)
    def handle(self,peer,message):
        try:self._handle(peer,message)
        except (ValueError,TypeError,KeyError):self.error(peer,10,'Bad parameter')
    def _handle(self,peer,m):
        op=m['op']
        if op=='ping':peer.emit(dict(op='pong',t=m.get('t')));return
        if op=='leave':self.leave(peer);return
        if op in ('create','join'):
            if peer.room is not None:self.error(peer,10,'Already in a room');return
            game=int(m['game']);build=int(m['build'])
            if not 0<=game<=65535 or not 0<=build<=65535:raise ValueError()
            if op=='create':
                slots=int(m['slots']);nbytes=int(m['bytes']);settings=m.get('settings','')
                if not 1<=slots<=4 or not 1<=nbytes<=4 or len(bytes.fromhex(settings))>16:raise ValueError()
                if len(self.rooms)>=128:self.error(peer,11,'Relay full');return
                alphabet='ABCDEFGHJKLMNPQRSTUVWXYZ'
                while True:
                    code=''.join(secrets.choice(alphabet) for _ in range(4))
                    if (game,code) not in self.rooms:break
                room=Room(game,build,slots,nbytes,settings,code);self.rooms[game,code]=room;slot=0
            else:
                room=self.rooms.get((game,str(m['code']).upper()))
                if room is None or room.running or room.dropped or len(room.peers)>=room.slots:self.error(peer,7,'Room unknown/full/started');return
                if room.build!=build:self.error(peer,6,'Build mismatch');return
                slot=next(s for s in range(room.slots) if s not in room.peers)
            peer.room=room;peer.slot=slot;room.peers[slot]=peer
            answer=dict(op='room',code=room.code,slot=slot,slots=room.slots,bytes=room.nbytes,settings=room.settings)
            peer.emit(answer);room.members()
            action='created' if op=='create' else 'joined'
            self.log(f'ROOM {room.code}: P{slot+1} {action}, {len(room.peers)}/{room.slots} connected, build {room.build:04X}')
            return
        room=peer.room
        if room is None or room.dropped:self.error(peer,8,'Not in a live room');return
        mask=sum(1<<slot for slot in room.peers)
        if op=='ready':
            if room.running:return
            if m['ready']:room.ready|=1<<peer.slot
            else:room.ready&=~(1<<peer.slot)
            room.members()
            self.log(f'ROOM {room.code}: {room.ready.bit_count()}/{room.slots} ready, {len(room.peers)}/{room.slots} connected')
            if room.ready==mask and len(room.peers)>=room.required:
                room.running=True;room.send(dict(op='start',seed=room.seed,frame=0,mask=mask))
                self.log(f'ROOM {room.code}: START {len(room.peers)} players, mask {mask:02X}')
        elif op=='input':
            frame=int(m['frame']);data=m['data']
            if not room.running or not 0<=frame<60002 or len(bytes.fromhex(data))!=room.nbytes:raise ValueError()
            room.send(dict(op='input',frame=frame,slot=peer.slot,data=data),exclude=peer)
        elif op=='hash':
            frame=int(m['frame']);value=int(m['hash'])
            if not room.running or not 0<=frame<60000 or not 0<=value<=65535:raise ValueError()
            hashes=room.hashes.setdefault(frame,{})
            hashes[peer.slot]=value
            if len(set(hashes.values()))>1:
                room.send(dict(op='desync',frame=frame));self.log(f'ROOM {room.code}: DESYNC at frame {frame}')
            if len(room.hashes)>256:room.hashes.pop(min(room.hashes))
        elif op=='msg':
            data=m['data'];to=int(m['to'])
            if not 1<=len(bytes.fromhex(data))<=32:raise ValueError()
            answer=dict(op='msg',**{'from':peer.slot},data=data)
            if to==-1:room.send(answer,exclude=peer)
            elif to in room.peers:room.peers[to].emit(answer)
            else:raise ValueError()
        else:raise ValueError()

async def serve(bind='127.0.0.1',port=8766):
    def log(text):print(f'[{datetime.now().strftime("%H:%M:%S")}] {text}',flush=True)
    relay=Relay(log)
    async def connection(reader,writer):
        def emit(message):writer.write((json.dumps(message,separators=(',',':'))+'\n').encode())
        peer=Peer(emit)
        sock=writer.get_extra_info('socket')
        if sock:sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
        log(f'Card connected: {writer.get_extra_info("peername")}')
        try:
            while True:
                line=await asyncio.wait_for(reader.readline(),600)
                if not line:break
                if len(line)>1024:break
                try:
                    message=json.loads(line)
                    if not isinstance(message,dict):raise ValueError()
                    relay.handle(peer,message)
                except (ValueError,UnicodeError):relay.error(peer,10,'Bad JSON')
                await writer.drain()
        except (ConnectionError,asyncio.TimeoutError,ValueError):pass
        finally:
            relay.leave(peer);writer.close()
            try:await writer.wait_closed()
            except ConnectionError:pass
    server=await asyncio.start_server(connection,bind,port,limit=2048)
    print(f'UniDoom NET local server on {bind}:{port} (TCP JSON lines)',flush=True)
    if bind in ('0.0.0.0','::'):
        try:addresses=sorted({a for a in socket.gethostbyname_ex(socket.gethostname())[2] if not a.startswith('127.')})
        except OSError:addresses=[]
        if addresses:print('PC address candidates: '+', '.join(addresses),flush=True)
    print(f'UniCard: set NETRELAYADDR to this PC LAN IP; NETRELAYPORT to {port}.',flush=True)
    print('On the Sharp: H -> choose 2/3/4 players. Others: J -> room code. SPACE readies; host last. Ctrl+C stops server.',flush=True)
    async with server:await server.serve_forever()

def main(argv=None,default_bind='127.0.0.1'):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind',default=default_bind,help='Interface to listen on; LAN: 0.0.0.0')
    parser.add_argument('--port',type=int,default=8766)
    args=parser.parse_args(argv)
    if not 1<=args.port<=65535:parser.error('--port must be 1..65535')
    try:asyncio.run(serve(args.bind,args.port))
    except KeyboardInterrupt:print('Server stopped.',flush=True)
    except OSError as exc:parser.exit(1,f'Cannot start local server: {exc}\n')

if __name__=='__main__':main()
