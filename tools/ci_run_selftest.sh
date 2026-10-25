#!/usr/bin/env bash
# Run the RadVeil self-test inside an installed Slicer and check the result.
#
#   tools/ci_run_selftest.sh SLICER_EXECUTABLE MODULE_DIR LOG_FILE
#
# MODULE_DIR is the staged RadVeil folder (tools/stage_module.py), i.e. exactly
# what the extension package contains. Success is read from the
# "RADVEIL-SELFTEST: PASS" marker in LOG_FILE, because Windows GUI
# applications do not reliably return output or exit codes to the shell.
set -uo pipefail

slicer="$1"
module_dir="$2"
log_file="$3"
here="$(cd "$(dirname "$0")/.." && pwd)"
script="$here/tests/slicer_selftest.py"

if [ "${RUNNER_OS:-}" = "Windows" ] && command -v cygpath >/dev/null; then
  module_dir="$(cygpath -w "$module_dir")"
  script="$(cygpath -w "$script")"
  log_file_native="$(cygpath -w "$log_file")"
else
  log_file_native="$log_file"
fi

rm -f "$log_file"
export RADVEIL_TEST_LOG="$log_file_native"
export LANG="${LANG:-C.UTF-8}"

args=(--no-splash --testing --additional-module-paths "$module_dir" --python-script "$script")
if [ "${RUNNER_OS:-$(uname)}" = "Linux" ]; then
  # Mesa's software OpenGL is enough for the 3D comparison views.
  export LIBGL_ALWAYS_SOFTWARE=1
  xvfb-run -a -s "-screen 0 1600x1000x24" "$slicer" "${args[@]}"
else
  "$slicer" "${args[@]}"
fi
status=$?

echo "----- self-test log -----"
cat "$log_file" 2>/dev/null || echo "(no log written)"
echo "-------------------------"

if grep -q "RADVEIL-SELFTEST: PASS" "$log_file" 2>/dev/null; then
  echo "Self-test passed (Slicer exit status $status)."
  exit 0
fi
echo "Self-test FAILED (Slicer exit status $status)."
exit 1
