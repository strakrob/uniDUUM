#!/usr/bin/env python3
"""Launch the shipped server.py and connect three real TCP clients."""
import asyncio
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
ROOT=Path(__file__).resolve().parent.parent

async def check():
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    proc=subprocess.Popen([sys.executable,str(ROOT/'server.py'),'--bind','127.0.0.1','--port',str(port)],
                          stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    connections=[]
    async def send(w,msg):w.write((json.dumps(msg)+'\n').encode());await w.drain()
    async def get(r,op):
        for _ in range(20):
            m=json.loads(await asyncio.wait_for(r.readline(),2))
            if m['op']==op:return m
        raise AssertionError(op)
    async def no_start(r):
        try:
            while True:
                m=json.loads(await asyncio.wait_for(r.readline(),.1))
                assert m['op']!='start','Server started before the selected number connected'
        except asyncio.TimeoutError:pass
    try:
        for _ in range(100):
            try:connections.append(await asyncio.open_connection('127.0.0.1',port));break
            except ConnectionRefusedError:await asyncio.sleep(.02)
        else:raise AssertionError('CLI server did not listen')
        a,aw=connections[0]
        await send(aw,dict(op='create',game=0x5544,build=2,slots=3,bytes=2,settings='0200'))
        room=await get(a,'room');assert room['slots']==3
        await send(aw,dict(op='ready',ready=1));await no_start(a)
        connections.append(await asyncio.open_connection('127.0.0.1',port));b,bw=connections[1]
        await send(bw,dict(op='join',game=0x5544,build=2,code=room['code']));assert (await get(b,'room'))['slot']==1
        await send(bw,dict(op='ready',ready=1));await no_start(a)
        connections.append(await asyncio.open_connection('127.0.0.1',port));c,cw=connections[2]
        await send(cw,dict(op='join',game=0x5544,build=2,code=room['code']));assert (await get(c,'room'))['slot']==2
        await send(cw,dict(op='ready',ready=1))
        starts=[await get(r,'start') for r,w in connections]
        assert all(s['mask']==7 and s['frame']==0 and s['seed']==starts[0]['seed'] for s in starts)
        for slot,(r,w) in enumerate(connections):await send(w,dict(op='input',frame=0,data=bytes([slot,64]).hex()))
        for slot,(r,w) in enumerate(connections):
            lines=[await get(r,'input') for _ in range(2)]
            assert {m['slot'] for m in lines}==set(range(3))-{slot}
            assert all(m['data']==bytes([m['slot'],64]).hex() for m in lines)
        bw.close();await bw.wait_closed();assert (await get(a,'dropped'))['slot']==1
    finally:
        for r,w in connections:w.close()
        await asyncio.sleep(.03)
        proc.terminate()
        try:output=proc.communicate(timeout=3)[0]
        except subprocess.TimeoutExpired:proc.kill();output=proc.communicate()[0]
    assert 'START 3 players' in output and '2/3 connected' in output and 'match stopped' in output,output
    (ROOT/'build/server_verification.json').write_text(json.dumps(dict(passed=True,
        real_server_entrypoint=True,real_tcp_clients=3,exact_count_start_gate=True,
        opaque_inputs=True,room_logs=True,disconnect=True,
        server_sha256=hashlib.sha256((ROOT/'server.py').read_bytes()).hexdigest(),
        relay_sha256=hashlib.sha256((ROOT/'tools/relay.py').read_bytes()).hexdigest()),indent=2)+'\n')
    print('PASS: shipped server.py, three real TCP clients, exact player count, room logs, input forwarding and disconnect')
if __name__=='__main__':asyncio.run(check())
