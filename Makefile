.DEFAULT_GOAL := all
.PHONY: all doom doom-direct doom-net verify verify-doom verify-doom-direct verify-doom-net verify-tcp server package clean help
PYTHON ?= python3

all: doom doom-direct doom-net

doom:
	$(MAKE) -C doom all

doom-direct:
	$(MAKE) -C doom_direct all

doom-net:
	$(MAKE) -C doom_net all

verify: verify-doom verify-doom-direct verify-doom-net

verify-doom:
	$(MAKE) -C doom verify

verify-doom-direct:
	$(MAKE) -C doom_direct verify

verify-doom-net:
	$(MAKE) -C doom_net verify

verify-tcp:
	$(MAKE) -C doom_net verify-tcp

server:
	$(MAKE) -C doom_net server

package:
	$(MAKE) -C doom package
	$(MAKE) -C doom_direct package
	$(MAKE) -C doom_net package

clean:
	$(PYTHON) tools/clean.py

help:
	@echo 'make             Build all three Doom editions'
	@echo 'make doom        Build Classic'
	@echo 'make doom-direct Build Direct'
	@echo 'make doom-net    Build NET'
	@echo 'make verify      Run all edition emulator suites'
	@echo 'make verify-tcp  Test the NET local server over loopback TCP'
	@echo 'make server      Start the NET LAN server'
	@echo 'make package     Package current verified releases'
	@echo 'make clean       Remove build products and Python caches; keep releases/previews'
