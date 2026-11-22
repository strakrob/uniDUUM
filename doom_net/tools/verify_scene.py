"""Independent ray/occlusion checks, game rules, and native previews."""
import ctypes as ct
import json
import math
from collections import deque
from pathlib import Path
import numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parent.parent

def qsin(angle):
    a=angle&1023;q=a>>8;i=a&255
    n=int(math.sin((256-i if q&1 else i)*math.pi/512)*32767+.5)
    return np.float32(-n if q&2 else n)*np.float32(1/32767)

def box_hit(px,py,rx,ry,x,y):
    """Ray versus a cell AABB, independent of the engine's grid-step DDA."""
    low,high=-float('inf'),float('inf')
    for p,r,a,b in [(px,rx,x,x+1),(py,ry,y,y+1)]:
        if abs(r)<1e-12:
            if p<a or p>b:return float('inf')
            continue
        t1,t2=(a-p)/r,(b-p)/r
        low=max(low,min(t1,t2));high=min(high,max(t1,t2))
    return max(0,low) if high>=max(0,low) else float('inf')

def check_scene(native,image,indices):
    native.native_door_depth.argtypes=[ct.c_int]
    native.native_door_depth.restype=ct.POINTER(ct.c_float)
    native.native_test_door.argtypes=[ct.c_int,ct.c_int]
    native.native_test_drone.argtypes=[ct.c_int,ct.c_float,ct.c_float,ct.c_int]
    native.native_flow.restype=ct.POINTER(ct.c_uint8)
    native.native_art.restype=ct.POINTER(ct.c_uint8)
    native.native_tick.argtypes=[ct.c_uint,ct.c_uint]
    level=json.loads((ROOT/'build/level.json').read_text())
    def reset():native.native_cold();native.native_key(0,0);native.native_ai(0)
    # Full-image ray-depth checks against brute-force intersections of all
    # occupied map cells, including partially raised/fully open doors.
    cases=[(3.5,8.5,0,0),(3.5,8.5,130,0),(11.5,3.5,512,0),
           (7.8,3.5,512,0),(7.8,3.5,512,8),(7.8,3.5,512,16),
           (7.8,13.5,512,8),(12.5,4.5,730,0),(19.5,20.5,0,0),
           (27.5,6.5,370,0),(28.5,3.5,512,0),(3.5,21.5,800,0)]
    ray_cases=[(s,*case) for s in range(2) for case in cases if level['maps'][s][int(case[1])][int(case[0])]=='0']
    for sector,px,py,angle,opening in ray_cases:
        reset()
        if sector:native.native_key(ord('2'),0);native.native_ai(0)
        native.native_set_pose(px,py,angle)
        for d in range(2):native.native_test_door(d,opening)
        native.native_render()
        dx,dy=qsin(angle+256),qsin(angle)
        expected=[];expected_doors=[[],[]]
        for col in range(160):
            camera=np.float32(np.float32(2*col+1)*np.float32(1/160)-np.float32(1))
            rx=float(np.float32(dx-np.float32(dy*camera)))
            ry=float(np.float32(dy+np.float32(dx*camera)))
            nearest=float('inf')
            for y,row in enumerate(level['maps'][sector]):
                for x,t in enumerate(row):
                    if t=='0' or (t=='5' and opening>0):continue
                    nearest=min(nearest,box_hit(px,py,rx,ry,x,y))
            expected.append(nearest)
            for d,(x,y) in enumerate(level['doors']):
                hit=box_hit(px,py,rx,ry,x,y)
                expected_doors[d].append(hit if 0<opening<16 and hit<nearest else 1000000)
        actual=np.ctypeslib.as_array(native.native_depth(),shape=(160,)).copy()
        assert np.allclose(actual,expected,rtol=2e-5,atol=5e-5),(px,py,angle,opening,'opaque depth')
        for d in range(2):
            actual=np.ctypeslib.as_array(native.native_door_depth(d),shape=(160,)).copy()
            assert np.allclose(actual,expected_doors[d],rtol=2e-5,atol=5e-5),('door depth',d,px,py,angle,opening)

    # A wall/closed door must hide a drone; an open door reveals it; a partly
    # raised door clips only its upper section. Compare fixed simulation time.
    reset();native.native_set_pose(7.8,3.5,512)
    for i in range(8):native.native_test_drone(i,10.5,13.5,0)
    native.native_test_drone(0,5.5,3.5,2)
    native.native_render();hidden_alive=indices(ct.string_at(native.native_frame(),32768)).copy()
    native.native_test_drone(0,5.5,3.5,0);native.native_render()
    hidden_dead=indices(ct.string_at(native.native_frame(),32768)).copy()
    assert np.array_equal(hidden_alive,hidden_dead),'Drone leaked through closed door'
    native.native_test_door(0,16);native.native_test_drone(0,5.5,3.5,2);native.native_render()
    visible_alive=indices(ct.string_at(native.native_frame(),32768)).copy()
    native.native_test_drone(0,5.5,3.5,0);native.native_render()
    visible_dead=indices(ct.string_at(native.native_frame(),32768)).copy()
    assert np.sum(visible_alive[8:125]!=visible_dead[8:125])>30,'Open door did not reveal drone'
    native.native_test_door(0,8);native.native_test_drone(0,5.5,3.5,2);native.native_render()
    partial_alive=indices(ct.string_at(native.native_frame(),32768)).copy()
    native.native_test_drone(0,5.5,3.5,0);native.native_render()
    partial_dead=indices(ct.string_at(native.native_frame(),32768)).copy()
    assert np.array_equal(partial_alive[8:89],partial_dead[8:89]),'Door upper clipping failed'
    assert np.sum(partial_alive[89:125]!=partial_dead[89:125])>10,'Door lower gap hides sprite'

    # Radius collision, axis sliding and closed/open passage.
    reset()
    for x,y in [(.5,.5),(3.5,7.5),(6.5,3.5),(7.1,3.5)]:assert not native.native_can_stand(x,y)
    assert native.native_can_stand(7.3,3.5)
    native.native_test_door(0,8);assert not native.native_can_stand(6.5,3.5)
    native.native_test_door(0,16);assert native.native_can_stand(6.5,3.5)
    native.native_set_pose(3.5,8.5,768)
    for _ in range(25):native.native_key(0,1)
    assert native.native_y()>=8.21-1e-5,'Walked into brick pillar'
    assert native.native_can_stand(native.native_x(),native.native_y())

    # Hitscan cannot pass a closed door, and two unoccluded shots destroy a drone.
    reset();native.native_set_pose(7.8,3.5,512);native.native_test_drone(0,5.5,3.5,2)
    native.native_key(32,0);assert native.native_drone(0)==2 and native.native_state(2)==71
    native.native_test_door(0,16)
    for _ in range(8):native.native_key(0,64)
    assert native.native_drone(0)==0 and native.native_state(3)==1

    # The objective and return zone are reachable and reset cleanly.
    reset();native.native_set_pose(*level['core'],0);native.native_key(0,0)
    assert native.native_state(4)==1
    native.native_set_pose(2.5,13.5,0);native.native_key(0,0)
    assert native.native_state(6)==0,'Exit ignored missing key'
    native.native_set_pose(*level['key'],0);native.native_key(0,0)
    assert native.native_state(28)==1
    native.native_set_pose(2.5,13.5,0);native.native_key(0,0)
    assert native.native_state(6)==1
    native.native_key(ord('R'),0)
    assert native.native_state(4)==native.native_state(6)==0 and native.native_state(1)==100

    # Complete the actual guided tour without teleporting, checking collision
    # at every frame. Save a sped-up visual tour from the same renderer.
    tour_ticks=[]
    for sector in range(2):
        reset()
        if sector:native.native_key(ord('2'),0)
        native.native_key(ord('P'),0)
        frames=[];contacts=[]
        for tick in range(2400):
            native.native_key(0,0)
            assert native.native_can_stand(native.native_x(),native.native_y()),('Tour collision',sector,tick)
            for i in range(8):assert native.native_can_stand(native.native_drone_x(i),native.native_drone_y(i)),('Tour drone collision',sector,tick,i)
            if tick%8==0:frames.append(image(ct.string_at(native.native_frame(),32768)).resize((640,400),Image.Resampling.NEAREST))
            if tick in [0,140,280,420,560,700]:contacts.append(image(ct.string_at(native.native_frame(),32768)).resize((320,200),Image.Resampling.NEAREST).convert('RGB'))
            if native.native_state(6):break
            assert native.native_state(1)>0,('Guided tour died',sector,tick)
        assert native.native_state(6) and native.native_state(4) and native.native_state(28),('Guided tour did not finish',sector,tick,native.native_x(),native.native_y(),native.native_state(15))
        assert native.native_state(29),'Guided tour missed secret'
        tour_ticks.append(tick+1)
        frames[-1]=image(ct.string_at(native.native_frame(),32768)).resize((640,400),Image.Resampling.NEAREST)
        frames[0].save(ROOT/('previews/tour.gif' if not sector else 'previews/tour2.gif'),save_all=True,append_images=frames[1:],duration=110,loop=0,optimize=False)
    sheet=Image.new('RGB',(960,400))
    for i,im in enumerate(contacts):sheet.paste(im,((i%3)*320,(i//3)*200))
    sheet.resize((1440,600),Image.Resampling.NEAREST).save(ROOT/'previews/sector.png')

    # Explicit minimap and weapon flash screenshots.
    reset();native.native_key(ord('M'),0)
    image(ct.string_at(native.native_frame(),32768)).resize((960,600),Image.Resampling.NEAREST).save(ROOT/'previews/map.png')
    native.native_key(32,0)
    image(ct.string_at(native.native_frame(),32768)).resize((960,600),Image.Resampling.NEAREST).save(ROOT/'previews/fire.png')

    # Patrol and chase positions must change while remaining collision-safe.
    reset();native.native_ai(1)
    before=[(native.native_drone_x(i),native.native_drone_y(i)) for i in range(8)]
    for _ in range(100):
        native.native_key(0,0)
        for i in range(8):assert native.native_can_stand(native.native_drone_x(i),native.native_drone_y(i)),('Drone in wall',i)
    after=[(native.native_drone_x(i),native.native_drone_y(i)) for i in range(8)]
    assert all(a!=b for a,b in zip(before,after)),'A drone never moved'
    reset()
    for i in range(8):native.native_test_drone(i,10.5,13.5,0)
    native.native_test_drone(0,5.5,8.5,2)
    for _ in range(48):native.native_key(0,0)
    assert native.native_state(1)<100,'Enemy attack did not damage player'
    for key in 'IDDQ':native.native_key(ord(key),0)
    assert native.native_state(23)==0,'IDDQ triggered before the final D'
    native.native_key(ord('D'),0)
    assert native.native_state(23)==1 and native.native_state(1)==100
    for _ in range(120):native.native_key(0,0)
    assert native.native_state(1)==100,'God mode still takes damage'
    image(ct.string_at(native.native_frame(),32768)).save(ROOT/'previews/god.png')
    for key in 'DDQD':native.native_key(ord(key),0)
    assert native.native_state(23)==0
    for _ in range(48):native.native_key(0,0)
    assert native.native_state(1)<100,'Turning god mode off did not restore damage'

    # Independently validate the decompressed maps and reverse BFS distances.
    for sector in range(2):
        reset();native.native_key(ord('1')+sector,0);native.native_ai(0)
        assert [[native.native_tile(x,y) for x in range(32)] for y in range(24)]==[[int(c) for c in row] for row in level['maps'][sector]]
        expected=[255]*768;start=(int(native.native_x()),int(native.native_y()));queue=deque([start]);expected[start[1]*32+start[0]]=0
        while queue:
            x,y=queue.popleft()
            for dx,dy in [(0,1),(-1,0),(0,-1),(1,0)]:
                xx,yy=x+dx,y+dy
                if not (0<=xx<32 and 0<=yy<24) or native.native_tile(xx,yy)!=0:continue
                j=yy*32+xx
                if expected[j]==255:expected[j]=expected[y*32+x]+1;queue.append((xx,yy))
        actual=list(ct.string_at(native.native_flow(),768));assert actual==expected,('BFS distance mismatch',sector)
    # An alerted drone must go around the brick obstruction, not through it.
    reset()
    for i in range(8):native.native_test_drone(i,10.5,13.5,0)
    native.native_test_drone(0,3.5,6.5,2);native.native_alert(0);native.native_ai(1)
    for _ in range(160):
        native.native_tick(0,0)
        assert native.native_can_stand(native.native_drone_x(0),native.native_drone_y(0))
    assert (native.native_drone_x(0)-3.5)**2+(native.native_drone_y(0)-8.5)**2<1.5**2,'Drone did not navigate around wall'

    # Key, lock, secret rewards, sector progression and their reset behavior.
    reset();native.native_set_pose(7.8,3.5,512);native.native_key(ord('F'),0)
    assert native.native_state(21)==0 and native.native_state(30)==2
    native.native_set_pose(*level['key'],0);native.native_key(0,0)
    native.native_set_pose(7.8,3.5,512);native.native_key(ord('F'),0)
    assert native.native_state(21)==1
    native.native_set_pose(5.5,9.5,256);old_ammo=native.native_state(2);native.native_key(ord('F'),0)
    assert native.native_state(29)==1 and native.native_tile(5,10)==0 and native.native_state(2)==min(99,old_ammo+24)
    native.native_key(ord('F'),0);assert native.native_state(2)==min(99,old_ammo+24),'Secret reward repeated'
    image(ct.string_at(native.native_frame(),32768)).save(ROOT/'previews/secret.png')
    native.native_key(ord('2'),0);assert native.native_state(27)==1 and not native.native_state(28) and not native.native_state(29)
    native.native_key(ord('R'),0);assert native.native_state(27)==1

    # Shotgun pellets, ammo cost, particle lifetime and physical sprite frames.
    reset()
    for i in range(8):native.native_test_drone(i,10.5,13.5,0)
    native.native_test_drone(0,5.5,8.5,2);native.native_key(ord('V'),0);native.native_key(32,0)
    assert native.native_drone(0)==0 and native.native_state(2)==70 and native.native_state(34)==1
    assert 0<native.native_particles()<=16
    image(ct.string_at(native.native_frame(),32768)).save(ROOT/'previews/shotgun.png')
    for _ in range(12):native.native_tick(0,0)
    assert native.native_particles()==0
    data=ct.string_at(native.native_art(),level['asset_raw_bytes'])
    assert len({data[i*512:(i+1)*512] for i in (8,11,12)})==3,'Drone walk frames are identical'
    expected=[]
    for texture in level['textures']:
        flat=[v for row in texture for v in row];expected.extend(flat[i]|flat[i+1]<<4 for i in range(0,1024,2))
    assert data[:4096]==bytes(expected),'Decoded texture pixels differ from source art'

    # Decode an atlas from the exact packed material data checked at generation.
    atlas=Image.new('P',(32*4,40*2));atlas.putpalette(image(ct.string_at(native.native_frame(),32768)).getpalette())
    for i,texture in enumerate(level['textures']):
        assert set(n for row in texture for n in row)==set(range(16))
        tile=Image.fromarray(np.array(texture,dtype=np.uint8),'P');tile.putpalette(atlas.getpalette())
        atlas.paste(tile,((i%4)*32,(i//4)*40))
    atlas.resize((768,480),Image.Resampling.NEAREST).save(ROOT/'previews/textures.png')
    changed=sum((a=='0')!=(b=='0') for r1,r2 in zip(*level['maps']) for a,b in zip(r1,r2))
    assert changed>=200,'Sector two differs mostly in wall materials'
    return {'independent_ray_cases':len(ray_cases),'door_sprite_occlusion_checked':True,
            'radius_collision_checked':True,'hitscan_and_drone_destroy_checked':True,
            'objective_and_reset_checked':True,'guided_tour_frames':tour_ticks,
            'guided_tour_completes':True,'all_eight_drones_move_without_wall_penetration':True,
            'god_mode_invulnerability_and_toggle_off_checked':True,'all_16_colours_per_texture_checked':True,
            'map_dimensions':[level['width'],level['height']],'decoded_maps_independently_checked':2,
            'navigation_distance_cells_independently_checked':1536,'drone_routes_around_wall':True,
            'key_lock_secret_rewards_and_sector_reset_checked':True,'shotgun_and_particle_lifetimes_checked':True,
            'three_distinct_drone_frames_checked':True,'decoded_textures_independently_checked':True,
            'sector_walkability_cells_different':changed}
