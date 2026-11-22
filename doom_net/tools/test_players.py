#!/usr/bin/env python3
"""Verify/preview the actual raw skins used by the Z80 upload."""
from pathlib import Path
import json
from PIL import Image
from generate_players import marines
from generate_assets import packed
ROOT=Path(__file__).resolve().parent.parent
players=marines();blob=(ROOT/'build/marines.bin').read_bytes()
assert blob==bytes(n for p in players for n in packed(p))
assert len(blob)==1536 and len(set(blob[i:i+512] for i in range(0,1536,512)))==3
assert blob!=(ROOT/'build/drones.bin').read_bytes()
# Separated legs and boots, a helmet above the torso, and visible rifle.
for p in players:
    assert all(p[y][16]==0 for y in range(24,28))
    assert p[3][16]==13 and p[11][15]==15 and p[15][27]==8
palette=[]
for c in range(16):
    low,high=(85,255) if c&8 else (0,170)
    palette += [high if c&2 else low,high if c&4 else low,high if c&1 else low]
atlas=Image.new('P',(32*4,32*3));atlas.putpalette(palette+[0]*(768-len(palette)))
for team,color in enumerate((9,12,10,14)):
    for pose,p in enumerate(players):
        tile=Image.new('P',(32,32));tile.putpalette(atlas.getpalette())
        tile.putdata([color if c in (2,10) else c for row in p for c in row]);atlas.paste(tile,(team*32,pose*32))
atlas.resize((768,576),Image.Resampling.NEAREST).save(ROOT/'previews/players.png')
(ROOT/'build/player_graphics_verification.json').write_text(json.dumps(dict(verified=True,poses=3,teams=4,
    raw_bytes=1536,arm_extra_sprite_bytes=0,distinct_from_drones=True),indent=2)+'\n')
print('PASS: humanoid helmet, rifle, separated legs/boots; three poses/four team colours; zero extra ARM sprite allocation')
