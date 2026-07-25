# Thin wrappers over bin/harness (§10)
HARNESS := ./bin/harness

.PHONY: init compile author-gate shadows resolve gates verify review replay status test

init:
	$(HARNESS) init

compile:
	$(HARNESS) compile

author-gate:
	$(HARNESS) author-gate

shadows:
	$(HARNESS) extract --all

resolve:
	$(HARNESS) resolve --slice $(SLICE)

gates:
	$(HARNESS) gates --event $(EVENT)

verify:
	$(HARNESS) verify

review:
	$(HARNESS) review

replay:
	$(HARNESS) review --replay

status:
	$(HARNESS) status --json

test:
	python3 -m pytest tests/ -q
