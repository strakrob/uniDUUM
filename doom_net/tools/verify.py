from emulation import *

pointer_report=verify_firmware_video_pointer()
verify_short_taps()

def verify_audio_sequences():
    """Exercise the actual Z80 event selection and every PSG envelope byte."""
    m=Machine();m.run_until(symbols['upload']);m.next_interrupt=1<<60
    m.memory[symbols['music_enabled']]=0
    sounds=json.loads((ROOT/'build/sounds.json').read_text())
    for index,(name,frames) in enumerate(sounds.items()):
        m.arm.u.mem_write(0x2002000b,bytes([1<<index]))
        z.z80ex_set_reg(m.cpu,11,0xcf00)
        struct.pack_into('<H',m.memory,0xcf00,symbols['frame_done'])
        z.z80ex_set_reg(m.cpu,10,symbols['sound_fetch'])
        start=len(m.psg_stream);m.run_until(symbols['frame_done'])
        for _ in frames:
            assert z.z80ex_int(m.cpu)
            m.run_until(symbols['frame_done'])
        expected=[0xe4]
        for lo,hi,tone,noise in frames:
            divider=lo+(hi<<8)
            expected.extend([0x80|(divider&15),(divider>>4)&63,0x90|tone,0xf0|noise])
        assert [v for _,v in m.psg_stream[start:]]==expected,name
        assert m.memory[symbols['sound_left']]==0 and expected[-2:]==[0x9f,0xff]
    # Multiple events select the highest-priority bit, not a random effect.
    m.arm.u.mem_write(0x2002000b,b'\xff')
    z.z80ex_set_reg(m.cpu,11,0xcf00)
    struct.pack_into('<H',m.memory,0xcf00,symbols['frame_done'])
    z.z80ex_set_reg(m.cpu,10,symbols['sound_fetch']);m.run_until(symbols['frame_done'])
    assert struct.unpack_from('<H',m.memory,symbols['sound_ptr'])[0]==symbols['sfx_god']+1
    gaps=[b[0]-a[0] for a,b in zip(m.psg_stream,m.psg_stream[1:])]
    assert min(gaps)>=32,'PSG writes lack required recovery delay'
    m.close()
    return len(sounds)

audio_effects=verify_audio_sequences()

