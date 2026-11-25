"""Run the native benchmark from an installed AIOS probe APK on a Flip4."""
import argparse
import json
from pathlib import Path
import re
import shlex
import statistics
import subprocess


PROMPT = (
    "<|im_start|>system\nExtract the exact text to append from the Korean memo request. "
    "Return one JSON object with tool append_line and line. No markdown. "
    'Example: 메모에 사과를 적어줘 -> {"tool":"append_line","line":"사과"}<|im_end|>\n'
    "<|im_start|>user\n메모에 '우유'를 적어줘.<|im_end|>\n<|im_start|>assistant\n"
)


def parse(stdout, requests):
    result = {"requests": []}
    for line in stdout.splitlines():
        tag, *fields = line.split("\t")
        if tag == "SETUP":
            threads, batch_threads, load, context = map(int, fields)
            result.update(threads=threads, batch_threads=batch_threads, load_us=load, context_us=context)
        elif tag == "REQUEST":
            index, total, prefill, generation, tokens = map(int, fields[:-1])
            text = bytes.fromhex(fields[-1]).decode(errors="replace")
            try:
                correct = json.loads(text) == {"tool": "append_line", "line": "우유"}
            except ValueError:
                correct = False
            row = dict(index=index, total_us=total, prefill_us=prefill,
                       generation_us=generation, tokens=tokens, correct=correct)
            if not correct:
                row["output"] = text
            result["requests"].append(row)
        elif tag == "RSS":
            result["peak_rss_kib"] = int(fields[0])
    times = [row["total_us"] for row in result["requests"]]
    if len(times) != requests:
        raise ValueError(f"Expected {requests} requests, got {len(times)}")
    result["all_correct"] = all(row["correct"] for row in result["requests"])
    result["first_preview_us"] = result["load_us"] + result["context_us"] + times[0]
    if len(times) > 1:
        result["retained_median_us"] = statistics.median(times[1:])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--threads", type=int, nargs="+", default=[0, 2, 6, 8, 0])
    parser.add_argument("--gpu-layers", type=int, default=0)
    parser.add_argument("--opencl", action="store_true", help="resolve the phone's vendor OpenCL library")
    parser.add_argument("--requests", type=int, default=4)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    adb = [args.adb, "-d", "shell"]

    def shell(*command):
        return subprocess.check_output(adb + list(command), timeout=15).decode().strip()

    if shell("getprop", "ro.product.model") != "SM-F721N":
        raise RuntimeError("Expected Galaxy Z Flip4 SM-F721N")
    package = "org.aios.mobile"
    installed = shell("pm", "path", package)
    if not re.fullmatch(r"package:/data/app/~~[-\w=]+/org\.aios\.mobile-[-\w=]+/base\.apk", installed):
        raise RuntimeError("Unexpected probe APK path")
    runner = installed.removeprefix("package:").removesuffix("/base.apk") + "/lib/arm64/libllama-bench.so"

    def temperature():
        match = re.search(r"temperature:\s*(\d+)", shell("dumpsys", "battery"))
        return int(match[1]) / 10 if match else None

    proof = {"device": "SM-F721N", "gpu_layers_requested": args.gpu_layers, "results": []}
    for threads in args.threads:
        before = temperature()
        invocation = [runner, "files/model-large.gguf", str(threads), str(args.gpu_layers), str(args.requests)]
        if args.opencl:
            invocation = ["sh", "-c", "LD_LIBRARY_PATH=/vendor/lib64 exec " + shlex.join(invocation)]
        command = adb + ["-T", shlex.join(["run-as", package, *invocation])]
        proc = subprocess.run(command, input=PROMPT.encode(), capture_output=True, timeout=180)
        logs = proc.stderr.decode(errors="replace")
        log_file = args.output.with_suffix(f".{len(proof['results'])}.log")
        log_file.write_text(logs, encoding="utf-8")
        proc.check_returncode()
        result = parse(proc.stdout.decode(), args.requests)
        offload = re.search(r"offloaded (\d+)/(\d+) layers", logs)
        result["offloaded_layers"] = int(offload[1]) if offload else 0
        if args.gpu_layers and not result["offloaded_layers"]:
            raise RuntimeError("GPU requested but no layers were offloaded")
        result.update(requested_threads=threads, battery_c_before=before, battery_c_after=temperature())
        proof["results"].append(result)
        args.output.write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
        print(f"threads={result['threads']} first={result['first_preview_us']/1000:.0f} ms "
              f"retained={result.get('retained_median_us', 0)/1000:.0f} ms "
              f"offloaded={result['offloaded_layers']} correct={result['all_correct']} "
              f"battery={before}->{result['battery_c_after']} °C", flush=True)
    if not all(result["all_correct"] for result in proof["results"]):
        raise SystemExit("Incorrect proposal in benchmark output")


if __name__ == "__main__":
    main()
