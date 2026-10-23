#!/usr/bin/env bash
# Run Ambush! Play-mode tests headless from the CLI. Writes TAP-style result to stdout and
# a JUnit XML to .claude/reports/last-playmode-tests.xml. Exits non-zero on any failure.
set -euo pipefail

UNITY_APP="${UNITY_APP:-/Applications/Unity/Hub/Editor/6000.4.6f1/Unity.app/Contents/MacOS/Unity}"
PROJECT="$(cd "$(dirname "$0")/.." && pwd)/ELVATR GAME 1"
REPORTS_DIR="$(cd "$(dirname "$0")/.." && pwd)/.claude/reports"
RESULTS="$REPORTS_DIR/last-playmode-tests.xml"
LOG="$REPORTS_DIR/last-playmode-tests.log"

mkdir -p "$REPORTS_DIR"
rm -f "$RESULTS" "$LOG"

if [ ! -x "$UNITY_APP" ]; then
  # Fallback: find the first Unity binary matching the project's required version.
  UNITY_APP="$(/usr/bin/find /Applications/Unity/Hub/Editor -name Unity -type f 2>/dev/null | head -1)"
fi
if [ ! -x "$UNITY_APP" ]; then
  echo "ERROR: no Unity binary found. Set UNITY_APP env var." >&2
  exit 2
fi

echo "Unity: $UNITY_APP"
echo "Project: $PROJECT"
echo "Results: $RESULTS"

"$UNITY_APP" \
  -batchmode -nographics \
  -projectPath "$PROJECT" \
  -runTests -testPlatform PlayMode \
  -testResults "$RESULTS" \
  -logFile "$LOG"
EXIT=$?

# Summarize: print the test cases + pass/fail from the XML.
if [ -f "$RESULTS" ]; then
  python3 - <<'PY'
import xml.etree.ElementTree as ET
import os, sys
xml = os.environ.get("RESULTS") or ".claude/reports/last-playmode-tests.xml"
tree = ET.parse(xml)
root = tree.getroot()
# NUnit3-style: <test-run><test-suite>…<test-case name=.. result=.. />
cases = root.findall(".//test-case")
passed = sum(1 for c in cases if c.get("result") == "Passed")
failed = sum(1 for c in cases if c.get("result") in ("Failed", "Error"))
skipped = sum(1 for c in cases if c.get("result") == "Skipped")
for c in cases:
    status = c.get("result","?")
    name = c.get("name","?")
    print(f"  [{status}] {name}")
print(f"Total: {len(cases)}  Passed: {passed}  Failed: {failed}  Skipped: {skipped}")
sys.exit(0 if failed == 0 else 1)
PY
else
  echo "No results XML produced; see $LOG"
fi

exit $EXIT
