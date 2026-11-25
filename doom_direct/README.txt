UniDoom Direct v0.6 — Firmware-published VGA buffer address
======================================================================

Load unidoom_direct_v0_6.mzf with your usual Sharp MZF loader.
The doom_direct/ source folder builds v0.6.

NEW FIRMWARE INTERFACE

The firmware author now publishes the framebuffer base as a 32-bit number
at flash address 0x08008228. This is the address of the pointer word, not
the pixel buffer itself. v0.6 reads that word on every ARM entry and accepts
only 0x10000000 <= base <= 0x10008000 (both endpoints included). At the upper
limit the complete 32768-byte plane allocation ends at 0x10010000.

The validated base is snapshotted for the whole frame and published in the
OpenCPU header at 0x20020004. The header starts at zero. On invalid metadata
ARM clears the header pointer/sound byte and returns before game setup,
simulation or framebuffer writes. The Z80 detects the zero result, disables
interrupts, mutes every sound channel and stops with a red border. There is
no fallback to the old hardcoded base. Firmware pointer changes are picked
up on the next frame.

Aligned buffers retain the fast 32-bit copy. Valid unaligned addresses use
a byte copy, so range validation does not impose an extra alignment
requirement on the new firmware. Padding and all memory outside the chosen
plane allocation stay untouched. Existing maps, music and game controls
are retained. Both DDQD and IDDQD work; IDDQ alone does not trigger early.

Explore two 32x24 sectors, recover the blue key and cyan data core, then
return to the green exit. The key opens the blue-locked western blast door
and is required at the exit. Press N after winning to enter the next sector,
or use 1/2 to select either sector directly. P plays through the current
sector, including its secret cache, combat, key, core and return route.

FEATURES

  - Two independent room layouts, with shared original 16-colour artwork
  - Eight patrolling drones, activated by line of sight, with reverse-grid
    navigation around walls and three physical sprite animation frames
  - A collectible blue key, locked door, and a hidden supply wall in each map
  - Secret rewards: 24 rounds and 20 health, capped at 99 ammo / 100 health;
    a secret can be opened and rewarded only once per sector visit
  - Pistol and three-pellet shotgun, hit sparks/blood, and 16 bounded particles
  - Animated reactor textures and emissive plasma/lights
  - Perspective textured floor/ceiling, partial lifting doors, clipped
    billboards, collision, hitscan, weapon effects, HUD and minimap
  - Full 95.38-second E1M1 PSG arrangement from the supplied d_e1m1.mid
    and eight PSG sound effects
  - DDQD god mode, ARM backbuffer, and direct UniCard VGA presentation

All assets are embedded; no WAD or external game files are needed. Maps
and artwork are LZSS-compressed in the uploaded image and unpacked into
ARM RAM. Art remains packed 4 bpp after decompression. Guided paths use two
bits per cell-to-cell step. This makes the additions fit the original
loader bound without overwriting firmware memory.

CONTROLS

  ARROWS / WASD   Walk forward/back; turn left/right
  Q / E           Strafe left/right
  SPACE           Fire; hold for repeated shots
  V               Switch pistol / shotgun
  F               Use a nearby door or secret wall
  M               Toggle minimap
  P               Start / stop guided play-through of the current sector
  B               Toggle music; enabling it restarts the loop
  L               Toggle light cone
  Z               Toggle running
  1 / 2           Select and restart sector 1 / 2
  N               Next sector after mission complete
  R / ESC         Restart the current sector
  DDQD            Toggle god mode; IDDQD also works

The shotgun costs two rounds and has an eight-frame cooldown; its three
pellets spread around the crosshair. The pistol costs one round and has a
four-frame cooldown. God mode restores 100 health and prevents damage;
ammo is still consumed. Reset/sector changes clear keys, secret rewards,
particles and god mode. Music continues independently of sector changes.
Movement takes over from the guided tour.

