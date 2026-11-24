"""Verify ordinary shutdown and abrupt power loss using the packaged ARM64 launcher."""
import hashlib
import json
import secrets
from pathlib import Path
import subprocess
import signal
import sys


def revision(text):
    return hashlib.sha256(text.encode()).hexdigest()


def wait(vm, log, prefix):
    for raw in vm.stdout:
        log.write(raw)
        line = raw.decode(errors="replace").strip()
        if line.startswith(prefix):
            return line
        if "Kernel panic" in line:
            raise RuntimeError(line)
    raise RuntimeError(f"Guest stopped before {prefix}")


def command(vm, log, request, prefix):
    vm.stdin.write(request.encode() + b"\n")
    vm.stdin.flush()
    return wait(vm, log, prefix)


original = "작업 기록"
model_port = int(sys.argv[3]) if len(sys.argv) > 3 else None
addition = "재부팅 검증" if model_port is None else f"검토 완료 {1000 + secrets.randbelow(9000)}"
saved = original + "\n" + addition
durable = saved + "\n전원 중단 검증"
for boot, expected in enumerate((original, saved, durable), 1):
    with Path(f"build/arm64-disk-{boot}.log").open("wb") as log, subprocess.Popen([
        "bash", sys.argv[1], sys.argv[2],
    ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as vm:
        try:
            wait(vm, log, "AIOS_DOCUMENT_READY pid=1")
            result = command(vm, log, "inspect", "AIOS_DOCUMENT ")
            assert result == f"AIOS_DOCUMENT revision={revision(expected)} bytes={len(expected.encode())}", result
            if boot == 1:
                if model_port is None:
                    result = command(vm, log, f"append {revision(original)} {addition}", "AIOS_SAVED ")
                else:
                    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
                    from model_mvp import run_model

                    def tool(name, document, revision, line):
                        if (name != "append_line" or document != "note.txt" or not line.isprintable()
                                or len(line.encode()) > 3900):
                            raise ValueError("Expected a single printable console line")
                        response = command(vm, log, f"append {revision} {line}", "AIOS_")
                        if not response.startswith("AIOS_SAVED revision="):
                            raise ValueError(response)
                        return {"revision": response.removeprefix("AIOS_SAVED revision=")}

                    instruction = f"문서 마지막에 '{addition}' 한 줄을 추가해 줘."
                    catalog = [{"name": "append_line", "inputSchema": {"properties": {"line": {"type": "string"}}}}]
                    state = {"document": "note.txt", "revision": result.split()[1].split("=")[1]}
                    published, trace = run_model(model_port, instruction, catalog, tool, state)
                    result = "AIOS_SAVED revision=" + published["revision"]
                assert result == f"AIOS_SAVED revision={revision(saved)}", result
                command(vm, log, f"append {revision(original)} 중복", "AIOS_REJECT invalid-edit")
            if boot == 2:
                result = command(vm, log, f"append {revision(saved)} 전원 중단 검증", "AIOS_SAVED ")
                assert result == f"AIOS_SAVED revision={revision(durable)}", result
                vm.kill()
                assert vm.wait(timeout=20) == -signal.SIGKILL
            else:
                vm.stdin.write(b"poweroff\n")
                vm.stdin.flush()
                assert vm.wait(timeout=20) == 0
        except Exception:
            log.flush()
            print(Path(log.name).read_bytes()[-4000:].decode(errors='replace'), flush=True)
            raise
        finally:
            if vm.poll() is None:
                vm.terminate()
        print(f"Verified ARM64 disk boot {boot}", flush=True)

if model_port is not None:
    disk_text = subprocess.check_output(["debugfs", "-R", "cat /work/note.txt", sys.argv[2]])
    assert disk_text == durable.encode()
    Path("build/arm64-model-proof.json").write_text(json.dumps({
        "instruction": instruction, "model_trace": trace, "after_reboot": saved,
        "offline_after_power_loss": disk_text.decode(), "guest_ram_mib": 128,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
