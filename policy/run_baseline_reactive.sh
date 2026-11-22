#!/usr/bin/env bash
# Reactive baseline (policy 2). Kept for `make baseline-reactive`; see run_baseline.sh.
POLICY=reactive exec "$(dirname "$0")/run_baseline.sh" "$@"
