#!/usr/bin/env python3
"""Create a source/release ZIP for one verified Doom edition."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED,ZipFile

ROOT=Path(__file__).resolve().parent.parent
PROJECTS=('doom','doom_direct','doom_net')

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_text())

def package(name):
    project=ROOT/name
    try:
        build=read(project/'build/build.json')
        mzf=ROOT/build['file'];digest=sha(mzf)
        assert digest==build['sha256']
        assert mzf.read_bytes()[128:]==(project/'build/host.bin').read_bytes()
        assert read(project/'build/verification.json')['mzf_sha256']==digest
        if name!='doom':assert sha(ROOT/'d_e1m1.mid')==build['music_source_sha256']
        if name=='doom_net':
            net=read(project/'build/network_verification.json')
            assert net['mzf_sha256']==digest and net['exact_player_counts']==[2,3,4]
            for key in ('multiplayer_minimap_disabled','multiplayer_god_mode_disabled',
                        'transient_wait_preserves_frame','sustained_wait_single_warning',
                        'marines_uploaded_and_drones_restored'):assert net[key]
            assert read(project/'build/deathmatch_verification.json')['passed']
            assert read(project/'build/player_graphics_verification.json')['verified']
            for filename in ('relay_tcp_verification.json','server_verification.json'):
                report=read(project/'build'/filename)
                assert report['passed'] and report['relay_sha256']==sha(project/'tools/relay.py')
            assert read(project/'build/server_verification.json')['server_sha256']==sha(project/'server.py')
    except (OSError,KeyError,AssertionError) as exc:
        raise SystemExit(f'{name}: build/verification evidence is missing or stale. Run make -C {name} verify'
                         +(' and make -C doom_net verify-tcp.' if name=='doom_net' else '.')) from exc
    keyboard=ROOT/'common/key_table.bin'
    assert len(keyboard.read_bytes())==80
    assert sha(keyboard)=='9f49c16609b647548d0b89a093331e86eda7d9a9a2cbe13202f27fd93fbd1e51'
    release=dict(edition=name,file=mzf.name,mzf_sha256=digest,file_bytes=mzf.stat().st_size,
                 keyboard_sha256=sha(keyboard),arm_payload_sha256=sha(project/'build/unicard.bin'),
                 emulator_suite_passed=True,physical_mk3b_verification=False)
    if name=='doom_net':
        release.update(exact_player_counts=[2,3,4],multiplayer_minimap=False,multiplayer_god_mode=False,
                       actual_loopback_tcp_passed=True,real_server_entrypoint_three_tcp_clients_passed=True,
                       arm_bytes_used=build['memory_budget']['arm_total_allocated_bytes'])
    (project/'build/release.json').write_text(json.dumps(release,indent=2)+'\n')
    archive=ROOT/(mzf.stem+'.zip');prefix=mzf.stem+'/'
    files=[p for p in project.rglob('*') if p.is_file() and
           'build' not in p.relative_to(project).parts and '__pycache__' not in p.parts and
           p.suffix not in ('.o','.so','.pyc','.pyo','.log')]
    with ZipFile(archive,'w',ZIP_DEFLATED,compresslevel=9) as z:
        z.write(project/'README.txt',prefix+'README.txt')
        z.write(mzf,prefix+mzf.name)
        for relative in ('common/key_table.bin','requirements-dev.txt','.gitignore',
                         'tools/clean.py','tools/package.py'):
            z.write(ROOT/relative,prefix+relative)
        if name!='doom':z.write(ROOT/'d_e1m1.mid',prefix+'d_e1m1.mid')
        z.writestr(prefix+'release.json',json.dumps(release,indent=2)+'\n')
        for path in sorted(files):z.write(path,prefix+name+'/'+path.relative_to(project).as_posix())
    with ZipFile(archive) as z:
        assert z.testzip() is None and z.read(prefix+mzf.name)==mzf.read_bytes()
        assert not any('/build/' in p or '__pycache__' in p for p in z.namelist())
        assert [p for p in z.namelist() if p.endswith('.mzf')]==[prefix+mzf.name]
        print(json.dumps(dict(edition=name,mzf=mzf.name,zip=archive.name,bytes=archive.stat().st_size,
                              files=len(z.namelist())),indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('edition',choices=PROJECTS)
    package(parser.parse_args().edition)
