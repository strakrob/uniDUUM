#!/usr/bin/env python3
"""Analyze a supplied SMF MIDI and stage a 50 Hz two-voice PSG arrangement.

This does not replace the built-in music or rebuild an MZF. It reports the
score budget for other supplied songs. The game build separately imports
root d_e1m1.mid through generate_music.py and its streaming player.
SMF structure reference: https://museinfo.sapp.org/doc/formats/midifile/
Channel arguments use MIDI's user-facing numbers 1..16 (10 is percussion).
"""
import argparse
from collections import Counter, defaultdict
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import struct

class MidiError(ValueError):pass

def vlq(data,pos):
    value=0
    for _ in range(4):
        if pos>=len(data):raise MidiError('Truncated variable-length field')
        b=data[pos];pos+=1;value=(value<<7)|(b&127)
        if not b&128:return value,pos
    raise MidiError('Variable-length field exceeds four bytes')

def read_midi(data):
    if len(data)<14 or data[:4]!=b'MThd':raise MidiError('Expected a Standard MIDI File header')
    length=int.from_bytes(data[4:8],'big')
    if length<6 or 8+length>len(data):raise MidiError('Invalid MIDI header length')
    fmt,tracks,division=struct.unpack_from('>HHH',data,8)
    if fmt not in (0,1) or (fmt==0 and tracks!=1):raise MidiError('Only SMF formats 0 and 1 are supported')
    if not division or division&0x8000:raise MidiError('Expected metrical PPQN timing; SMPTE files need conversion')
    events=[];pos=8+length
    for track in range(tracks):
        if pos+8>len(data) or data[pos:pos+4]!=b'MTrk':raise MidiError('Missing MIDI track')
        size=int.from_bytes(data[pos+4:pos+8],'big');pos+=8
        end=pos+size
        if end>len(data):raise MidiError('Truncated MIDI track')
        buf=data[pos:end];pos=end;i=0;tick=0;running=None;serial=0
        while i<len(buf):
            delta,i=vlq(buf,i);tick+=delta
            if i>=len(buf):raise MidiError('Missing event status')
            status=buf[i]
            if status&128:i+=1
            elif running is None:raise MidiError('Running status without a channel message')
            else:status=running
            if status==0xff:
                running=None
                if i>=len(buf):raise MidiError('Missing meta-event type')
                kind=buf[i];i+=1;count,i=vlq(buf,i)
                if i+count>len(buf):raise MidiError('Truncated meta event')
                body=buf[i:i+count];i+=count
                if kind==0x51:
                    if count!=3 or not int.from_bytes(body,'big'):raise MidiError('Invalid tempo event')
                    events.append((tick,track,serial,'tempo',int.from_bytes(body,'big')))
                elif kind==0x2f:
                    if count:raise MidiError('Invalid end-of-track event')
                    events.append((tick,track,serial,'end',0));break
            elif status in (0xf0,0xf7):
                running=None;count,i=vlq(buf,i);i+=count
                if i>len(buf):raise MidiError('Truncated SysEx event')
            elif 0x80<=status<0xf0:
                running=status;count=1 if status>>4 in (12,13) else 2
                if i+count>len(buf) or any(b&128 for b in buf[i:i+count]):raise MidiError('Invalid channel data')
                events.append((tick,track,serial,status,list(buf[i:i+count])));i+=count
            else:raise MidiError(f'Unsupported system event {status:02X}')
            serial+=1
    events.sort(key=lambda e:e[:3])
    tempo=500000;previous=0;micros=Fraction(0);timed=[]
    for tick,track,serial,status,body in events:
        micros+=Fraction((tick-previous)*tempo,division);previous=tick
        timed.append((round(micros/20000),status,body))
        if status=='tempo':tempo=body
    return timed,{'format':fmt,'tracks':tracks,'ppqn':division,'seconds':float(micros/1000000)}

