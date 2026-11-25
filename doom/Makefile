.PHONY: all verify package clean
PYTHON ?= python3

all:
	$(PYTHON) tools/build.py

verify: all
	$(PYTHON) tools/verify.py

package:
	$(PYTHON) ../tools/package.py doom

clean:
	$(PYTHON) ../tools/clean.py doom
