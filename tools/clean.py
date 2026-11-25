#!/usr/bin/env python3
"""Remove generated files belonging to the three Doom editions only."""
import argparse
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parent.parent
PROJECTS=('doom','doom_direct','doom_net')

def clean(projects):
    for name in projects:
        directory=ROOT/name
        build=directory/'build'
        if build.exists():shutil.rmtree(build)
        for cache in directory.rglob('__pycache__'):
            if cache.is_dir():shutil.rmtree(cache)
        for pattern in ('*.pyc','*.pyo'):
            for bytecode in directory.rglob(pattern):bytecode.unlink()
    for directory in (ROOT/'tools',ROOT/'common'):
        if directory.exists():
            for cache in directory.rglob('__pycache__'):
                if cache.is_dir():shutil.rmtree(cache)
    print('Cleaned build products and Python caches: '+', '.join(projects))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project',nargs='?',choices=PROJECTS)
    args=parser.parse_args()
    clean((args.project,) if args.project else PROJECTS)
