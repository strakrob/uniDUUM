"""Independent ray/occlusion checks, game rules, and native previews."""
import ctypes as ct
import json
import math
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
    level=json.loads((ROOT/'build/level.json').read_text())
    def reset():native.native_cold();native.native_key(0,0)
    # Full-image ray-depth checks against brute-force intersections of all
    # occupied map cells, including partially raised/fully open doors.
    cases=[(3.5,8.5,0,0),(3.5,8.5,130,0),(11.5,3.5,512,0),
           (7.8,3.5,512,0),(7.8,3.5,512,8),(7.8,3.5,512,16),
           (7.8,13.5,512,8),(12.5,4.5,730,0)]
    for px,py,angle,opening in cases:
        reset();native.native_set_pose(px,py,angle)
        for d in range(2):native.native_test_door(d,opening)
        native.native_render()
        dx,dy=qsin(angle+256),qsin(angle)
        expected=[];expected_doors=[[],[]]
        for col in range(160):
            camera=np.float32(np.float32(2*col+1)*np.float32(1/160)-np.float32(1))
            rx=float(np.float32(dx-np.float32(dy*camera)))
            ry=float(np.float32(dy+np.float32(dx*camera)))
            nearest=float('inf')
            for y,row in enumerate(level['map']):
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
    for i in range(4):native.native_test_drone(i,10.5,13.5,0)
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
    native.native_key(32,0);assert native.native_drone(0)==2 and native.native_state(2)==35
    native.native_test_door(0,16)
    for _ in range(8):native.native_key(0,64)
    assert native.native_drone(0)==0 and native.native_state(3)==1

    # The objective and return zone are reachable and reset cleanly.
    reset();native.native_set_pose(12.5,3.5,0);native.native_key(0,0)
    assert native.native_state(4)==1
    native.native_set_pose(2.5,13.5,0);native.native_key(0,0)
    assert native.native_state(6)==1
    native.native_key(ord('R'),0)
    assert native.native_state(4)==native.native_state(6)==0 and native.native_state(1)==100

    # Complete the actual guided tour without teleporting, checking collision
    # at every frame. Save a sped-up visual tour from the same renderer.
    reset();native.native_key(ord('P'),0)
    frames=[];contacts=[]
    for tick in range(700):
        native.native_key(0,0)
        assert native.native_can_stand(native.native_x(),native.native_y()),('Tour collision',tick)
        if tick%3==0:
            frames.append(image(ct.string_at(native.native_frame(),32768)).resize((640,400),Image.Resampling.NEAREST))
        if tick in [0,45,90,150,210,290]:contacts.append(image(ct.string_at(native.native_frame(),32768)).convert('RGB'))
        if native.native_state(6):break
        assert native.native_state(1)>0,'Guided tour died'
    assert native.native_state(6) and native.native_state(4) and native.native_state(19)==16,'Guided tour did not finish'
    frames[-1]=image(ct.string_at(native.native_frame(),32768)).resize((640,400),Image.Resampling.NEAREST)
    frames[0].save(ROOT/'previews/tour.gif',save_all=True,append_images=frames[1:],duration=110,loop=0,optimize=False)
    sheet=Image.new('RGB',(960,400))
    for i,im in enumerate(contacts):sheet.paste(im,((i%3)*320,(i//3)*200))
    sheet.resize((1440,600),Image.Resampling.NEAREST).save(ROOT/'previews/sector.png')

    # Explicit minimap and weapon flash screenshots.
    reset();native.native_key(ord('M'),0)
    image(ct.string_at(native.native_frame(),32768)).resize((960,600),Image.Resampling.NEAREST).save(ROOT/'previews/map.png')
    native.native_key(32,0)
    image(ct.string_at(native.native_frame(),32768)).resize((960,600),Image.Resampling.NEAREST).save(ROOT/'previews/fire.png')
    return {'independent_ray_cases':len(cases),'door_sprite_occlusion_checked':True,
            'radius_collision_checked':True,'hitscan_and_drone_destroy_checked':True,
            'objective_and_reset_checked':True,'guided_tour_frames':tick+1,
            'guided_tour_completes':True}
