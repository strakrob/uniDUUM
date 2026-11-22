.PHONY: all verify cube verify-cube doom verify-doom doom-direct verify-doom-direct vramfinder verify-vramfinder

all:
	python3 tools/build.py

verify: all
	python3 tools/verify.py

cube:
	python3 cube/tools/build.py

verify-cube: cube
	python3 cube/tools/verify.py

doom:
	python3 doom/tools/build.py

verify-doom: doom
	python3 doom/tools/verify.py

doom-direct:
	python3 doom_direct/tools/build.py

verify-doom-direct: doom-direct
	python3 doom_direct/tools/verify.py

vramfinder:
	python3 vramfinder/tools/build.py

verify-vramfinder: vramfinder
	python3 vramfinder/tools/verify.py
