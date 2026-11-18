# Experiment entry points. Everything is SIMULATED (see README.md).
SEED ?= 1

.PHONY: baseline-reactive test

## Reactive up/down loop (HRES-like) + seeded workload; results in results/reactive/seed$(SEED)/
baseline-reactive:
	SEED=$(SEED) policy/run_baseline_reactive.sh

## Unit tests (feed + workload generator)
test:
	cd feed && python3 -m unittest -q
	cd workload && python3 -m unittest -q