The blue key is at (9.5, 6.5), core at (28.5, 3.5), and exit at (2.5, 13.5).
The supply wall is tile (5,10): use F from an adjacent corridor.
Opening it also creates a shortcut. These placements are shared
between the two sectors; the surrounding materials and eastern/southern
room layouts differ. The blue lock is the door at tile (6,3).

Sector 2 is built independently from room and corridor carving: an arrival
bay, armory, equipment room, central gallery, eastern reactor, southern
cistern and southeast stores. Its walkable/nonwalkable mask differs in
264 cells from sector 1, regardless of wall materials. previews/maps.png
compares the geometry with identical neutral wall colours.

ARM FRAMEBUFFER AND MEMORY

The Sharp CPU performs no framebuffer transfers or VRAM reads/writes.
ARM renders into the former private framebuffer at 0x20028000, then copies
only the visible pixels into the base read from 0x08008228. This is an
ARM-to-ARM-memory copy; Sharp VRAM is bypassed entirely.

Let B be that validated base. VGA plane slots are:
  P1 / colour bit 0   B + 0000h .. B + 1FFFh
  P2 / colour bit 1   B + 2000h .. B + 3FFFh
  P3 / colour bit 2   B + 4000h .. B + 5FFFh
  P4 / colour bit 3   B + 6000h .. B + 7FFFh

The old 0x10001F80 address is now only a test fixture, not a production
constant or fallback. No framebuffer scan is needed with the new firmware.

Each slot has an 8192-byte stride. Exactly 8000 visible bytes per plane are
written: 200 rows of 40 bytes, leftmost pixel in the least significant bit.
The 192 padding bytes per plane remain untouched in both buffers. An ARM
DMB follows presentation before returning to firmware.

The backbuffer occupies 0x20028000..0x2002FFFF. The linker keeps code,
decoded assets, maps, game state and navigation below 0x20028000, and checks
the backbuffer remains inside the original 64 KB OpenCPU user window.

MZF file: 19034 bytes; loaded image: 18906 bytes at 3000h..79D9h.
Free under the current 8000h loader limit: 1574 bytes.
ARM code/assets/state: 31544 bytes; backbuffer: 32768 bytes.
Free before the backbuffer: 1224 bytes. See MEMORY.txt and build/memory.json.
The music decoder also uses ordinary Sharp RAM A000h..A7FFh for its 2 KB
history, outside the CPU VRAM window and away from the D000h stack top.

This requires the new firmware publication at 0x08008228 and the existing
planar layout. A firmware without a valid publication fails safely.
The backbuffer prevents the VGA buffer showing an intermediate clear and
rasterization, but the final visible copy can still overlap scanout; a
firmware-supported buffer swap/synchronization is needed for guaranteed
tear-free output. Physical Sharp/UniCard operation remains untested.

HARNESS, TIMING AND SOUND

The Z80 configures GDG mode/palette/scroll, uploads and verifies ARM once,
samples the full keyboard at 50 Hz, sends input and calls OpenCPU. It reads
one header-status byte and one sound-event byte per frame. No CEh
framebuffer-readback command is used.
The Sharp CPU VRAM window stays disabled. Load/execute remains 3000h.

The host starts frames after three 50 Hz interrupts: a target ceiling of
16.7 FPS, with lower rates if rendering is slower. Physics advances once
per rendered frame. The ceiling is higher than v0.4, so movement/gameplay
also advances faster when the renderer meets the new interval. This is
pacing, not a measured hardware frame rate.

OpenCPU header at 0x20020000:
  +00h   Thumb entry pointer
  +04h   Resolved live VGA base, zero until validated / on failure
  +08h   Key event
  +09h   Native initialization flag
  +0Ah   Held-button mask
  +0Bh   Sound-event mask