def verify_music():
    """Compare two full Z80-played loops, muting, and percussion arbitration."""
    m=Machine();m.run_until(symbols['upload']);m.next_interrupt=1<<60
    song=json.loads((ROOT/'build/music.json').read_text())
    trace=[];durations=[]
    def irq():
        start=len(m.psg_stream);cycles=m.cycles
        accepted=z.z80ex_int(m.cpu);assert accepted
        m.cycles+=accepted;m.run_until(symbols['upload'])
        durations.append(m.cycles-cycles)
        return [value for _,value in m.psg_stream[start:]]
    def voice(note,latch,attenuation,phase):
        if not note:return [latch|0x1f]
        divider=song['dividers'][note]
        return [latch|(divider&15),(divider>>4)&63,latch|0x10|(attenuation+min(4,phase))]
    expanded=[(lead,bass,drum,phase,duration) for duration,lead,bass,drum in song['records'] for phase in range(duration)]
    loop_ticks=len(expanded)
    assert loop_ticks==song['total_ticks']
    import hashlib
    assert hashlib.sha256((ROOT.parent/'d_e1m1.mid').read_bytes()).hexdigest()==song['source_sha256']
    m.memory[0x9ff0:0xa000]=b'\xa5'*16;m.memory[0xa800:0xa810]=b'\xa5'*16
    for tick in range(loop_ticks*2):
        lead,bass,drum,phase,duration=expanded[tick%loop_ticks]
        command,attenuation=song['percussion'][str(drum)]
        expected=voice(lead,0xa0,7,phase)+voice(bass,0xc0,5,phase)
        expected += [command,0xf0|min(15,attenuation+2*phase)]
        actual=irq()
        assert actual==expected,('Music bytes differ',tick,actual,expected)
        trace.append(actual)
        assert m.memory[symbols['music_phase']]==(phase+1)%duration
        if tick%1000==0:print(f'E1M1 PSG tick {tick+1}/{loop_ticks*2} verified',flush=True)
    assert trace[:loop_ticks]==trace[loop_ticks:],'Music loop is not deterministic'
    assert m.memory[0x9ff0:0xa000]==m.memory[0xa800:0xa810]==b'\xa5'*16,'Music decoder history overflow'
    # B is acted on at key-down, including while ARM rendering is busy.
    m.keys=[ord('B')];irq();assert m.memory[symbols['music_enabled']]==0
    phase=m.memory[symbols['music_phase']];pointer=bytes(m.memory[symbols['music_ptr']:symbols['music_ptr']+2])
    assert irq()==[],'Holding B retriggered the toggle'
    m.keys=[];assert irq()==[]
    assert phase==m.memory[symbols['music_phase']] and pointer==bytes(m.memory[symbols['music_ptr']:symbols['music_ptr']+2])
    m.keys=[ord('B')];assert irq()==[];assert m.memory[symbols['music_enabled']]==1
    m.keys=[];assert irq()==trace[0],'Music did not restart cleanly'
    # A shot overlays the two music voices and owns noise until its last tick.
    m.arm.u.mem_write(0x2002000b,b'\x01')
    z.z80ex_set_reg(m.cpu,11,0xcf00);struct.pack_into('<H',m.memory,0xcf00,symbols['upload'])
    z.z80ex_set_reg(m.cpu,10,symbols['sound_fetch']);m.run_until(symbols['upload'])
    frames=json.loads((ROOT/'build/sounds.json').read_text())['shot']
    for index,(lo,hi,tone,noise) in enumerate(frames):
        actual=irq();divider=lo+(hi<<8)
        assert actual[:4]==[0x80|(divider&15),(divider>>4)&63,0x90|tone,0xf0|noise]
        commands=[b for b in actual[4:] if 0xe0<=b<0xf0]
        assert bool(commands)==(index==len(frames)-1),'Music stole SFX noise or failed to restore percussion'
        assert any(0xb0<=b<=0xbf for b in actual[4:]) and any(0xd0<=b<=0xdf for b in actual[4:])
    assert max(durations)<70000,'Music/keyboard ISR exceeds one modeled 50 Hz interval'
    assert min(b[0]-a[0] for a,b in zip(m.psg_stream,m.psg_stream[1:]))>=32
    (ROOT/'build/music_psg_trace.json').write_text(json.dumps({'tick_hz':50,'ticks':trace},separators=(',',':'))+'\n')
    m.close()
    return {'music_loops_byte_verified':2,'music_ticks_verified':len(trace),
            'music_mute_restart_and_held_key_checked':True,'music_sfx_noise_priority_checked':True,
            'music_source_sha256':song['source_sha256'],'music_seconds':song['loop_seconds'],
            'music_history_wrap_and_guards_checked':True,
            'max_music_keyboard_irq_tstates':max(durations)}

music_report=verify_music()
machine=Machine()
cases=[('boot',0),('walk1',ord('W')),('walk2',ord('W')),
       ('turn_walk',[ord('W'),ord('D')]),('turn',ord('D')),('release',0),
       ('fire1',32),('fire2',32),('fire3',32),('fire4',32),('fire5',32),('fire_release',0),
       ('map',ord('M')),('map_hold',ord('M')),('map_release',0),('light',ord('L')),
       ('run',ord('Z')),('reset',ord('R')),('strafe_l',ord('Q')),('strafe_r',ord('E')),
       ('use_far',ord('F')),('release2',0),('tour',ord('P')),('tour2',0),('tour3',0),
       ('manual',ord('W')),('reset2',ord('R')),('combo',[ord('W'),32,ord('F')]),
       ('release3',0),('escape',27),
       ('cheat_d1',ord('D')),('cheat_release1',0),('cheat_d2',ord('D')),('cheat_release2',0),
       ('cheat_q',ord('Q')),('cheat_release3',0),('cheat_on',ord('D')),('cheat_release4',0),
       ('off_d1',ord('D')),('off_release1',0),('off_d2',ord('D')),('off_release2',0),
       ('off_q',ord('Q')),('off_release3',0),('cheat_off',ord('D')),('off_release4',0),
       ('music_off',ord('B')),('music_release',0),('music_on',ord('B')),('music_release2',0),
       ('sector2',ord('2')),('sector2_walk',ord('W')),('sector1',ord('1')),
       ('shotgun',ord('V')),('shotgun_fire',32),('pistol',ord('V'))]
