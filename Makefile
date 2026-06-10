PYTHON ?= python3
export PYTHONPATH := src

.PHONY: help test doctor observe baseline

help:
	@echo "Developer convenience targets (the product interface is 'python -m ck3env'):"
	@echo "  make test      - offline test suite"
	@echo "  make doctor    - environment diagnosis"
	@echo "  make observe RUN=<dir> [LIVE=1 CK3_USER_DIR=<dir>]"
	@echo "  make baseline RUN=<dir> STEPS=<n> CK3_USER_DIR=<dir>"

test:
	@$(PYTHON) -m unittest discover -s tests

doctor:
	@$(PYTHON) -m ck3env doctor

observe:
	@test -n "$(RUN)" || (echo "usage: make observe RUN=runs/dir" && exit 2)
	@$(PYTHON) -m ck3env observe --run "$(RUN)" $(if $(LIVE),--live --ck3-user-dir "$(CK3_USER_DIR)")

baseline:
	@test -n "$(RUN)" || (echo "usage: make baseline RUN=runs/dir STEPS=100 CK3_USER_DIR=..." && exit 2)
	@$(PYTHON) -m ck3env baseline-run --run "$(RUN)" --steps $(or $(STEPS),100) --live --ck3-user-dir "$(CK3_USER_DIR)"
