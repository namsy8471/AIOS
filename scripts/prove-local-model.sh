#!/usr/bin/env bash
set -euo pipefail
if [[ ${1:-} != --server-ready ]]; then
  exec bash scripts/with-local-model.sh bash "$0" --server-ready
fi
stage=$(mktemp -d)
trap 'rm -rf -- "$stage"' EXIT
if ! python3 build/runtime/aios_mvp.py --model-port 18080 --output "$stage/proof"; then
  tail -40 "$stage/proof/first-boot.log" >&2
  exit 1
fi
cp "$stage/proof/proof.json" build/runtime/model-proof.json
cat build/runtime/model-proof.json
python3 build/runtime/aios_mvp.py --model-port 18080 --resume "$stage/proof" --output "$stage/custom" \
  --instruction "문서에서 '첫 문서'를 '작업 기록'으로 바꿔 줘."
python3 - "$stage/proof/proof.json" "$stage/custom/proof.json" <<'PY'
import json
import sys
from pathlib import Path

first, second = [json.loads(Path(path).read_text(encoding="utf-8")) for path in sys.argv[1:]]
for proof, operation in ((first, "append_line"), (second, "replace_text")):
    trace = proof["model_trace"]
    assert len(trace) == 1 and trace[0]["mcp_call"]["name"] == operation, proof
assert second["before"] == first["after_reboot"]
assert second["after_reboot"] == first["after_reboot"].replace("첫 문서", "작업 기록", 1), second
PY
cp "$stage/custom/proof.json" build/runtime/model-replace-proof.json
python3 build/runtime/aios_mvp.py --model-port 18080 --resume "$stage/custom" --output "$stage/batch" \
  --instruction "'작업 기록'을 '업무 일지'로 바꾸고 마지막 줄에 '배포 준비'를 추가해 줘."
python3 - "$stage/custom/proof.json" "$stage/batch/proof.json" <<'PY'
import json
import sys
from pathlib import Path

previous, batch = [json.loads(Path(path).read_text(encoding="utf-8")) for path in sys.argv[1:]]
assert batch["before"] == previous["after_reboot"]
assert batch["after_reboot"] == batch["before"].replace("작업 기록", "업무 일지", 1) + "\n배포 준비", batch
calls = [step["mcp_call"] for step in batch["model_trace"] if "mcp_result" in step]
assert [call["name"] for call in calls] == ["edit_document"], batch
assert [edit["op"] for edit in calls[0]["arguments"]["edits"]] == ["replace_text", "append_line"], batch
PY
cp "$stage/batch/proof.json" build/runtime/model-batch-proof.json
python3 build/runtime/aios_mvp.py --model-port 18080 --interactive --output "$stage/live" <<'REQUESTS'
마지막에 '승인 요청' 한 줄을 추가해 줘.
'승인 요청'을 '승인 완료'로 바꿔 줘.
REQUESTS
python3 - "$stage/live/proof.json" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

proof = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
first, second = proof["turns"]
middle = hashlib.sha256((proof["before"] + "\n승인 요청").encode()).hexdigest()
assert first["revision_before"] == proof["revision_before"]
assert first["revision_after"] == second["revision_before"] == middle
assert second["revision_after"] == proof["revision_after_reboot"]
assert proof["after_reboot"] == proof["before"] + "\n승인 완료"
PY
cp "$stage/live/proof.json" build/runtime/model-session-proof.json
