.PHONY: all verify package clean
PYTHON ?= python3

all:
	$(PYTHON) tools/build.py

verify: all
	$(PYTHON) tools/test_lzss.py
	$(PYTHON) tools/test_import_midi.py
	$(PYTHON) tools/verify.py

package:
	$(PYTHON) ../tools/package.py doom_direct

clean:
	$(PYTHON) ../tools/clean.py doom_direct
