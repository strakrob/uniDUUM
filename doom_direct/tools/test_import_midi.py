"""MIDI importer checks using generated note/control fixtures, no song assets."""
import struct
import unittest
from import_midi import arrange,read_midi,MidiError

def midi(*tracks,division=96):
    return b'MThd'+struct.pack('>IHHH',6,int(len(tracks)>1),len(tracks),division)+b''.join(b'MTrk'+struct.pack('>I',len(t))+t for t in tracks)

END=b'\x00\xff\x2f\x00'

class ImportTests(unittest.TestCase):
    def test_running_status_and_velocity_zero(self):
        track=b'\x00\x90\x3c\x64\x00\x43\x64\x60\x43\x00\x00\x3c\x00'+END
        r=arrange(midi(track))
        self.assertEqual(r['arranged_seconds'],.5)
        self.assertEqual(r['notes'],[0,60,67])
        self.assertEqual(r['records'],[[25,2,1,0]])

    def test_tempo_changes_merge_across_tracks(self):
        tempo=b'\x00\xff\x51\x03\x07\xa1\x20\x60\xff\x51\x03\x0f\x42\x40\x60\xff\x2f\x00'
        notes=b'\x00\xc0\x21\x00\x90\x34\x64\x60\x80\x34\x00\x00\x90\x37\x64\x60\x80\x37\x00'+END
        r=arrange(midi(tempo,notes))
        self.assertEqual(r['seconds'],1.5)
        self.assertEqual([v[0] for v in r['records']],[25,50])

    def test_sustain_release(self):
        track=b'\x00\xb0\x40\x7f\x00\x90\x3c\x64\x30\x80\x3c\x00\x30\xb0\x40\x00\x60\xff\x2f\x00'
        r=arrange(midi(track))
        self.assertEqual(r['records'],[[25,1,1,0],[25,0,0,0]])

    def test_repeated_pitch_retriggers(self):
        r=arrange(midi(b'\x00\x90\x3c\x64\x30\x3c\x64\x30\x3c\x00'+END))
        self.assertEqual([v[0] for v in r['records']],[12,13])

    def test_bass_octave_and_percussion_priority(self):
        track=b'\x00\xc0\x21\x00\x90\x28\x64\x00\x99\x26\x64\x00\x2a\x64\x60\x80\x28\x00'+END
        r=arrange(midi(track))
        self.assertEqual(r['notes'],[0,52])
        self.assertEqual(r['records'][0][-1],2)
        self.assertEqual(r['warnings']['simultaneous_drum_hits_reduced'],1)

    def test_explicit_channel_selection(self):
        track=b'\x00\x90\x3c\x64\x00\x91\x48\x64\x60\x80\x3c\x00\x00\x81\x48\x00'+END
        r=arrange(midi(track),lead_channel=1,bass_channel=0)
        self.assertEqual(r['records'],[[25,2,1,0]])
        self.assertEqual((r['lead_channel'],r['bass_channel']),(2,1))

    def test_whole_channel_transposition_preserves_octaves(self):
        track=b'\x00\x90\x1c\x64\x60\x1c\x00\x00\x28\x64\x60\x28\x00'+END
        r=arrange(midi(track))
        self.assertEqual(r['notes'],[0,52,64])
        self.assertEqual(r['channel_transpose_semitones'],{'1':24})

    def test_malformed_and_unsupported(self):
        for data in (b'not midi',midi(b'\x00\x3c\x64'+END),midi(END,division=0xe728),midi(b'\x00\x90\x3c')):
            with self.subTest(data=data),self.assertRaises(MidiError):read_midi(data)

    def test_pattern_encoding_roundtrip(self):
        r=arrange(midi(b'\x00\x90\x3c\x64\x60\x3c\x00'+END))
        expanded=[list(row) for i in r['pattern_order'] for row in r['patterns'][i]]
        self.assertEqual(expanded,r['records'])

if __name__=='__main__':unittest.main()
