"""Run the AIOS debug APK's engine checks on an authorized USB Flip4."""
import argparse
from base64 import b64decode
from hashlib import file_digest
import json
from pathlib import Path
import subprocess


PACKAGE = "org.aios.mobile"
PORT = "tcp:18120"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    adb = [args.adb, "-d"]

    def call(*command, timeout=20):
        result = subprocess.run(adb + list(command), capture_output=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors="replace") or result.stdout.decode(errors="replace"))
        return result.stdout.decode().strip()

    def copy_app_file(source, destination):
        stage = call("shell", "mktemp", "-d", "/data/local/tmp/aios-mobile-XXXXXXXX")
        if not stage.startswith("/data/local/tmp/aios-mobile-") or not stage.rpartition("-")[2].isalnum():
            raise RuntimeError("Unexpected phone scratch directory")
        try:
            call("push", str(source), f"{stage}/payload", timeout=180)
            call("shell", "-T", f"cat {stage}/payload | run-as {PACKAGE} sh -c 'cat > {destination}'", timeout=180)
        finally:
            call("shell", "rm", "-f", f"{stage}/payload")
            call("shell", "rmdir", stage)

    def probe(mode):
        output = call("shell", "am", "instrument", "-w", "-e", "mode", mode,
                      f"{PACKAGE}/.MobileProbe", timeout=160)
        for line in output.splitlines():
            if line.startswith("INSTRUMENTATION_RESULT: aios_proof="):
                return json.loads(b64decode(line.partition("=")[2]))
        raise RuntimeError(output)

    model = call("shell", "getprop", "ro.product.model")
    if model != "SM-F721N":
        raise RuntimeError(f"Expected the authorized Galaxy Z Flip4, got {model}")
    call("shell", "run-as", PACKAGE, "mkdir", "-p", "files/probe")
    call("shell", "run-as", PACKAGE, "rm", "-f", "files/probe/memo.txt", "files/probe/draft.md")
    with args.weights.open("rb") as source:
        expected = file_digest(source, "sha256").hexdigest()
        installed = call("shell", "run-as", PACKAGE, "sh", "-c",
                         "'if [ -f files/model.gguf ]; then sha256sum files/model.gguf; fi'")
        if not installed.startswith(f"{expected} "):
            copy_app_file(args.weights, "files/model.gguf.incoming")
            transferred = call("shell", "run-as", PACKAGE, "sha256sum", "files/model.gguf.incoming")
            if not transferred.startswith(f"{expected} "):
                raise RuntimeError("Model bytes changed in transit")
            call("shell", "run-as", PACKAGE, "mv", "files/model.gguf.incoming", "files/model.gguf")

    airplane = call("shell", "settings", "get", "global", "airplane_mode_on")
    if airplane not in {"0", "1"}:
        raise RuntimeError("Unknown initial airplane mode")
    try:
        if airplane == "0":
            call("shell", "cmd", "connectivity", "airplane-mode", "enable")
        if call("shell", "settings", "get", "global", "airplane_mode_on") != "1":
            raise RuntimeError("Airplane mode did not turn on")
        local = probe("local")
        call("shell", "am", "force-stop", PACKAGE)
        restored = probe("verify")
    finally:
        if airplane == "0":
            call("shell", "cmd", "connectivity", "airplane-mode", "disable")
    for name in ("memo", "revision"):
        if local[name] != restored[name]:
            raise RuntimeError("Memo changed after process restart")

    mappings = [line.split()[-2:] for line in call("reverse", "--list").splitlines()]
    if any(pair[0] == PORT and pair != [PORT, PORT] for pair in mappings):
        raise RuntimeError("ADB port already belongs to another mapping")
    created = [PORT, PORT] not in mappings
    if created:
        call("reverse", PORT, PORT)
    try:
        copy_app_file(args.token_file, "files/probe/pairing.token")
        remote = probe("pc")
    finally:
        if created:
            call("reverse", "--remove", PORT)
        call("shell", "run-as", PACKAGE, "rm", "-f", "files/probe/pairing.token")

    proof = {"device": model, "scope": "android_app_engine_instrumentation", "model_sha256": expected,
             "airplane_mode_checked": True, "local": local, "restored_after_force_stop": restored,
             "windows_over_usb": remote}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(proof, ensure_ascii=True))


if __name__ == "__main__":
    main()
