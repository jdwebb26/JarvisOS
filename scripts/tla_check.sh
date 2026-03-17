#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JAR_PATH="${TLA_TOOLS_JAR:-$ROOT/tools/tla/tla2tools.jar}"
TLC_MAIN="tlc2.TLC"

if ! command -v java >/dev/null 2>&1; then
  printf 'error: java is not installed or not on PATH.\n' >&2
  printf 'hint: see docs/notes/tla_setup.md\n' >&2
  exit 1
fi

if [[ ! -f "$JAR_PATH" ]]; then
  printf 'error: TLC jar not found at %s\n' "$JAR_PATH" >&2
  printf 'hint: place tla2tools.jar at tools/tla/tla2tools.jar or set TLA_TOOLS_JAR.\n' >&2
  printf 'hint: see docs/notes/tla_setup.md\n' >&2
  exit 1
fi

run_spec() {
  local spec_name="$1"
  local spec_path="$ROOT/specs/tla/${spec_name}.tla"
  local cfg_path="$ROOT/specs/tla/${spec_name}.cfg"

  printf '\n== Running %s ==\n' "$spec_name"
  java -cp "$JAR_PATH" "$TLC_MAIN" -deadlock -workers auto -config "$cfg_path" "$spec_path"
}

run_spec "TaskLifecycle"
run_spec "ApprovalGate"
run_spec "SchedulerLease"

printf '\nAll TLA+ checks passed.\n'
