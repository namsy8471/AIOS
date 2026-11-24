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


sys.path.insert(0, str(Path(sys.argv[1]).resolve().parent))
from arm64_model import command, edit, wait


original = "작업 기록"
model_port = int(sys.argv[3]) if len(sys.argv) > 3 else None
addition = "재부팅 검증" if model_port is None else f"검토 완료 {1000 + secrets.randbelow(9000)}"
saved = original + "\n" + addition
durable = saved + "\n" + (addition if model_port is not None else "전원 중단 검증")
for boot, expected in enumerate((original, saved, durable), 1):
    with Path(f"build/arm64-disk-{boot}.log").open("wb") as log, subprocess.Popen([
        "bash", sys.argv[1], sys.argv[2],
    ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as vm:
        try:
            wait(vm, log, "AIOS_DOCUMENT_READY pid=1")
            reply = command(vm, log, "memory", "AIOS_")
            assert reply.startswith("AIOS_MEMORY "), reply
            memory = json.loads(reply.removeprefix("AIOS_MEMORY "))
            assert 0 < memory["available_kib"] <= memory["total_kib"] <= 128 * 1024
            assert 0 < memory["init_rss_kib"] < memory["total_kib"]
            print(f"ARM64 boot {boot} ready memory: {memory}", flush=True)
            result = command(vm, log, "inspect", "AIOS_DOCUMENT ")
            assert result == f"AIOS_DOCUMENT revision={revision(expected)} bytes={len(expected.encode())}", result
            observed = result.split()[1].split("=")[1]
            offset = 0
            chunks = []
            while offset is not None:
                reply = command(vm, log, f"read {observed} {offset} 3", "AIOS_PAGE ")
                page = json.loads(reply.removeprefix("AIOS_PAGE "))
                assert page["revision"] == observed and 0 < len(page["text"]) <= 3
                chunks.append(page["text"])
                next_byte = page["next_byte"]
                assert next_byte is None or next_byte == offset + len(page["text"].encode())
                offset = next_byte
            assert "".join(chunks) == expected
            command(vm, log, f"read {observed} 1 3", "AIOS_REJECT invalid-read")
            if boot == 1:
                if model_port is None:
                    result = command(vm, log, f"append {revision(original)} {addition}", "AIOS_SAVED ")
                else:
                    instruction = f"문서 마지막에 '{addition}' 한 줄을 추가해 줘."
                    published, trace = edit(vm, log, model_port, instruction, observed)
                    result = "AIOS_SAVED revision=" + published["revision"]
                assert result == f"AIOS_SAVED revision={revision(saved)}", result
                command(vm, log, f"read {observed} 0 3", "AIOS_REJECT invalid-read")
                command(vm, log, f"append {revision(original)} 중복", "AIOS_REJECT invalid-edit")
            if boot == 2:
                if model_port is None:
                    result = command(vm, log, f"append {revision(saved)} 전원 중단 검증", "AIOS_SAVED ")
                else:
                    followup = "read_text 도구로 현재 본문을 먼저 읽어 줘. 그런 다음 마지막 줄을 그대로 한 줄 더 추가해 줘."
                    published, followup_trace = edit(vm, log, model_port, followup, observed)
                    successful = [step["mcp_call"]["name"] for step in followup_trace if "mcp_result" in step]
                    assert successful in (["read_text", "append_line"], ["read_text", "append_observed_line"]), followup_trace
                    result = "AIOS_SAVED revision=" + published["revision"]
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
        "followup_instruction": followup, "followup_trace": followup_trace,
        "offline_after_power_loss": disk_text.decode(), "guest_ram_mib": 128,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
