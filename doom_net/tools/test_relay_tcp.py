#!/usr/bin/env python3
"""Exercise the actual LAN listener over loopback sockets."""
import asyncio
import contextlib
import json
import socket
from pathlib import Path
import hashlib
from relay import serve

async def test():
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
    server=asyncio.create_task(serve('127.0.0.1',port))
    for _ in range(100):
        try:a,aw=await asyncio.open_connection('127.0.0.1',port);break
        except ConnectionRefusedError:await asyncio.sleep(.01)
    else:raise AssertionError('Relay did not start')
    b,bw=await asyncio.open_connection('127.0.0.1',port)
    async def send(w,m):w.write((json.dumps(m)+'\n').encode());await w.drain()
    async def get(r,op):
        for _ in range(20):
            m=json.loads(await asyncio.wait_for(r.readline(),2))
            if m['op']==op:return m
        raise AssertionError(op)
    try:
        await send(aw,dict(op='ping',t=123));assert (await get(a,'pong'))['t']==123
        await send(aw,dict(op='create',game=0x5544,build=1,slots=2,bytes=2,settings='0200'))
        room=await get(a,'room');assert room['bytes']==2 and room['settings']=='0200' and room['slots']==2
        await send(bw,dict(op='join',game=0x5544,build=1,code=room['code']))
        assert (await get(b,'room'))['slot']==1
        await send(bw,dict(op='ready',ready=1));await send(aw,dict(op='ready',ready=1))
        assert (await get(a,'start'))['mask']==3;await get(b,'start')
        await send(aw,dict(op='input',frame=0,data='5640'));assert (await get(b,'input'))['data']=='5640'
        await send(aw,dict(op='hash',frame=0,hash=1));await send(bw,dict(op='hash',frame=0,hash=2))
        assert (await get(a,'desync'))['frame']==0
        bw.close();await bw.wait_closed();assert (await get(a,'dropped'))['slot']==1
        relay_path=Path(__file__).with_name('relay.py')
        report=Path(__file__).resolve().parent.parent/'build/relay_tcp_verification.json'
        report.parent.mkdir(exist_ok=True)
        report.write_text(json.dumps(dict(passed=True,actual_loopback_tcp=True,
            checks=['ping/pong','create settings','join','start','opaque inputs','desync','disconnect'],
            relay_sha256=hashlib.sha256(relay_path.read_bytes()).hexdigest()),indent=2)+'\n')
        print('PASS: TCP create/join/settings/start/input/hash/disconnect',flush=True)
    finally:
        for w in [aw,bw]:w.close()
        server.cancel()
        with contextlib.suppress(asyncio.CancelledError):await server
if __name__=='__main__':asyncio.run(test())
