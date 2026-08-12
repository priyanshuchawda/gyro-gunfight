#!/usr/bin/env bash
# Every check that does not need hands on the gun.
#
#   tools/run_tests.sh

set -uo pipefail
cd "$(dirname "$0")/.."

pass=0
fail=0
declare -a failed=()

run() {
  local name="$1"
  shift
  printf '\n\033[1m== %s\033[0m\n' "$name"
  if "$@"; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    failed+=("$name")
  fi
}

cxx() {
  local src="$1" bin="$2"
  g++ -std=c++11 -Wall -Wextra -o "$bin" "$src" && "$bin"
}

run "trigger debounce"  cxx firmware/aim-controller/test/test_trigger.cpp /tmp/gg_trigger
run "attitude filter"   cxx firmware/aim-controller/test/test_attitude.cpp /tmp/gg_attitude
run "gyro bias tracker" cxx firmware/aim-controller/test/test_bias.cpp /tmp/gg_bias

if [[ -x .venv/bin/python ]]; then
  run "serial parsing" .venv/bin/python tools/test_serial.py
else
  run "serial parsing" python3 tools/test_serial.py
fi

# The 3D range needs the venv, which is not required for anything else.
if [[ -x .venv/bin/python ]]; then
  run "3D aim projection" .venv/bin/python range3d/main.py --simulate --selftest
else
  printf '\n\033[33m-- skipped 3D range: no .venv (see range3d/README.md)\033[0m\n'
fi

printf '\n\033[1m%s\033[0m\n' "$(printf '=%.0s' {1..52})"
if [[ $fail == 0 ]]; then
  printf '\033[32mall %d suites passed\033[0m\n' "$pass"
  exit 0
fi
printf '\033[31m%d of %d suites failed:\033[0m\n' "$fail" "$((pass + fail))"
printf '  %s\n' "${failed[@]}"
exit 1
