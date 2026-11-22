"""Test fixtures for the Z80-owned sprite transfers (no extra ARM allocation)."""
import ctypes as ct

def native_skins(native,root,players=True):
    blob=(root/'build'/('marines.bin' if players else 'drones.bin')).read_bytes()
    base=ct.addressof(native.native_art().contents)+4096
    for frame,slot in enumerate((0,3,4)):
        ct.memmove(base+slot*512,blob[frame*512:(frame+1)*512],512)

def arm_skins(arm,root,symbols,players=True):
    blob=(root/'build'/('marines.bin' if players else 'drones.bin')).read_bytes()
    for frame,slot in enumerate((0,3,4)):
        arm.u.mem_write(symbols['art']+4096+slot*512,blob[frame*512:(frame+1)*512])
