# Set up and check a checkout of this repository; see "Development environment" in AGENTS.md.
#   make -n bootstrap   show what the bootstrap would run, changing nothing
#   make bootstrap      install the tools below with the system package manager (idempotent)
#   make doctor         one line per tool; non-zero when one is missing or too old
.PHONY: bootstrap doctor

TOOLS := bash git jq shellcheck python3
PYTHON_MIN := 3.11

# The distribution, read from /etc/os-release (its ID and ID_LIKE words); the line that installs is the one that starts with sudo.
OS_IDS := $(shell . /etc/os-release 2>/dev/null && echo "$$ID $$ID_LIKE")
ifneq (,$(filter arch,$(OS_IDS)))
INSTALL := sudo pacman -S --needed --noconfirm bash git jq shellcheck python
else ifneq (,$(filter debian ubuntu,$(OS_IDS)))
INSTALL := sudo apt-get install -y bash git jq shellcheck python3
else ifneq (,$(filter fedora rhel,$(OS_IDS)))
INSTALL := sudo dnf install -y bash git jq ShellCheck python3
endif

bootstrap:
ifdef INSTALL
	$(INSTALL)
else
	@echo "bootstrap: this distribution is not known here. Install $(TOOLS) (python3 >= $(PYTHON_MIN)) with its package manager."; exit 1
endif

doctor:
	@rc=0; \
	for t in $(TOOLS); do \
	  if command -v $$t >/dev/null 2>&1; then \
	    echo "ok: $$t $$($$t --version 2>&1 | grep -Eo '[0-9]+(\.[0-9]+)+' | head -n 1)"; \
	  else \
	    echo "missing: $$t is not installed"; rc=1; \
	  fi; \
	done; \
	if command -v python3 >/dev/null 2>&1 && ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= tuple(map(int, "$(PYTHON_MIN)".split("."))) else 1)'; then \
	  echo "missing: python3 older than $(PYTHON_MIN)"; rc=1; \
	fi; \
	exit $$rc