observed={}
for i,(name,keys) in enumerate(cases):
    data=machine.frame(keys);observed[name]=machine.arm.calls[-1]
    observed[name]['music_enabled']=machine.memory[symbols['music_enabled']]
    if name=='boot':image(data).resize((960,600),Image.Resampling.NEAREST).save('previews/boot.png')
    if i%8==0:print(f'Z80/ARM control frame {i+1}/{len(cases)} verified',flush=True)
assert observed['walk1']['buttons']==observed['walk2']['buttons']==1
assert observed['walk1']['x']>observed['boot']['x'] and observed['walk2']['x']>observed['walk1']['x']
assert observed['turn_walk']['buttons']==9 and observed['turn_walk']['state'][0]>0
assert observed['turn_walk']['x']>observed['walk2']['x']
assert observed['release']['buttons']==0
assert observed['fire1']['state'][2]==71 and observed['fire5']['state'][2]==70
assert observed['map']['state'][11]==observed['map_hold']['state'][11]==1
assert observed['light']['state'][12]==0 and observed['run']['state'][13]==1
assert observed['reset']['sha256']==observed['boot']['sha256']
assert abs(observed['strafe_r']['y']-8.5)<1e-5
assert observed['tour']['state'][14]==1 and observed['tour3']['x']>observed['tour']['x']
assert observed['manual']['state'][14]==0
assert observed['combo']['buttons']==(1|64|128)
assert observed['escape']['sha256']==observed['boot']['sha256']
assert observed['cheat_on']['god']==1 and observed['cheat_on']['sound']&128
assert observed['cheat_off']['god']==0 and observed['cheat_off']['sound']&128
assert observed['walk2']['drones']!=observed['boot']['drones']
assert observed['music_off']['music_enabled']==observed['music_release']['music_enabled']==0
assert observed['music_on']['music_enabled']==1
assert observed['sector2']['sector']==1 and observed['sector1']['sector']==0
assert observed['shotgun']['weapon']==1 and observed['shotgun_fire']['state'][2]==70
assert observed['pistol']['weapon']==0

def fixture_pose(x,y,angle):
    for name,value in [('player_x',x),('player_y',y)]:machine.arm.u.mem_write(arm_symbols[name],struct.pack('<f',value))
    machine.arm.u.mem_write(arm_symbols['angle'],struct.pack('<I',angle))
    native.native_set_pose(x,y,angle)

# Locked door is denied before collecting the key, then opens normally.
fixture_pose(7.8,3.5,512)
machine.frame(ord('F'))
assert machine.arm.calls[-1]['state'][21]==0 and not machine.arm.calls[-1]['blue_key']
fixture_pose(9.5,6.5,0);machine.frame(0)
assert machine.arm.calls[-1]['blue_key']==1

# Inspect an actual lifting door through the Z80/ARM path at every stage.
for name,value in [('player_x',7.8),('player_y',3.5)]:
    machine.arm.u.mem_write(arm_symbols[name],struct.pack('<f',value))
