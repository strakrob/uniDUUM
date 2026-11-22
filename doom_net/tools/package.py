#!/usr/bin/env python3
"""Package only a built and verified UniDoom NET release."""
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
import hashlib
import json
import struct
ROOT=Path(__file__).resolve().parent.parent
PARENT=ROOT.parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda name:json.loads((ROOT/'build'/name).read_text())
build=read('build.json');mzf=PARENT/build['file'];digest=sha(mzf)
assert digest==build['sha256']
assert mzf.read_bytes()[128:]==(ROOT/'build/host.bin').read_bytes()
assert struct.unpack_from('<HHH',mzf.read_bytes(),18)==(len(mzf.read_bytes())-128,0x3000,0x3000)
assert read('verification.json')['mzf_sha256']==digest
net=read('network_verification.json');assert net['mzf_sha256']==digest and net['exact_player_counts']==[2,3,4]
assert net['transient_wait_preserves_frame'] and net['sustained_wait_single_warning'] and net['marines_uploaded_and_drones_restored']
assert read('deathmatch_verification.json')['passed'] and read('player_graphics_verification.json')['verified']
for name in ['relay_tcp_verification.json','server_verification.json']:
    report=read(name);assert report['passed'] and report['relay_sha256']==sha(ROOT/'tools/relay.py')
assert read('server_verification.json')['server_sha256']==sha(ROOT/'server.py')
assert sha(PARENT/'d_e1m1.mid')==build['music_source_sha256']
assert sha(PARENT/'unifractal_v0_2.mzf')=='2b1a31fcc5a37ed93ccf59aadb9ffd5c569f76df5a0267e90974edc097a9682c'
release=dict(project=build['project'],mzf_sha256=digest,arm_payload_sha256=sha(ROOT/'build/unicard.bin'),
             file_bytes=mzf.stat().st_size,network_build=build['multiplayer']['build_id'],
             emulator_suite_passed=True,actual_loopback_tcp_passed=True,
             real_server_entrypoint_three_tcp_clients_passed=True,
             physical_mk3b_verification=False,exact_player_counts=[2,3,4],
             marine_sprites=True,transient_wait_preserves_frame=True,
             sustained_wait_warning_after_ms=800,arm_bytes_used=build['memory_budget']['arm_total_allocated_bytes'],
             arm_allocation_bytes=65536)
(ROOT/'build/release.json').write_text(json.dumps(release,indent=2)+'\n')
version=mzf.stem;archive=PARENT/(version+'.zip');prefix=version+'/'
files=[p for p in ROOT.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.so','.o','.pyc','.log')]
with ZipFile(archive,'w',ZIP_DEFLATED,compresslevel=9) as z:
    z.write(ROOT/'README.txt',prefix+'README.txt')
    for name in [mzf.name,'unifractal_v0_2.mzf','d_e1m1.mid','requirements-dev.txt']:z.write(PARENT/name,prefix+name)
    for p in sorted(files):z.write(p,prefix+'doom_net/'+p.relative_to(ROOT).as_posix())
with ZipFile(archive) as z:
    assert z.testzip() is None and z.read(prefix+mzf.name)==mzf.read_bytes()
    print(json.dumps(dict(mzf=mzf.name,bytes=mzf.stat().st_size,sha256=digest,
                          zip=archive.name,zip_bytes=archive.stat().st_size,files=len(z.namelist())),indent=2))
