# Experiment entry points. Everything is SIMULATED (see README.md).
SEED ?= 1
SEEDS ?= 1
POLICIES ?= static reactive predictive

.PHONY: baseline-reactive baseline sweep aggregate test

## Reactive up/down loop (HRES-like) + seeded workload; results in results/reactive/seed$(SEED)/
baseline-reactive:
	SEED=$(SEED) policy/run_baseline_reactive.sh

## One run of any policy: make baseline POLICY=predictive SEED=1
baseline:
	POLICY=$(POLICY) SEED=$(SEED) policy/run_baseline.sh

## Every policy x seed, then aggregate + chart: make sweep SEEDS="1 2 3 4 5"
sweep:
	SEEDS="$(SEEDS)" POLICIES="$(POLICIES)" policy/run_sweep.sh

## Re-aggregate existing results (sweep_summary.csv, sweep_table.md, sweep.png)
aggregate:
	python3 policy/aggregate.py --results results
	python3 policy/plot_sweep.py --results results

## Unit tests (feed, workload generator, policy)
test:
	cd feed && python3 -m unittest discover -q
	cd workload && python3 -m unittest discover -q
	cd policy && python3 -m unittest discover -q