machine.arm.u.mem_write(arm_symbols['angle'],struct.pack('<I',512))
machine.arm.u.mem_write(arm_symbols['auto_mode'],struct.pack('<I',0))
native.native_set_pose(7.8,3.5,512)
machine.arm.u.mem_write(arm_symbols['ai_on'],(0).to_bytes(arm_sizes['ai_on'],'little'))
native.native_ai(0)
machine.frame(0)
assert machine.arm.calls[-1]['state'][19]==0
machine.frame(ord('F'))
assert machine.arm.calls[-1]['state'][21]==1
for i in range(18):
    data=machine.frame(0)
    if i==7:image(data).resize((960,600),Image.Resampling.NEAREST).save('previews/door.png')
assert machine.arm.calls[-1]['state'][19]==16
for _ in range(8):machine.frame(ord('W'))
assert machine.arm.calls[-1]['x']<6.5,'Could not walk through open doorway'
machine.frame(ord('F'));machine.frame(0)
assert machine.arm.calls[-1]['state'][19]==16 and machine.arm.calls[-1]['state'][21]==1,'Door crushed player'
fixture_pose(5.5,9.5,256);machine.frame(ord('F'))
assert machine.arm.calls[-1]['secret']==1
fixture_pose(*level['core'],0);machine.frame(0)
fixture_pose(*level['exit'],0);machine.frame(0)
assert machine.arm.calls[-1]['state'][6]==1
machine.frame(ord('N'));assert machine.arm.calls[-1]['sector']==1 and not machine.arm.calls[-1]['blue_key']
image(machine.frame(ord('M'))).resize((960,600),Image.Resampling.NEAREST).save('previews/sector2.png')
calls=machine.arm.calls
assert machine.uploads==len(payload)+26*len(calls)
frame_intervals=[b[0]-a[0] for a,b in zip(machine.frame_starts,machine.frame_starts[1:])]
machine.close()

bad=Machine(corrupt=True)
bad.run_until(symbols['failed']);bad.run_until(symbols['failure_loop'])
assert bad.border==10 and not bad.arm.calls
assert [v for _,v in bad.psg_stream[-4:]]==[0x9f,0xbf,0xdf,0xff] and not z.z80ex_int(bad.cpu)
bad.close()
timeout=Machine()
timeout.run_until(symbols['wait_native']);timeout.busy=2
z.z80ex_set_reg(timeout.cpu,2,1)
timeout.run_until(symbols['failed']);timeout.close()

from verify_scene import check_scene
report={'host_arm_frames':len(calls),'exact_native_comparison':True,
        'simultaneous_keys_checked':True,'held_movement_and_autofire_checked':True,
        'door_opening_and_safe_closing_checked':True,'short_taps_and_irq_registers_checked':True,
        'upload_failure_checked':True,'busy_timeout_checked':True,
        'framebuffer':'runtime from 0x08008228','default_fixture_framebuffer':hex(fb),'direct_framebuffer_bytes':32768,
        'framebuffer_readback_bytes_per_frame':0,'blocks_per_frame':0,
        'sharp_vram_reads':machine.vram_reads,'sharp_vram_writes':machine.vram_writes,
        'ccm_outside_framebuffer_unchanged':True,'arm_backbuffer':hex(0x20028000),
        'render_complete_before_present_checked':True,'present_bytes_per_frame':32000,
        'compressed_art_arm_native_exact':True,'keys_secrets_sectors_and_shotgun_through_z80':True,
        'three_vblank_frame_pacing_checked':True,
        'sound_effects_byte_verified':audio_effects,'sound_event_arm_native_comparison':True,
        'moving_drone_positions_exactly_compared':8,'ddqd_toggle_through_z80_keyboard':True,
        'visible_plane_bytes':8000,'all_plane_padding_unchanged':True,
        'emulated_z80_tstates_between_frames':[min(frame_intervals),max(frame_intervals)],
        'mzf_sha256':hashlib.sha256(mzf).hexdigest(),'calls':calls}
report.update(check_scene(native,image,indices))
report.update(music_report)
report['firmware_video_pointer']=pointer_report
(ROOT/'build/verification.json').write_text(json.dumps(report,indent=2)+'\n')
print('PASS: ARM backbuffer -> CCM, zero Sharp VRAM access/readback, compressed assets, sectors, gameplay, music and sound.')

