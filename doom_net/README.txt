UniDoom NET v0.3 — UniCard Ethernet mk3b deathmatch
================================================

Separate project based on UniDoom Direct v0.6. Load unidoom_net_v0_3.mzf.
The existing doom_direct project and its MZF are preserved.

2–4 Sharp MZ-800 machines play deathmatch, one player per machine. First to
10 frags wins. Players have separate positions, health, ammo, weapon and
scores. Opponents use original humanoid marine sprites with helmets, rifles,
armour, separate legs and boots. Three poses animate in blue/green/red/yellow
for P1/P2/P3/P4. These are distinct from the single-player drones. Walls and lifting doors block visibility and shots. Death
causes an automatic respawn after 30 simulation frames, with 30 frames of
protection; firing ends protection. Pistol hits do 25 damage; the shotgun
fires three hits. There is no friendly/enemy drone AI in deathmatch.

The complete previous single-player game remains available, including both
maps, moving drones, secrets, weapons, E1M1 music and DDQD. The minimap,
god mode, cheats and the automatic tour are disabled during deathmatch. Entering any network lobby
also clears an active single-player minimap or god mode. The M key and
DDQD/IDDQD cannot enable these features in a match. Players can pass through
each other; collision against the level geometry remains active.

HARDWARE AND RELAY SETUP

Each machine needs a UniCard mk3b with Ethernet and firmware implementing:
  * The existing OpenCPU commands CAh..CDh.
  * The 32-bit VGA pointer published at 08008228h, as in Direct v0.6.
  * BomberNet's NET commands A0h..A9h, advertised by INFO (95h), feature
    byte 3, bit 08h. Ethernet hardware alone is insufficient.

The firmware repository supplied by the user documents the common NET
contract for MZPico. BomberNet's protocol document also describes the STM32
UniCard Ethernet implementation, emu_NET.c, and its TCP configuration.
This program uses that shared card API; it does not add/flash firmware.

1. On a PC on the same LAN, with Python 3.10 or newer:

     python3 doom_net/server.py

   Or run doom_net/start_server.sh on Linux/macOS, or double-click
   doom_net/start_server.cmd on Windows with the Python launcher installed.
   From inside doom_net, make server also starts it.

   The server listens on all LAN interfaces, TCP 8766, without pip packages
   or internet services. It prints connection, room, player-count, ready,
   start, disconnect and desync events. Leave it running while playing.

   Options: --bind <interface IP> --port <TCP port>. Use --bind 127.0.0.1
   only for clients on the same PC. Ctrl+C stops the server. A bind error
   explains when another server already owns the port.

   This is the same TCP JSON-lines transport used by BomberNet's local
   relay for UniCard. It also accepts the game-independent BomberNet API;
   different game IDs remain in separate rooms. WebSocket/browser play is
   outside this UniCard build. BomberNet's reference relay can also host
   these rooms when its TCP listener is enabled with RELAY_TCP_HOST=0.0.0.0.

2. In each UniCard's /unicard/network.cfg, set NETRELAYADDR to that PC's
   LAN IPv4 address and NETRELAYPORT to 8766, using the firmware's normal
   configuration syntax. Apply/reload the network configuration as required
   by that firmware. Both cards must reach the same PC and port.

   Use the PC's LAN address, not 127.0.0.1. The public mzpico.com relay is
   WebSocket-only; UniCard Ethernet's documented transport is TCP JSON lines.

3. Load the identical unidoom_net_v0_3.mzf on every machine.

4. One player presses H. The Sharp now asks HOW MANY PLAYERS? 2 / 3 / 4.
   Press the exact count, including the host. Only then is a room created
   with that many slots. Give the displayed four-letter code to the others.

   Each other player presses J and types the code (BACKSPACE corrects a
   letter). JOINED / NEEDED displays the current and selected counts.
   Joiners press SPACE when ready. The host presses SPACE last. Play cannot
   start until the exact selected count has joined and everybody is ready.
   If the count was wrong, ESC leaves; H opens a new count selection.

5. ESC leaves a room or match and returns to single-player. If any player
   leaves, loses the connection or desynchronizes, the remaining machines
   stop the match and show an error; ESC exits. Create a new room to restart.

