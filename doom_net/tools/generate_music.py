"""Convert the user's root d_e1m1.mid into a full 50 Hz PSG arrangement."""
import hashlib,json
from pathlib import Path
from import_midi import arrange
from lzss import compress
ROOT=Path(__file__).resolve().parent.parent

def generate():
    source=ROOT.parent/'d_e1m1.mid'
    if not source.exists():raise SystemExit('Music build requires the supplied d_e1m1.mid in the project/package root')
    data=source.read_bytes();score=arrange(data,lead_channel=1,bass_channel=2)
    raw=bytes(v for row in score['records'] for v in row);blob=compress(raw)
    out=['; E1M1 PSG arrangement from supplied d_e1m1.mid; 50 Hz variable durations.',
         f'MUSIC_RECORD_COUNT equ {len(score["records"])}',f'MUSIC_TOTAL_TICKS equ {sum(r[0] for r in score["records"])}',
         'music_data_start:','music_notes: dw '+','.join(map(str,score['dividers'])),'music_song:']
    out+=['db '+','.join(map(str,blob[i:i+24])) for i in range(0,len(blob),24)]
    out+=['music_song_end:','music_data_end:']
    (ROOT/'build/music.inc').write_text('\n'.join(out)+'\n')
    manifest={k:v for k,v in score.items() if k not in ('patterns','pattern_order','pattern_block_records','pattern_score_bytes')}
    manifest.update({'title':"At Doom's Gate / E1M1",'original_composition':False,
         'source_file':source.name,'source_sha256':hashlib.sha256(data).hexdigest(),
         'tick_hz':50,'loop_seconds':sum(row[0] for row in score['records'])/50,
         'total_ticks':sum(row[0] for row in score['records']),'voices':[1,2],
         'percussion':{'0':[0xe4,15],'1':[0xe2,7],'2':[0xe5,8],'3':[0xe4,12]},
         'codec':'LZSS 2048/34','compressed_bytes':len(blob),'decoded_bytes':len(raw),
         'history_address':0xa000,'history_bytes':2048,
         'data_bytes':len(score['dividers'])*2+len(blob)})
    (ROOT/'build/music.json').write_text(json.dumps(manifest,indent=2)+'\n')
