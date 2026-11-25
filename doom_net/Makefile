.PHONY: all verify verify-tcp server package clean
PYTHON ?= python3

all:
	$(PYTHON) tools/build.py

verify: all
	$(PYTHON) tools/test_lzss.py
	$(PYTHON) tools/test_import_midi.py
	$(PYTHON) tools/verify.py
	$(PYTHON) tools/test_deathmatch.py
	$(PYTHON) tools/test_players.py
	$(PYTHON) tools/test_network.py

verify-tcp:
	$(PYTHON) tools/test_relay_tcp.py
	$(PYTHON) tools/test_server.py

server:
	$(PYTHON) server.py

package:
	$(PYTHON) ../tools/package.py doom_net

clean:
	$(PYTHON) ../tools/clean.py doom_net
