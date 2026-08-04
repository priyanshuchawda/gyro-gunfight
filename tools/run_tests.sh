#!/usr/bin/env bash
# Every check that does not need hands on the gun.
#
#   tools/run_tests.sh          firmware, game, bridge
#   tools/run_tests.sh --all    also the browser and the live controller
#
# The browser check is opt-in because it needs a bridge already serving on
# port 8000, and a missing bridge is not the same as a broken game.

set -uo pipefail
cd "$(dirname "$0")/.."

WITH_BROWSER=0
[[ "${1:-}" == "--all" ]] && WITH_BROWSER=1

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
run "page and script"   node tools/check_web.js
run "game rules"        node tools/test_range.js
run "bridge parsing"    python3 tools/test_bridge.py

if [[ $WITH_BROWSER == 1 ]]; then
  if curl -sf -m 3 http://127.0.0.1:8000/aim > /dev/null 2>&1; then
    run "browser and live controller" python3 tools/visual_check.py
  else
    printf '\n\033[33m-- skipped browser check: no bridge on port 8000\033[0m\n'
  fi
fi

printf '\n\033[1m%s\033[0m\n' "$(printf '=%.0s' {1..52})"
if [[ $fail == 0 ]]; then
  printf '\033[32mall %d suites passed\033[0m\n' "$pass"
  exit 0
fi
printf '\033[31m%d of %d suites failed:\033[0m\n' "$fail" "$((pass + fail))"
printf '  %s\n' "${failed[@]}"
exit 1
