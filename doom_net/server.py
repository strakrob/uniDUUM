#!/usr/bin/env python3
"""Start the UniDoom LAN server for UniCard Ethernet mk3b (no pip needed)."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent/'tools'))
from relay import main
if __name__=='__main__':main(default_bind='0.0.0.0')
