"""Original 16-colour packed textures, sprites and an expanded playable sector."""
from collections import deque
import json
from pathlib import Path
from lzss import compress
ROOT=Path(__file__).resolve().parent.parent
WIDTH,HEIGHT=32,24
OLD=[
 '1111111111111111','1000001000000001','1000001000004001','1000005000000001',
 '1000001000000001','1110111111101111','1000000000000001','1022200003330001',
 '1000000000000001','1000001000000001','1111011111110111','1000001000000001',
 '1000001000000001','1600005000000001','1000001000000001','1111111111111111']
world=[list('1'*WIDTH) if y in (0,HEIGHT-1) else list('1'+'0'*(WIDTH-2)+'1') for y in range(HEIGHT)]
for y,row in enumerate(OLD):world[y][:16]=row
for y in (3,8,13):world[y][15]='0'
for x in (3,12):world[15][x]='0'
for y in range(1,23):
    if y not in (3,12,20):world[y][23]='3'
for x in range(16,31):
    if x not in (19,27):world[9][x]='2'
for x in range(1,31):
    if x not in (3,12,19,27):world[17][x]='3'
for x,y in [(18,4),(19,4),(20,4),(26,14),(27,14),(28,14),(6,20),(7,20),(27,2),(29,2)]:world[y][x]='4' if x>16 else '2'
ROWS=[''.join(row) for row in world]
SPAWNS=[(10.5,8.5),(3.5,6.5),(11.5,2.5),(10.5,13.5),
        (19.5,6.5),(27.5,6.5),(19.5,20.5),(28.5,20.5)]
CORE=(28,3)
KEY=(9,6)
SECRET=(5,10)
alternate=[list('1'*WIDTH) for _ in range(HEIGHT)]
def carve(x1,y1,x2,y2):
    for y in range(y1,y2+1):
        for x in range(x1,x2+1):alternate[y][x]='0'
# Independent layout: arrival bay, armory, equipment room, central gallery,
# east reactor, southern cistern and southeast stores, joined by corridors.
for room in [(1,6,6,10),(1,1,5,4),(7,1,14,4),(8,5,12,8),
             (1,12,5,15),(7,11,13,15),(14,4,21,8),(25,1,30,6),
             (25,17,30,22),(16,16,21,22),(9,18,13,22)]:carve(*room)
for corridor in [(2,4,2,6),(10,4,10,5),(6,8,8,8),(12,6,15,6),
                 (19,3,26,3),(19,3,19,4),(27,6,27,17),
                 (17,8,18,16),(12,20,28,20),(11,15,11,20),
                 (11,8,11,12),(5,11,5,12)]:carve(*corridor)
for x,y in [(16,5),(16,6),(19,7),(17,18),(20,18),(27,19),(3,2)]:alternate[y][x]='1'
for y in range(1,23):
    for x in range(1,31):
        if alternate[y][x]=='1':alternate[y][x]='4' if x>=24 else '3' if 14<=x<=21 else '2'
alternate[3][6]=alternate[13][6]='5';alternate[13][1]='6';alternate[10][5]='2'
MAPS=[ROWS,[''.join(row) for row in alternate]]
GEOMETRY_DIFFERENCES=sum((a=='0')!=(b=='0') for ra,rb in zip(*MAPS) for a,b in zip(ra,rb))
assert GEOMETRY_DIFFERENCES>=200

def path(a,b,rows=ROWS):
    queue=deque([a]);prev={a:None}
    while queue:
        p=queue.popleft()
        if p==b:break
        for dx,dy in [(1,0),(0,-1),(-1,0),(0,1)]:
            q=(p[0]+dx,p[1]+dy)
            if q not in prev and 0<=q[0]<WIDTH and 0<=q[1]<HEIGHT and rows[q[1]][q[0]] in '05':
                prev[q]=p;queue.append(q)
    assert b in prev,(a,b)
    result=[];p=b
    while p is not None:result.append(p);p=prev[p]
    # Cell-centre waypoints prevent steering drift across long door corridors.
    result.reverse()
    return result

def packed(data):
    flat=[n for row in data for n in row]
    return [flat[i]|flat[i+1]<<4 for i in range(0,len(flat),2)]