Held bits: 01 forward, 02 backward, 04 left, 08 right, 10 strafe left,
20 strafe right, 40 fire, 80 use. DDQD is recognized on Z80 key-down
transitions and delivered as event FEh, retaining the cheat during a busy
ARM call. Short taps are latched; simultaneous movement/actions work.

At Doom's Gate / E1M1 is converted from the user's d_e1m1.mid in the
workspace/package root. The complete supplied track is retained as a
95.38-second loop, with variable-duration events at 50 Hz. MIDI tempo is
resolved before quantization (per-event error at most 10 ms). The lead is
MIDI channel 2 and bass channel 3; channel 10 supplies percussion. Whole
voices are raised by 12/24 semitones to fit the PSG's low-frequency limit,
preserving octave jumps. Additional harmony voices and pitch-bend vibrato
are omitted in this two-tone-voice chip arrangement; MIDI instrument
samples are replaced by PSG tones/noise.

The 6648-byte event score compresses to 2561 bytes plus a 56-byte divider
table. The Z80 streams it through a 2 KB LZSS history in ordinary Sharp
RAM. Tone channels 1/2 carry the music; effects retain tone 0 and priority
over percussion on the noise channel. Playback runs at 50 Hz during ARM
rendering. B mutes music without muting effects and restarts the song when
re-enabled. Source hash, channel mapping, omissions and timing are recorded
in build/music.json. The supplied MIDI is included for reproducible builds.

Effects, lowest to highest priority: shot, hit, drone destruction, player
hurt, door, pickup/secret, victory and god mode. Envelopes finish muted;
PSG writes have recovery delays. Upload mismatch or ARM timeout disables
interrupts, silences every PSG channel and requests a red border.
The Sharp SN76489 is written on port F2h, as documented in section 4-6:
  https://www.idealine.info/sharpmz/mz-800/download/sm800.pdf

BUILD AND VERIFY

From the workspace/package root:
  python3 doom_direct/tools/build.py
  python3 doom_direct/tools/verify.py
  python3 doom_direct/tools/preview_extras.py

Workspace Makefile targets: make doom-direct / make verify-doom-direct.
Inside doom_direct/: make / make verify / make package / make clean.

Build requires Python 3, clang with ARM target, lld, llvm-objcopy, llvm-nm
and pasmo. UNIDOOM_LLD (or UNIDOOM_DIRECT_LLD) can select the linker.
The included ../common/key_table.bin supplies the keyboard mapping. The
root d_e1m1.mid supplies E1M1; it is required for music generation. Asset/music/sound
generation uses Python's standard library. Verification additionally needs
Unicorn 2.1+, numpy, Pillow and libz80ex1; UNIDOOM_Z80EX (or
UNIDOOM_DIRECT_Z80EX) can select the Z80 library. Python packages must be
installed in your selected environment.

The verifier checks the actual assembled Z80 and Cortex-M4 code:
  - 93 normal integrated frames with exact native C pixels/game-state matches
  - Firmware pointer bounds: both endpoints, alternate bases and unaligned bases
  - Zero, erased flash, pointer-slot address and out-of-range values rejected
  - Exactly one little-endian 32-bit flash read per ARM entry; flash unchanged
  - No initialization, simulation or framebuffer writes on invalid metadata
  - Next-frame relocation, stale-pointer rejection, and safe host shutdown
  - Backbuffer/live VGA equality; complete raster before the first VGA write
  - Exactly 32000 bytes presented, with both buffers' padding untouched
  - Code/state, backbuffer and CCM guards; no writes to unowned CCM
  - Zero Sharp VRAM access and no Z80 framebuffer copies
  - Exact moving-drone positions and decoded art between ARM and native C
  - Keys, locked doors, secret rewards, shotgun and sector changes via Z80
  - Held/multiple keys, fast DDQD, upload mismatch and busy timeout
  - 23 independently computed ray-depth views across both sectors
  - Partial-door sprite clipping, collision, blocked shots and god mode
  - Independent decompressed map/texture checks and 1536 BFS distances
  - A drone navigating around a wall; all drones collision-safe in both tours
  - Single secret reward, particle expiry and three distinct walk frames
  - Both complete guided tours: 957 and 1098 frames, with key, secret and core
  - All eight effects and two complete E1M1 loops: 9538 byte-verified ticks
  - Music streaming/history wraparound guards, tempo handling and source hash
  - Music mute/restart, held B, sound-effect priority and PSG recovery delays

