"""Original procedural textures/sprites and a small playable sector."""
from collections import deque
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
ROWS=[
 '1111111111111111','1000001000000001','1000001000004001','1000005000000001',
 '1000001000000001','1110111111101111','1000000000000001','1022200003330001',
 '1000000000000001','1000001000000001','1111011111110111','1000001000000001',
 '1000001000000001','1600005000000001','1000001000000001','1111111111111111']
SPAWNS=[(10.5,8.5),(3.5,6.5),(11.5,2.5),(10.5,13.5)]

def path(a,b):
    queue=deque([a]);prev={a:None}
    while queue:
        p=queue.popleft()
        if p==b:break
        for dx,dy in [(1,0),(0,-1),(-1,0),(0,1)]:
            q=(p[0]+dx,p[1]+dy)
            if q not in prev and 0<=q[0]<16 and 0<=q[1]<16 and ROWS[q[1]][q[0]] in '05':
                prev[q]=p;queue.append(q)
    assert b in prev
    result=[];p=b
    while p is not None:result.append(p);p=prev[p]
    result.reverse()
    # Keep all corners; the tour only follows collision-safe cell centers.
    corners=[result[0]]
    for i in range(1,len(result)-1):
        if (result[i][0]-result[i-1][0],result[i][1]-result[i-1][1]) != (result[i+1][0]-result[i][0],result[i+1][1]-result[i][1]):
            corners.append(result[i])
    return corners+[result[-1]]

def generate():
    assert len(ROWS)==16 and all(len(row)==16 for row in ROWS)
    assert set(''.join(ROWS))<=set('0123456')
    assert all(ROWS[0][i]==ROWS[15][i]==ROWS[i][0]==ROWS[i][15]=='1' for i in range(16))
    assert [(x,y) for y,row in enumerate(ROWS) for x,t in enumerate(row) if t=='5']==[(6,3),(6,13)]
    assert all(ROWS[int(y)][int(x)]=='0' for x,y in SPAWNS)
    assert ROWS[3][12]=='0' and ROWS[13][2]=='0'
    textures=[[[0]*16 for _ in range(16)] for _ in range(8)]
    for y in range(16):
        for x in range(16):
            noise=((x*17+y*31)^(x*y*7))&7
            textures[0][y][x]=0 if x%8==0 or y%8==0 else (8 if noise<6 else 7)
            textures[1][y][x]=1 if y in [2,3] or (x==12 and y%4==0) else (8 if noise==0 else 0)
            metal=8 if x in [0,15] or y in [0,15] else (7 if noise<6 else 8)
            if x in [2,13] and y in [2,13]:metal=15
            if x in [7,8] and 4<=y<=11:metal=8
            textures[2][y][x]=metal
            mortar=y%4==0 or (x+(4 if (y//4)&1 else 0))%8==0
            textures[3][y][x]=8 if mortar else (2 if noise<5 else (10 if noise<7 else 6))
            tech=8 if x in [0,15] or y in [0,15] else 7
            if 4<=y<=11:tech=14 if ((x+y)//3)&1 else 0
            if y==2 and x>3:tech=13
            textures[4][y][x]=tech
            reactor=8 if x in [0,1,14,15] else (1 if x%4 else 9)
            if 4<=x<=11 and y not in [0,15]:reactor=13 if (x+y)%5 else 15
            textures[5][y][x]=reactor
            door=8 if x in [0,15] else (7 if x<7 else 8)
            if x in [7,8]:door=1
            if y in [1,14]:door=14 if x%4<2 else 0
            if 10<=x<=12 and 7<=y<=10:door=12 if x==11 else 4
            textures[6][y][x]=door
            exit_color=4 if 2<x<13 and 3<y<12 else 8
            if 6<=x<=10 and y in [5,6,9,10]:exit_color=15
            if x in [8,9] and y in [7,8]:exit_color=15
            textures[7][y][x]=exit_color
    sprites=[[[0]*32 for _ in range(32)] for _ in range(3)]
    for y in range(32):
        for x in range(32):
            col=0
            if (x-16)**2+(y-11)**2<87:col=8 if x<12 else 7
            if 8<=x<=24 and 17<=y<=26:col=2 if x<18 else 10
            if 5<=x<=8 and 17<=y<=24:col=8
            if 24<=x<=27 and 17<=y<=24:col=8
            if 10<=x<=13 and 10<=y<=13:col=10
            if 19<=x<=22 and 10<=y<=13:col=10
            if 11<=x<=21 and y in [26,27]:col=8
            if x in [11,12,21,22] and 28<=y<=30:col=7
            sprites[0][y][x]=col
            r=(x-16)**2+(y-16)**2
            if r<105:sprites[1][y][x]=15 if r<18 else (13 if r<60 else 9)
            if (x==16 or y==16) and r<200:sprites[1][y][x]=5
            if 7<=x<=25 and 10<=y<=25:
                sprites[2][y][x]=15 if 8<x<24 and 11<y<24 else 8
                if (14<=x<=18 and 13<=y<=22) or (10<=x<=22 and 16<=y<=19):sprites[2][y][x]=10
    # Nearest RGBI colours at four light levels, computed once at build time.
    rgb=[tuple((85 if n&8 else 0)+(170 if n&bit else 0) for bit in [2,4,1]) for n in range(16)]
    shades=[]
    for gain in [.28,.48,.73,1.0]:
        row=[]
        for color in rgb:
            target=tuple(v*gain for v in color)
            row.append(min(range(16),key=lambda i:sum((rgb[i][k]-target[k])**2 for k in range(3))))
        shades.append(row)
    route=path((3,8),(12,3))+path((12,3),(3,3))[1:]+path((3,3),(2,13))[1:]
    out=['/* Generated original assets: no external game data required. */']
    out.append('static const uint8_t world_map[16][16]={')
    out += ['{'+','.join(row)+'},' for row in ROWS];out.append('};')
    for name,data in [('textures',textures),('sprites',sprites)]:
        side=16 if name=='textures' else 32
        out.append(f'static const uint8_t {name}[{len(data)}][{side*side}]={{')
        for item in data:out.append('{'+','.join(str(n) for row in item for n in row)+'},')
        out.append('};')
    out.append('static const uint8_t light_table[4][16]={')
    out+=['{'+','.join(map(str,row))+'},' for row in shades];out.append('};')
    out.append(f'#define TOUR_POINTS {len(route)}')
    out.append('static const uint8_t tour_path[TOUR_POINTS][2]={'+','.join('{'+f'{x},{y}'+'}' for x,y in route)+'};')
    (ROOT/'src/assets.h').write_text('\n'.join(out)+'\n')
    manifest={'map':ROWS,'start':[3.5,8.5,0],'drones':SPAWNS,'core':[12.5,3.5],
              'exit':[2.5,13.5],'doors':[[6,3],[6,13]],'tour':route}
    (ROOT/'build/level.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest

if __name__=='__main__':
    (ROOT/'build').mkdir(exist_ok=True)
    print(json.dumps(generate(),indent=2))