If INFO does not advertise NET, the program shows UNICARD NET FIRMWARE
REQUIRED. It remains usable offline. No firmware upgrade is bundled.

KEYS

  WASD / cursor keys    Move and turn
  Q / E                Strafe
  SPACE                Fire; in lobby, ready
  F                    Use a door / secret
  V                    Pistol / shotgun
  Z                    Walk / run
  M                    Minimap in single-player only (disabled online)
  L                    Local flashlight
  B                    Local music on/off
  H / J                Host / join from single-player
  ESC                  Leave / cancel
  R                    Host: rematch, preserving the selected map
  N                    Host: switch between the two different maps

Offline-only controls: M minimap, R reset, 1/2 select sector, P guided tour,
DDQD god mode. The lobby shows JOINED / NEEDED, so a three-player room explicitly displays
1 / 3, 2 / 3 and 3 / 3 as players connect. Each machine carries one player.

The host selects the other map with N once play starts. Both maps have four
distinct valid spawn points. The map layout, doors and secret are shared;
view direction, weapon, health, ammo and running are per player. The HUD
always displays all participating players' frag scores.

Errors: 6 build mismatch; 7 room unknown/full/started; 8 not in a room;
9 relay unavailable; 10 invalid command/settings; 11 card/relay queue full;
12 ten-second timeout; 13 state desync; 14 peer dropped; 15 frame limit.
A match ends at network frame 60000 to avoid the device's 16-bit frame-wrap
limit (about an hour at the pacing ceiling). Make a fresh room afterward.

HOW IT WORKS

Z80: use the existing UniCard ports 50h/51h. REVD then INFO detects NET.
STSR (03h) reads the four-byte command status. CREATE/JOIN wait on the
IN_PROGRESS bit, bounded by 500 real 50 Hz keyboard interrupts. On error,
STORNO (04h) cancels the pending command before rendering the error screen.
The keyboard/music IRQ never touches the UniCard ports.

CREATE uses game id 5544h (UniDoom), exactly 2/3/4 selected room slots,
two input bytes per slot and settings {protocol=2, initial_sector=0}.
The build id is a 16-bit SHA-256 prefix covering the ARM payload, Z80 host,
network source and marine graphics. Different builds cannot
join each other. UniDoom and BomberNet have separate game IDs and rooms.
They share the transport, not game logic or matches.

The two input bytes are {key-down event, held-buttons mask}. NETSEND always
writes the required fixed four-byte input parameter, with two unused zero
bytes. NETPOLL reads exactly 2 + slots * 2 response bytes; unused local vector
entries are zeroed. It no longer reads ten bytes unconditionally.
Frames 0 and 1 are primed with neutral input; each later sample is sent two frames ahead.
FFFFh from NETPOLL means no frame is available and is explicitly rejected.

The Z80 uploads a 24-byte network record at ARM header offset 0Ch between
native calls. ARM advances simulation only for a new complete frame, in
fixed slot order. It moves all players first, then resolves weapons in slot
order. Simultaneous fights therefore favour the earlier slot when a lethal
hit prevents the later player firing.

For a brief missing-input frame the Z80 keeps the last completed VGA image
and skips ARM rendering entirely, polling again at the next 50 Hz tick.
It never predicts or skips a remote input. After 40 ticks (800 ms), it draws
WAITING FOR PLAYERS once and holds that warning until recovery. Ten seconds
without progress stops the match. Normal packet jitter no longer alternates
the full-screen message and game view. Local L taps are retained while
waiting. The minimap and god/cheat state are forced off for network screens;
the deathmatch HUD does not advertise M MAP. Exact room size also prevents waiting on unused slot 3 or 4.
The slowest player limits simulation cadence. Two-frame input delay is
about 120 ms at the 16.7 FPS ceiling; actual speed depends on the hardware.

Each rendered view loads the local player's camera and state. All peers
calculate the same 16-bit state fingerprint from player state, map, doors,
sector, game frame and winner. Local camera/HUD/music and render scratch
are excluded. Every 16 network frames, NETHASH lets the relay detect a
mismatch. It stops the match on disagreement; there is no state recovery,
late joining, spectators, discovery broadcast or cross-game compatibility.