Results/hashes: build/verification.json. Budget: build/memory.json.
These are CPU/protocol simulations; hardware and firmware timing still need
physical testing.

PREVIEWS AND SOURCE

previews/boot.png, door.png and sector2.png come from emulated Z80/ARM.
Other views and GIFs use the same renderer compiled natively. tour.gif and
tour2.gif are accelerated play-throughs; drones.gif has a stationary camera.
textures.png is the material atlas; shotgun.png, secret.png and god.png show
the corresponding features. RGBI levels approximate the physical display.

maps.png compares room geometry without texture differences.
music.wav is the full E1M1 PSG rendition synthesized from verified Z80 commands;
sounds.wav auditions all effects. They approximate chip waveforms and are
not recordings of physical hardware. sounds.json gives effect start times.

src/raycaster.c: renderer, simulation, navigation, controls and native hooks.
src/host.asm: Z80 upload/call/input, music, sound and frame pacing.
src/unicard.ld and unicard_header.S: memory bounds and ABI.
src/assets.h, font.h and sine.h: compressed assets, font and sine lookup.
tools/build.py: compilation, linked-symbol budget and MZF packaging.
tools/generate_assets.py, generate_music.py, generate_sounds.py: content.
tools/verify.py, verify_scene.py: CPU, bus, independent scene/game checks.
tools/preview_extras.py: optional native animation, map comparison and audio.
tools/profile_render.py: actual Cortex-M4 instruction counts for fixed views;
--video-address sets its emulated firmware publication (default test fixture).
tools/lzss.py: shared lossless art/map/music encoding and reference decoder.

RENDERER PERFORMANCE

The old path drew floor/ceiling across the entire scene and then covered it
with per-pixel walls. Enlarged walls repeated both shading and bitplane
read/modify/write operations. The optimized renderer traces first, chooses the visible opaque
surface per sample, packs four doubled samples into whole plane bytes, and
caches up to 96 shaded texture columns. Partial doors/sprites are overlaid
with their existing depth clipping. Only UI rows need an explicit clear.
The ray cache shares memory with the inactive navigation queue.

Measure the current renderer with:
  python3 doom_direct/tools/profile_render.py --output doom_direct/build/profile_current.json
These are Cortex-M4 instruction counts under Unicorn, not hardware FPS or
cycle measurements. The profiler excludes initialization and writes the
four sampled frame buffers into build/.

Generated build/ products and reports are ignored by Git. make clean removes
them and Python caches while preserving source, previews and root releases.
The shared ../tools/package.py packages verified source with the common
keyboard table, MIDI and tools; it excludes build products and other demos.

MIDI IMPORT TOOL

Builds automatically convert root d_e1m1.mid. The standalone importer stages
other supplied MIDI candidates without changing the game:
  python3 doom_direct/tools/import_midi.py your_track.mid --output doom_direct/build/imported_music.json
  python3 doom_direct/tools/test_import_midi.py

Optional --lead-channel / --bass-channel use numbers 1..16; channel 10 is
percussion. The importer handles SMF 0/1, tempo changes, sustain, repeated
attacks and whole-channel octave transposition. It reports pitch bends and
polyphony reduction. Nine synthetic checks cover parser/timing behavior.
A different song still needs its channel mapping and final memory fit
verified after adjusting generate_music.py.

Transport and the included keyboard mapping originate from
NOBOMI-SOFTWARE's UniFractal scaffold; the original executable is not needed.
