"""50 Hz SN76489 tone/noise envelopes. Four bytes per tick, no blocking waits."""
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent

def generate():
    # Frequency (Hz), tone attenuation (0=loud, 15=mute), noise attenuation.
    specs={
      'shot':[(700-i*65,5+i,2+i*2) for i in range(6)],
      'hit':[(1000,3,7),(600,5,9),(350,8,12),(180,11,14)],
      'kill':[(520-i*35,5+i//2,3+i) for i in range(12)],
      'hurt':[(140,5,5),(90,7,7),(140,6,9),(80,9,11),(65,12,13)],
      'door':[(90+(i%4)*12,10,10+i//4) for i in range(16)],
      'pickup':[(f,5+i//4,15) for i,f in enumerate([440]*3+[554]*3+[659]*3+[880]*4)],
      'win':[(f,4+i//5,15) for i,f in enumerate([523]*4+[659]*4+[784]*4+[1047]*8)],
      'god':[(f,5,15) for f in [330]*3+[440]*3+[660]*3+[880]*3],
    }
    out=['; Generated PSG effects: count, then divider low/high, tone/noise attenuation.',
         'sfx_table: dw '+','.join('sfx_'+name for name in specs)]
    import json
    manifest={}
    for name,notes in specs.items():
        frames=[]
        for frequency,tone,noise in notes:
            divider=max(1,min(1023,round(3546895/(32*frequency))))
            frames.append([divider&255,divider>>8,min(15,tone),min(15,noise)])
        frames.append([0,0,15,15])
        out.append('sfx_'+name+': db '+str(len(frames)))
        out+=['db '+','.join(map(str,frame)) for frame in frames]
        manifest[name]=frames
    (ROOT/'build/sfx.inc').write_text('\n'.join(out)+'\n')
    (ROOT/'build/sounds.json').write_text(json.dumps(manifest,indent=2)+'\n')
