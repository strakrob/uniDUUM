#!/usr/bin/env python3
"""Native combat fixtures; ARM/native equality is checked by test_network.py."""
from emulation import *
from skin_helpers import native_skins

native.native_net.argtypes=[ct.c_uint,ct.c_uint,ct.c_uint,ct.POINTER(ct.c_uint8)]
native.native_peers.restype=ct.c_void_p
native.native_net_pose.argtypes=[ct.c_int,ct.c_float,ct.c_float,ct.c_int]
native.native_net_health.argtypes=[ct.c_int,ct.c_int]
class Player(ct.Structure):
    _fields_=[('x',ct.c_float),('y',ct.c_float)]+[(name,ct.c_int16) for name in
        ['angle','health','ammo','fire_timer','cooldown','hurt_timer','walk_phase','weapon','running','use_down','score','respawn','shield']]
assert ct.sizeof(Player)*4==arm_sizes['peers']
clock=0

def step(keys=None,mask=3):
    global clock
    controls=bytes(keys or bytes(8))
    native.native_net(0,mask,clock,(ct.c_uint8*8).from_buffer_copy(controls));clock+=1
    return (Player*4).from_address(native.native_peers())
def setup(mask=3):
    global clock
    clock=0;native.native_cold();step(mask=mask);native_skins(native,ROOT)
    native.native_net_pose(0,3.5,8.5,0);native.native_net_pose(1,5.5,8.5,512)

def main():
    # Carry both single-player assists into the network lobby: neither may survive.
    native.native_cold();native.native_key(0,0)
    native.native_key(ord('M'),0);native.native_key(254,0)
    assert native.native_state(11)==native.native_state(23)==1
    net=(ct.c_uint8*24).in_dll(native,'network');net[0]=1
    native.native_key(0,0)
    assert all(native.native_state(i)==0 for i in (11,23,24,25)),'Lobby inherited single-player assists'
    # M, DDQD and the latched FEh cheat event must also do nothing in a match.
    setup();native.native_key(0,0)
    before=ct.string_at(native.native_frame(),32768)
    for key in [ord('M'),254,*map(ord,'IDDQD')]:
        native.native_key(key,0)
        assert native.native_state(11)==native.native_state(23)==0
        assert ct.string_at(native.native_frame(),32768)==before,'Multiplayer assist changed the image'
    # A remote cheat attempt must not prevent ordinary lethal damage.
    native.native_net_health(1,100)
    for _ in range(13):p=step([ord('M'),64,254,0,0,0,0,0])
    assert p[1].health==0 and p[0].score==1,'Remote god-mode attempt blocked damage'
    # Leaving the match restores the availability of both single-player features.
    net[0]=0;native.native_key(0,0)
    native.native_key(ord('M'),0);native.native_key(254,0)
    assert native.native_state(11)==native.native_state(23)==1
    setup();p=step([0,64,0,0,0,0,0,0]);assert p[1].health==100 and p[0].shield==0,'Spawn shield failed'
    setup();native.native_net_health(1,100)
    for i in range(13):p=step([0,64,0,0,0,0,0,0])
    assert p[1].health==0 and p[0].score==1 and p[0].ammo==68 and p[1].respawn==30
    for _ in range(30):p=step()
    assert p[1].health==100 and p[1].shield==30 and p[1].score==0 and p[1].ammo==72
    setup();native.native_net_pose(0,3.5,8.5,768);native.native_net_pose(1,3.5,6.5,256);native.native_net_health(1,100)
    p=step([0,64,0,0,0,0,0,0]);assert p[1].health==100,'Shots penetrated solid wall'
    setup();native.native_net_health(1,100)
    p=step([ord('V'),64,0,0,0,0,0,0]);assert p[0].weapon==1 and p[0].ammo==70 and p[1].health==25
    for _ in range(8):p=step([0,64,0,0,0,0,0,0])
    assert p[1].health==0 and p[0].score==1 and p[0].ammo==68
    setup();p=step([254,0,ord('R'),0,0,0,0,0]);assert native.native_state(23)==0 and native.native_state(7)>1,'Multiplayer cheat/reset restrictions failed'
    setup(mask=15);step([ord('N'),0,0,0,0,0,0,0],mask=15)
    assert native.native_state(27)==1
    p=(Player*4).from_address(native.native_peers())
    assert len({(v.x,v.y) for v in p})==4
    for v in p:assert native.native_can_stand(v.x,v.y)
    step([ord('R'),0,0,0,0,0,0,0],mask=15);assert native.native_state(27)==1
    setup();
    for kill in range(10):
        native.native_net_pose(0,3.5,8.5,0);native.native_net_pose(1,5.5,8.5,512);native.native_net_health(1,25)
        for _ in range(4):step()
        p=step([0,64,0,0,0,0,0,0]);assert p[0].score==kill+1
    assert native.native_state(6)==1,'Ten-frag victory failed'
    step([ord('R'),0,0,0,0,0,0,0]);assert native.native_state(6)==0
    p=(Player*4).from_address(native.native_peers());assert p[0].score==p[1].score==0
    # A visible, unoccluded opponent, from the exact native renderer.
    native.native_net_pose(0,3.5,8.5,0);native.native_net_pose(1,5.5,8.5,512);step()
    image(ct.string_at(native.native_frame(),32768)).resize((960,600),Image.Resampling.NEAREST).save('previews/opponent.png')
    checks=['spawn protection','wall occlusion','pistol/shotgun damage and ammo','frags','respawn',
            'four valid distinct spawns in both sectors','ten-frag victory','host rematch/map control','multiplayer cheats disabled','multiplayer minimap disabled',
            'lobby clears inherited assists','single-player map/god mode retained']
    (ROOT/'build/deathmatch_verification.json').write_text(json.dumps(dict(checks=checks,passed=True),indent=2)+'\n')
    print('PASS: '+', '.join(checks))
if __name__=='__main__':main()
