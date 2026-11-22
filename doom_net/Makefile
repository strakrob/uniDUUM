.PHONY: all verify verify-tcp server package
all:
	python3 tools/build.py
verify: all
	python3 tools/test_lzss.py
	python3 tools/test_import_midi.py
	python3 tools/verify.py
	python3 tools/test_deathmatch.py
	python3 tools/test_players.py
	python3 tools/test_network.py
verify-tcp:
	python3 tools/test_relay_tcp.py
	python3 tools/test_server.py

server:
	python3 server.py

package:
	python3 tools/package.py
