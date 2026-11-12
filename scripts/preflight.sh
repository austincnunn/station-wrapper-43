#!/usr/bin/env bash
# Local pre-push check. Runs what CI runs, plus a throwaway image build and
# smoke test. The image it builds (station-wrapper-43-smoke:local) is never pushed: the
# official build is dev-image.yml on GitHub.
#
# Usage: scripts/preflight.sh [--no-images]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "== syntax"
python3 -m py_compile fs42-tuner/*.py scripts/*.py fs42-sync/*.py supervisor/*.py
bash -n scripts/*.sh install.sh setup-dirs.sh fieldstation42/entrypoint.sh
sh -n farm/run.sh fieldstation42/fs42-channels
python3 -c "import json; json.load(open('fs42-tuner/config.default.json')); json.load(open('fs42-tuner/config.example.json'))"

echo "== tuner tests"
(cd fs42-tuner && for t in test_*.py; do echo "-- $t"; python3 "$t" > /dev/null; done)

echo "== generator tests"
python3 -c "import defusedxml" 2>/dev/null || { echo "missing: pip install defusedxml" >&2; exit 1; }
python3 -c "import jsonschema" 2>/dev/null || echo "note: pip install jsonschema to also check station configs against FieldStation42's schema" >&2
python3 scripts/test_build_channels.py 2>&1 | tail -3
python3 scripts/test_init.py 2>&1 | tail -3
python3 scripts/test_compose.py 2>&1 | tail -3
python3 scripts/test_fs42_link.py 2>&1 | tail -3
python3 scripts/test_firstrun.py 2>&1 | tail -3
python3 scripts/test_setup_dirs.py 2>&1 | tail -3
(cd fs42-sync && python3 test_sync.py 2>&1 | tail -3)
(cd supervisor && python3 test_supervisor.py 2>&1 | tail -3)

echo "== FieldStation42 contract (upstream's newest, which the image build fetches)"
fs42="$(mktemp -d)"
git clone -q --depth 1 https://github.com/shane-mason/FieldStation42.git "$fs42"
python3 scripts/check-fs42-contract.py "$fs42"
FS42_SRC="$fs42" python3 scripts/test_build_channels.py FieldStationSchemaTest 2>&1 | tail -3
rm -rf "$fs42"

if [ "${1:-}" = "--no-images" ]; then
  echo "preflight ok (images skipped)"; exit 0
fi

echo "== build and smoke test the image (a throwaway station-wrapper-43-smoke:local; nothing is pushed)"
# PREFLIGHT_BUILD_ARGS adds docker build flags, e.g. --network=host when the Docker bridge can't reach the internet.
# shellcheck disable=SC2086
docker build -q ${PREFLIGHT_BUILD_ARGS:-} -t station-wrapper-43-smoke:local . > /dev/null
scripts/smoke-image.sh station-wrapper-43-smoke:local
echo "preflight ok"
