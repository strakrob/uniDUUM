"""Original 32x32 humanoid marine sprites, stored in Sharp RAM, not ARM BSS.

Eight RGBI shades, a helmet/visor, shoulder armour, hands, rifle and two
separate booted legs. Three walk poses reuse the existing 0/3/4 sprite slots.
Colours 2 and 10 are the existing team-colour channels in the renderer.
"""
from pathlib import Path
from generate_assets import packed
from lzss import decompress

def marines():
    frames=[]
    for pose in (0,-1,1):
        pic=[[0]*32 for _ in range(32)]
        def box(x,y,w,h,c):
            for yy in range(y,y+h):
                for xx in range(x,x+w):
                    if 0<=xx<32 and 0<=yy<32:pic[yy][xx]=c
        # Boots and legs are drawn first; the torso overlaps their upper ends.
        for x,shift in [(10,pose),(18,-pose)]:
            box(x+shift,20,5,10,8);box(x+shift+1,22,3,6,2)
            box(x+shift-1,29-(1 if shift>0 else 0),7,3,8)
            box(x+shift,30-(1 if shift>0 else 0),5,1,7)
        box(8,9,16,12,2);box(10,10,12,9,10);box(11,11,10,2,15)
        box(5,10,5,5,8);box(6,10,4,3,10)
        box(23,10,5,5,8);box(23,10,4,3,10)
        box(6,14,4,7,2);box(23,14,4,6,2)
        box(7,19,4,3,14);box(22,18,4,3,14)
        box(10,20,13,3,8);box(14,20,5,2,7)
        # Neck, angular helmet, narrow luminous visor and chin guard.
        box(13,7,7,3,6);box(11,2,11,6,8);box(13,1,7,2,7)
        box(12,3,9,2,9);box(13,3,7,1,13);box(12,6,9,2,7)
        box(15,6,4,1,8)
        # Rifle lies diagonally across the chest; metal outline avoids holes.
        box(12,15,14,3,8);box(11,16,7,3,7);box(15,16,10,1,15)
        box(24,14,5,2,8);box(14,18,3,4,8);box(18,17,3,3,6)
        frames.append(pic)
    assert len({bytes(packed(p)) for p in frames})==3
    return frames

def generate(root,art_blob):
    root=Path(root)
    players=marines();(root/'build/marines.bin').write_bytes(bytes(v for p in players for v in packed(p)))
    # Preserve the exact original drone frames for the return to single-player.
    art=decompress(art_blob,7168)
    (root/'build/drones.bin').write_bytes(b''.join(art[4096+i*512:4096+(i+1)*512] for i in (0,3,4)))
    assert (root/'build/marines.bin').stat().st_size==(root/'build/drones.bin').stat().st_size==1536
    return players