def arrange(data,lead_channel=None,bass_channel=None):
    events,info=read_midi(data)
    counts=Counter();programs={};program_events=defaultdict(Counter);pitch_min={}
    for _,status,body in events:
        if not isinstance(status,int):continue
        channel=status&15;kind=status>>4
        if kind==12:programs[channel]=body[0]
        if kind==9 and body[1] and channel!=9:
            counts[channel]+=1;program_events[channel][programs.get(channel,0)]+=1
            pitch_min[channel]=min(pitch_min.get(channel,127),body[0])
    if not counts:raise MidiError('No melodic note-on events')
    channels=sorted(counts,key=lambda c:(-counts[c],c))
    if bass_channel is None:
        bass_channel=next((c for c in channels if any(32<=p<=39 for p in program_events[c])),channels[-1])
    if lead_channel is None:lead_channel=next((c for c in channels if c!=bass_channel),bass_channel)
    if lead_channel==9 or bass_channel==9:raise MidiError('Channel 10 is reserved for percussion')
    ticks=max(1,max((e[0] for e in events),default=0))
    if ticks>45000:raise MidiError('Limit is fifteen minutes per staged score')
    by_frame=defaultdict(list)
    for frame,status,body in events:by_frame[frame].append((status,body))
    active=defaultdict(dict);pressed=defaultdict(set);pedal=defaultdict(bool)
    raw=[];note_set={0};warnings=Counter()
    transpose={}
    for channel in (lead_channel,bass_channel):
        shift=0
        while pitch_min.get(channel,45)+shift<45:shift+=12
        transpose[channel]=shift
    def psg_note(note,channel):
        # Transpose WHOLE voices: folding individual low notes would collapse
        # octave jumps in E1M1's riff and bass line.
        if note+transpose[channel]>127:warnings['notes_clipped_above_MIDI_range']+=1
        return min(127,note+transpose[channel])
    for frame in range(ticks):
        drum=0;retrigger=False
        for status,body in by_frame[frame]:
            if not isinstance(status,int):continue
            channel=status&15;kind=status>>4
            if kind==9 and body[1]:
                note,velocity=body
                if channel==9:
                    hit=1 if note in (35,36) else 2 if note in (38,40) else 3
                    if drum:warnings['simultaneous_drum_hits_reduced']+=1
                    if {0:0,3:1,1:2,2:3}[hit]>{0:0,3:1,1:2,2:3}[drum]:drum=hit
                else:
                    active[channel][note]=velocity;pressed[channel].add(note)
                    retrigger|=channel in (lead_channel,bass_channel)
            elif kind==8 or (kind==9 and not body[1]):
                note=body[0];pressed[channel].discard(note)
                if not pedal[channel]:active[channel].pop(note,None)
            elif kind==11:
                controller,value=body
                if controller==64:
                    pedal[channel]=value>=64
                    if not pedal[channel]:active[channel]={n:v for n,v in active[channel].items() if n in pressed[channel]}
                elif controller in (120,123):
                    pressed[channel].clear()
                    if controller==120 or not pedal[channel]:active[channel].clear()
            elif kind==14 and channel in (lead_channel,bass_channel) and body!=[0,64]:warnings['pitch_bend_events_not_rendered']+=1
        lead=psg_note(max(active[lead_channel]),lead_channel) if active[lead_channel] else 0
        bass=psg_note(min(active[bass_channel]),bass_channel) if active[bass_channel] else 0
        note_set.update((lead,bass));state=(lead,bass,drum)
        if raw and raw[-1][1:]==list(state) and raw[-1][0]<255 and not retrigger:raw[-1][0]+=1
        else:raw.append([1,*state])
    notes=sorted(note_set);indices={n:i for i,n in enumerate(notes)}
    dividers=[0 if not n else max(1,min(1023,round(3546895/(32*440*2**((n-69)/12))))) for n in notes]
    records=[[duration,indices[lead],indices[bass],drum] for duration,lead,bass,drum in raw]
    best=None
    for block_size in (4,8,16,32):
        patterns=[];lookup={};order=[]
        for i in range(0,len(records),block_size):
            block=tuple(tuple(r) for r in records[i:i+block_size])
            if block not in lookup:lookup[block]=len(patterns);patterns.append(block)
            order.append(lookup[block])
        if len(patterns)>255:continue
        # Include per-pattern pointers and a one-byte length before each block.
        size=len(dividers)*2+sum(len(p)*4+3 for p in patterns)+len(order)
        candidate=(size,block_size,patterns,order)
        if best is None or size<best[0]:best=candidate
    info.update({'lead_channel':lead_channel+1,'bass_channel':bass_channel+1,
                 'channel_note_counts':{str(c+1):counts[c] for c in channels},'tick_hz':50,
                 'quantization_max_error_ms':10,'arranged_seconds':ticks/50,'notes':notes,'dividers':dividers,
                 'records':records,'raw_score_bytes':len(notes)*2+len(records)*4,
                 'warnings':dict(warnings),'polyphony_reduced_to_two_voices':True,
                 'channel_transpose_semitones':{str(c+1):s for c,s in transpose.items()}})
    if best:
        size,block_size,patterns,order=best
        info.update({'pattern_block_records':block_size,'patterns':patterns,'pattern_order':order,
                     'pattern_score_bytes':size})
    return info

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('midi',type=Path);p.add_argument('--output',type=Path)
    for name in ('lead','bass'):p.add_argument('--'+name+'-channel',type=int,choices=range(1,17))
    args=p.parse_args();data=args.midi.read_bytes()
    report=arrange(data,None if args.lead_channel is None else args.lead_channel-1,
                   None if args.bass_channel is None else args.bass_channel-1)
    report['source_file']=args.midi.name;report['source_sha256']=hashlib.sha256(data).hexdigest()
    manifest=Path(__file__).resolve().parent.parent/'build/memory.json'
    if manifest.exists():
        budget=json.loads(manifest.read_text())
        current=json.loads(manifest.with_name('music.json').read_text())['data_bytes']
        report['score_budget_before_player_changes']=budget['z80_image_free_bytes']+current
    output=args.output or args.midi.with_suffix('.psg.json')
    output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('records','patterns','pattern_order','dividers')},indent=2))
    print('Staged:',output,'; current game unchanged. For another song, adjust generate_music.py and verify the final build.')

if __name__=='__main__':
    try:main()
    except (MidiError,OSError) as exc:raise SystemExit(str(exc))
