#!/usr/bin/env python3
"""Optional native drone animation and approximate PSG effect audition WAV.
Run after verify.py creates native.so. These previews are not hardware captures.
"""
import ctypes as ct
import json
from pathlib import Path
import wave
import numpy as np
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parent.parent
n=ct.CDLL(str(ROOT/'build/native.so'))
n.native_frame.restype=ct.POINTER(ct.c_uint8)
n.native_cold();n.native_key(0,0)
palette=[]
for c in range(16):
    low,high=(85,255) if c&8 else (0,170)
    palette.extend([high if c&2 else low,high if c&4 else low,high if c&1 else low])
frames=[]
for tick in range(96):
    n.native_key(0,0)
    if tick%3:continue
    data=np.frombuffer(ct.string_at(n.native_frame(),32768),dtype=np.uint8).reshape(4,8192)[:,:8000]
    bits=np.unpackbits(data,axis=1,bitorder='little').reshape(4,200,320)
    pixels=np.sum(bits*np.array([1,2,4,8])[:,None,None],axis=0).astype(np.uint8)
    im=Image.fromarray(pixels,'P');im.putpalette(palette+[0]*(768-len(palette)))
    frames.append(im.resize((640,400),Image.Resampling.NEAREST))
frames[0].save(ROOT/'previews/drones.gif',save_all=True,append_images=frames[1:],duration=240,loop=0,optimize=False)
# Approximate tone and white noise from the same divider/attenuation envelopes
# sent by the Z80, with 0.2 seconds of silence between effects.
sounds=json.loads((ROOT/'build/sounds.json').read_text())
rate=22050;rng=np.random.default_rng(1234);audio=[];markers=[]
for name,sequence in sounds.items():
    markers.append({'effect':name,'seconds':sum(len(a) for a in audio)/rate})
    phase=0.0
    for lo,hi,tone,noise in sequence:
        divider=max(1,lo+(hi<<8));frequency=3546895/(32*divider)
        t=np.arange(rate//50)/rate
        wave_tone=np.where(np.mod(phase+t*frequency,1)<.5,1.0,-1.0)
        phase=(phase+len(t)*frequency/rate)%1
        gain=lambda a:0 if a>=15 else 10**(-a/10)
        audio.append((wave_tone*gain(tone)+rng.choice([-1.,1.],len(t))*gain(noise))*.35)
    audio.append(np.zeros(rate//5))
raw=np.clip(np.concatenate(audio)*32767,-32768,32767).astype('<i2').tobytes()
with wave.open(str(ROOT/'previews/sounds.wav'),'wb') as out:
    out.setnchannels(1);out.setsampwidth(2);out.setframerate(rate);out.writeframes(raw)
(ROOT/'previews/sounds.json').write_text(json.dumps(markers,indent=2)+'\n')
print('Wrote native drones.gif and approximate sounds.wav; not physical captures.')

# Audition one full loop using the actual byte stream verified from the Z80
# player. This approximates PSG waveforms; it is not a hardware recording.
song=json.loads((ROOT/'build/music.json').read_text())
trace=json.loads((ROOT/'build/music_psg_trace.json').read_text())['ticks']
count=song['total_ticks']
dividers=[1,1,1];volumes=[15]*4;phases=[0.0]*3;latched=0;noise_control=4
music=[]
for commands in trace[:count]:
    for value in commands:
        if value&128:
            latched=(value>>4)&7
            if latched==6:noise_control=value&7
            elif latched&1:volumes[latched//2]=value&15
            else:
                channel=latched//2;dividers[channel]=(dividers[channel]&0x3f0)|(value&15)
        elif latched<6 and not latched&1:
            channel=latched//2;dividers[channel]=(dividers[channel]&15)|((value&63)<<4)
    sample=np.zeros(rate//50);t=np.arange(len(sample))/rate
    for channel in range(3):
        frequency=3546895/(32*max(1,dividers[channel]))
        sample+=np.where(np.mod(phases[channel]+t*frequency,1)<.5,1.,-1.)*gain(volumes[channel])
        phases[channel]=(phases[channel]+len(t)*frequency/rate)%1
    shift_rate=3546895/(512*(1<<(noise_control&3)))
    indices=(t*shift_rate).astype(int)
    if noise_control&4:
        noise=rng.choice([-1.,1.],int(indices[-1])+1)[indices]
    else:noise=np.where(indices%15==0,1.,-1/14)
    sample+=noise*gain(volumes[3]);music.append(sample*.45)
raw=np.clip(np.concatenate(music)*32767,-32768,32767).astype('<i2').tobytes()
with wave.open(str(ROOT/'previews/music.wav'),'wb') as out:
    out.setnchannels(1);out.setsampwidth(2);out.setframerate(rate);out.writeframes(raw)
print('Wrote music.wav from verified PSG commands:',song['title'],song['loop_seconds'],'seconds.')

level=json.loads((ROOT/'build/level.json').read_text())
fontpath=Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
font=ImageFont.truetype(str(fontpath),19) if fontpath.exists() else ImageFont.load_default()
small=ImageFont.truetype(str(fontpath),14) if fontpath.exists() else ImageFont.load_default()
cell=20;pad=20;top=62;width=32*cell;height=24*cell
im=Image.new('RGB',(width*2+pad*3,height+top+100),'#0c1118');draw=ImageDraw.Draw(im)
for sector,rows in enumerate(level['maps']):
    ox=pad+sector*(width+pad)
    draw.text((ox,15),'SECTOR '+str(sector+1)+(' - original sector' if not sector else ' - new rooms and corridors'),font=font,fill='#e5edf5')
    for y,row in enumerate(rows):
        for x,tile in enumerate(row):
            color='#1c2834' if tile=='0' else '#318bbf' if tile=='5' else '#48bd89' if tile=='6' else '#647381'
            draw.rectangle((ox+x*cell,top+y*cell,ox+(x+1)*cell-2,top+(y+1)*cell-2),fill=color)
    for key,label,color in [('start','S','#fff1b5'),('key','K','#51dfff'),('core','C','#f277e9'),('exit','E','#91ffae')]:
        x,y=level[key][:2];cx=ox+int(x)*cell;cy=top+int(y)*cell
        draw.rectangle((cx+1,cy+1,cx+17,cy+17),fill='#061018',outline=color)
        draw.text((cx+4,cy-1),label,font=small,fill=color)
    draw.text((ox,top+height+12),'S start   K blue key   C core   E exit   Blue cells: doors',font=small,fill='#c0cfdf')
draw.text((pad,top+height+50),f'Geometry comparison ignores wall textures: {level["geometry_different_cells"]} floor/wall cells differ.',font=font,fill='#e5edf5')
im.save(ROOT/'previews/maps.png')