The included relay speaks the documented JSON-lines TCP protocol, forwards
opaque input, readiness and state hashes, and handles keepalive ping/pong.
It returns slots/bytes/settings in both CREATE and JOIN replies, as needed
by card firmware. Protocol-2 UniDoom rooms require every selected slot to
connect before starting, even if a client readies early. TCP_NODELAY keeps
small input messages from waiting for Nagle buffering. It does not render, simulate the game or send video.

ARM rendering retains the validated firmware pointer at 08008228h and
accepts 10000000h..10008000h inclusive. It uses the existing double-buffered
16-colour direct VGA path. No Sharp VRAM copies or framebuffer readback.
The renderer packs its 32 cached shaded columns into 4-bit texels and shares
that storage with the BFS queue. At match start the Z80 uploads three
32x32 marine frames into the existing drone sprite slots 0/3/4. On leaving,
it restores the exact drone frames before resuming single-player. Both
1536-byte frame sets live in the Sharp image; ARM allocates no extra sprite
buffer and retains its 32-column texture cache. See MEMORY.txt.

SOURCES AND REFERENCES

Independent transport/relay implementation from the public protocol and
card API, with credit to MZPico/BomberNet. No BomberNet game code or assets
are included. The existing user-supplied d_e1m1.mid supplies the PSG music. The included
common keyboard table originates from NOBOMI-SOFTWARE's UniFractal scaffold;
the original demo is not a build dependency.

  https://github.com/MZPico/BomberNet/blob/2948cd900cf15cfd3103b70724056f2fb4e04028/docs/net-protocol.md
  https://github.com/MZPico/BomberNet/blob/2948cd900cf15cfd3103b70724056f2fb4e04028/c/common/netdev_card.c
  https://github.com/MZPico/BomberNet/blob/2948cd900cf15cfd3103b70724056f2fb4e04028/docs/setup/mz-800.md
  https://github.com/MZPico/MZPico-firmware/blob/5c7c4de63a5cc383656e23795aa98882d881cd72/docs/net-extension.md

BUILD AND VERIFICATION

From doom_net:
  make                 build root unidoom_net_v0_3.mzf
  make verify          full single-player + multiplayer emulator checks
  make verify-tcp      actual loopback TCP listener test
  make server          local LAN server (default TCP 8766)
  make package         ZIP, after successful current build and verification
  make clean           remove generated build files and Python caches

Needs clang for Cortex-M4, ld.lld, llvm-objcopy/llvm-nm and pasmo.
Python test dependencies are in ../requirements-dev.txt; libz80ex is also
needed. Shared build inputs are ../common/key_table.bin and ../d_e1m1.mid.
UNIDOOM_LLD selects a linker outside PATH; UNIDOOM_Z80EX selects a Z80
shared library outside the system search path. Install Python test packages
in the selected environment; no machine-specific tool directories are used.
The verified toolchain uses clang/LLVM 14; the linker enforces the tight
SRAM limit if a different compiler produces a larger binary.

Verification executes the actual Z80 and Cortex-M4 machine code with a
protocol model of the NET card, plus independent native combat fixtures.
It covers real 2-, 3- and 4-peer Z80/ARM matches, four ARM player states,
exact native/ARM images and hashes, count selection, rooms/readiness,
unchanged VGA during short stalls, a single sustained-stall warning, local
light toggles during waits, disabled online minimap/god mode, sprite upload/restoration, duplicate frames, timeouts,
missing NET, disconnects, shots, scoring, spawning and map/rematch control.
The single-player regression additionally checks 93 host/ARM frames, both
complete guided tours, independent ray/collision/AI checks, firmware-pointer
validation and two full E1M1 PSG loops. The relay is separately exercised
through real loopback TCP sockets, including launching server.py as a
separate process and connecting three TCP clients.

These are software/emulator results. Electrical timing, Ethernet firmware
coexistence with OpenCPU and gameplay across physical mk3b cards still need
hardware verification. If the NET-required screen appears on firmware that
already runs BomberNet, provide its version or the mk3b NET command header;
that will identify any firmware API difference.

DIRECTORY AND PACKAGE HYGIENE

build/ contains generated compiler outputs and verification reports and is
ignored by Git. make clean removes build/ and Python caches; it preserves
source, previews and the root MZF/ZIP releases. Source packages use the
shared ../tools/package.py and include common/key_table.bin, the MIDI and
shared repository tools. Build products and other demos are excluded.