def generate():
    assert len(ROWS)==HEIGHT and all(len(row)==WIDTH for row in ROWS)
    assert all(t=='1' for t in ROWS[0]+ROWS[-1]) and all(row[0]==row[-1]=='1' for row in ROWS)
    assert all(ROWS[int(y)][int(x)]=='0' for x,y in SPAWNS)
    assert ROWS[CORE[1]][CORE[0]]=='0'
    for x,y in [(3,8),CORE,(19,20),(2,13)]+[(int(x),int(y)) for x,y in SPAWNS]:path((3,8),(x,y))
    textures=[[[0]*32 for _ in range(32)] for _ in range(8)]
    for y in range(32):
        for x in range(32):
            n=((x*17+y*31)^(x*y*7))&15
            # Recessed floor plates, brass trim, cyan floor guidance lights.
            c=8 if x%16 in (0,15) or y%16 in (0,15) else (7 if n<3 else 8)
            if x%16==1 or y%16==1:c=0
            if x%16==2 and y%16==2:c=15
            if y in (7,8) and x<10:c=13 if x<7 else 9
            if x>25 and y in (24,25):c=6 if (x+y)&1 else 14
            textures[0][y][x]=c
            # Ceiling: ribbed alloy, illuminated conduit, inset vent.
            c=8 if y%8==0 else 0
            if y in (3,4):c=1 if y==3 else 9
            if 9<x<23 and 12<y<26:c=7 if y%3==0 else 8
            if x in (10,22) and 13<=y<=25:c=15
            textures[1][y][x]=c
            # Brushed metal bulkhead with bevel, bolts and status panel.
            c=0 if x in (0,31) or y in (0,31) else 8 if x in (1,30) or y in (1,30) else 7
            if x==2 or y==2:c=15
            if x==29 or y==29:c=8
            if 6<=x<=25 and 8<=y<=23:c=8 if x in (6,25) or y in (8,23) else (7 if n<12 else 15)
            if 9<=x<=22 and y in (12,16,20):c=0
            if x in (4,27) and y in (4,27):c=15 if (x+y)&1 else 0
            if x in (4,5) and 11<=y<=20:c=9 if y&1 else 1
            textures[2][y][x]=c
            # Oxidised red/brown brick, staggered seams and lit top edges.
            offset=8 if (y//8)&1 else 0;u=(x+offset)%16;v=y%8
            c=0 if v==0 or u==0 else 6 if v==1 else 2 if n<10 else 10 if n<13 else 8
            if u==1 and v>1:c=10
            textures[3][y][x]=c
            # Hazard machinery, recessed caution band and green diagnostics.
            c=15 if x==1 or y==1 else 8 if x in (0,31) or y in (0,31) else 7
            if 9<=y<=22:c=14 if ((x+y)//5)&1 else 0
            if y in (8,23):c=6
            if 4<=x<=27 and 3<=y<=6:c=0
            if y==4 and 5<=x<=24:c=[4,12,13,9,10][(x//4)%5]
            textures[4][y][x]=c
            # Blue reactor columns, cyan plasma with white lightning veins.
            c=8 if x%8 in (0,7) else 1 if x%8 in (1,6) else 9
            if 5<=y<=26 and x%8 in (2,3,4,5):c=15 if (x*3+y*5)%13<2 else 13 if n<11 else 5
            if y in (2,29):c=14 if x%4<2 else 0
            textures[5][y][x]=c
            # Sliding blast door, split centre, warning chevrons and lock.
            c=8 if x<16 else 7
            if y%4==0:c=0 if x<16 else 8
            if x in (0,31):c=15
            if x in (15,16):c=0
            if y in (2,3,28,29):c=14 if ((x+y)//4)&1 else 0
            if 22<=x<=27 and 12<=y<=20:c=0 if x in (22,27) or y in (12,20) else 12 if y<17 else 10
            textures[6][y][x]=c
            # Green exit panel with luminous arrow, metal surround and vents.
            c=8 if x<3 or x>28 or y<3 or y>28 else 4
            if 5<=x<=26 and 5<=y<=26:c=12 if (x+y)%7==0 else 4
            if (8<=x<=22 and y in (14,15,16,17)) or (18<=x<=23 and abs(y-16)<=23-x):c=15
            if x in (4,27) and y%4<2:c=0
            textures[7][y][x]=c
    # Tiny inset service/status strips use every RGBI palette entry. Other
    # material areas retain coherent palettes rather than random colour noise.
    for t in range(8):
        for c in range(16):textures[t][30 if t>1 else 30][8+c]=c
        assert set(n for row in textures[t] for n in row)==set(range(16))
    sprites=[[[0]*32 for _ in range(32)] for _ in range(6)]
    for y in range(32):
        for x in range(32):
            r=(x-16)**2+(y-12)**2;c=0
            if r<112:c=15 if x<12 and y<10 else 7 if x<20 else 8
            if 7<=x<=25 and 17<=y<=26:c=2 if x<12 else 10 if x<21 else 6
            if 4<=x<=7 and 14<=y<=24:c=8 if x<6 else 7
            if 25<=x<=28 and 14<=y<=24:c=7 if x<27 else 8
            if 9<=x<=23 and 10<=y<=14:c=0
            if 10<=x<=22 and y in (11,12):c=14 if x in (10,22) else 10
            if 12<=x<=20 and y in (19,20):c=9 if x&1 else 13
            if x in (11,12,21,22) and 27<=y<=30:c=15 if y==29 else 8
            sprites[0][y][x]=c
            r=(x-16)**2+(y-16)**2
            if r<105:sprites[1][y][x]=15 if r<18 else 13 if r<60 else 9
            if (x==16 or y==16) and r<200:sprites[1][y][x]=5
            if 7<=x<=25 and 10<=y<=25:
                sprites[2][y][x]=15 if 8<x<24 and 11<y<24 else 8
                if (14<=x<=18 and 13<=y<=22) or (10<=x<=22 and 16<=y<=19):sprites[2][y][x]=10
    # Two additional physical walk frames, plus an emissive blue key sprite.
    for index,shift in [(3,-2),(4,2)]:
        sprites[index]=[row[:] for row in sprites[0]]
        for y in range(26,32):
            sprites[index][y]=[0]*32
            for foot in (11+shift,21-shift):
                for x in range(foot,foot+3):sprites[index][y][x]=15 if y==29 else 8
        for x in range(10,23):sprites[index][12][x]=13 if index==3 else 14
    for y in range(32):
        for x in range(32):
            r=(x-11)**2+(y-12)**2
            if 10<r<38:sprites[5][y][x]=13 if x<12 else 9
            if 11<=x<=25 and y in (15,16,17):sprites[5][y][x]=13
            if x in (21,24) and 17<=y<=21:sprites[5][y][x]=9
    rgb=[tuple((85 if n&8 else 0)+(170 if n&bit else 0) for bit in [2,4,1]) for n in range(16)]
    shades=[]
    for gain in (.32,.55,.79,1.0):
        shades.append([min(range(16),key=lambda i:sum((rgb[i][k]-color[k]*gain)**2 for k in range(3))) for color in rgb])
    routes=[]
    for rows in MAPS:
        assert all(rows[int(y)][int(x)]=='0' for x,y in SPAWNS)
        goals=[(3,8),(5,9),KEY,(19,20),CORE,(3,3),(2,13)]
        route=[goals[0]]
        for a,b in zip(goals,goals[1:]):route+=path(a,b,rows)[1:]
        routes.append(route)
    art=[v for data in (textures,sprites) for item in data for v in packed(item)]
    art_blob=compress(art)
    map_blobs=[compress([int(n) for row in rows for n in row]) for rows in MAPS]
    directions={(1,0):0,(0,1):1,(-1,0):2,(0,-1):3}
    route_blobs=[]
    for route in routes:
        dirs=[directions[(b[0]-a[0],b[1]-a[1])] for a,b in zip(route,route[1:])]
        route_blobs.append([sum(dirs[j]<<((j-i)*2) for j in range(i,min(i+4,len(dirs)))) for i in range(0,len(dirs),4)])
    out=['/* Generated LZSS art/maps, packed 4bpp texels and 2-bit tour directions. */',
         f'#define MAP_W {WIDTH}\n#define MAP_H {HEIGHT}\n#define DRONE_COUNT {len(SPAWNS)}',
         f'#define CORE_X {CORE[0]+.5}f\n#define CORE_Y {CORE[1]+.5}f',
         '#define ART_BYTES '+str(len(art))]
    out.append('static const uint8_t art_blob[]={'+','.join(map(str,art_blob))+'};')
    for i,blob in enumerate(map_blobs):out.append(f'static const uint8_t map_blob{i}[]={{'+','.join(map(str,blob))+'};')
    out.append('static const uint8_t *const map_blobs[]={map_blob0,map_blob1};')
    out.append('static const float spawn[DRONE_COUNT][2]={'+','.join('{'+f'{x}f,{y}f'+'}' for x,y in SPAWNS)+'};')
    out.append('static const uint8_t light_table[4][16]={')
    out+=['{'+','.join(map(str,row))+'},' for row in shades];out.append('};')
    for i,blob in enumerate(route_blobs):out.append(f'static const uint8_t tour_route{i}[]={{'+','.join(map(str,blob))+'};')
    out.append('static const uint8_t *const tour_routes[]={tour_route0,tour_route1};')
    out.append('static const uint16_t tour_lengths[]={'+','.join(str(len(r)-1) for r in routes)+'};')
    (ROOT/'src/assets.h').write_text('\n'.join(out)+'\n')
    manifest={'map':ROWS,'width':WIDTH,'height':HEIGHT,'start':[3.5,8.5,0],'drones':SPAWNS,'core':[CORE[0]+.5,CORE[1]+.5],
              'exit':[2.5,13.5],'doors':[[6,3],[6,13]],'tour':routes[0],
              'maps':MAPS,'tours':routes,'key':[9.5,6.5],'secret':list(SECRET),
              'asset_raw_bytes':len(art),'asset_compressed_bytes':len(art_blob),
              'map_compressed_bytes':[len(b) for b in map_blobs],'drone_animation_frames':3,
              'geometry_different_cells':GEOMETRY_DIFFERENCES,'asset_codec':'LZSS 2048/34',
              'texture_size':32,'texture_colours':[sorted(set(n for row in t for n in row)) for t in textures],
              'textures':textures}
    (ROOT/'build/level.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest

if __name__=='__main__':
    (ROOT/'build').mkdir(exist_ok=True)
    print(json.dumps({k:v for k,v in generate().items() if k!='textures'},indent=2))
