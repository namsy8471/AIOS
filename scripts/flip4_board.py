"""Merge and inspect the public CAPE device tree for the observed Flip4 board."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess

from flip4_fdt import nodes, trees


DTB_INDEX = 0
DTBO_INDEX = 9
SOC_ID = 530
BOARD_REVISION = 13
PROVIDERS = {
    "qcom,i2c-geni": "i2c-msm-geni.ko",
    "qcom,ufs-phy-qmp-v4-cape": "phy-qcom-ufs-qmp-v4-cape.ko",
    "qcom,cape-gcc": "gcc-waipio.ko",
    "qcom,cape-dispcc": "dispcc-waipio.ko",
    "qcom,cape-pinctrl": "pinctrl-cape.ko",
}


def overlay_at(image, index):
    # Android DT table v0 uses big-endian headers and uncompressed entries.
    if len(image) < 32:
        raise ValueError("truncated recovery DTBO table")
    magic, size, header_size, entry_size, count, offset, _, version = struct.unpack_from(">8I", image)
    end = offset + count * entry_size
    if (magic != 0xD7B7AB1E or version != 0 or size != len(image)
            or not 32 <= header_size <= offset or entry_size < 32 or not 0 <= index < count or end > size):
        raise ValueError("invalid recovery DTBO table or overlay index")
    length, start = struct.unpack_from(">2I", image, offset + index * entry_size)
    if length < 40 or start < end or start + length > size:
        raise ValueError("invalid recovery DTBO entry bounds")
    overlay = image[start:start + length]
    if struct.unpack_from(">2I", overlay) != (0xD00DFEED, length):
        raise ValueError("recovery DTBO entry is not a complete FDT")
    return overlay


def strings(value):
    return value.rstrip(b"\0").decode().split("\0")


def cells(value):
    return [cell for cell, in struct.iter_unpack(">I", value)]


def check_identity(base, overlay):
    base_root = dict(nodes(base))[""]
    overlay_root = dict(nodes(overlay))[""]
    for root in (base_root, overlay_root):
        if ("qcom,cape" not in strings(root["compatible"])
                or SOC_ID not in cells(root["qcom,msm-id"])[::2]):
            raise ValueError("selected device tree does not describe CAPE SoC 530")
    low, = cells(overlay_root["dtbo-hw_rev"])
    high, = cells(overlay_root["dtbo-hw_rev_end"])
    if not low <= BOARD_REVISION <= high:
        raise ValueError(f"selected overlay does not cover revision {BOARD_REVISION}")
    return [low, high]


def describe(tree, order):
    entries = dict(nodes(tree))
    phandles = {props["phandle"]: path for path, props in entries.items() if "phandle" in props}

    def node(path, compatible=None, module=None):
        props = entries[path]
        for ancestor, parent in entries.items():
            if (path == ancestor or path.startswith(ancestor + "/")) and parent.get("status") not in (
                None, b"ok\0", b"okay\0",
            ):
                raise ValueError(f"{path} is unavailable because of status on {ancestor or '/'}")
        matches = strings(props.get("compatible", b"")) if "compatible" in props else []
        if compatible and compatible not in matches:
            raise ValueError(f"{path} does not declare {compatible}")
        result = {"path": path, "compatible": matches, "status": strings(props.get("status", b"okay\0"))[0]}
        if module:
            if module not in order:
                raise ValueError(f"{module} for {path} is absent from the driver archive order")
            result["module"] = module
        return result

    kms = "/soc/qcom,mdss_mdp@ae00000"
    display = node(kms, "qcom,sde-kms", "msm_drm.ko")
    display["outputs"] = {}
    for role in ("primary", "secondary"):
        path = f"/soc/qcom,dsi-display-{role}"
        output = node(path, "qcom,dsi-display")
        props = entries[path]
        if phandles[props["qcom,mdp"]] != kms:
            raise ValueError(f"{path} does not reference the expected display controller")
        panel = phandles[props["qcom,dsi-default-panel"]]
        output["default_panel"] = node(panel)
        label, = strings(entries[panel]["label"])
        output["default_panel"]["label"] = label
        config = node(f"{kms}/{label}")
        if strings(entries[config["path"]]["qcom,display-type"]) != [role]:
            raise ValueError(f"{label} is not configured for the {role} display")
        output["panel_configuration"] = config["path"]
        display["outputs"][role] = output

    touch = {}
    for role, path, compatible, module, firmware in (
        ("inner", "/soc/i2c@a80000/touchscreen@49", "stm,stm_ts", "fst2ca78y_i2c.ko", "sec,firmware_name"),
        ("cover", "/soc/i2c@984000/touchscreen@20", "zinitix,ztw522", "zinitix_ts.ko", "zinitix,firmware_name"),
    ):
        chip = node(path, compatible, module)
        chip["firmware"], = strings(entries[path][firmware])
        chip["bus"] = node(path.rsplit("/", 1)[0], "qcom,i2c-geni", PROVIDERS["qcom,i2c-geni"])
        touch[role] = chip

    host = "/soc/ufshc@1d84000"
    ufs = node(host, "qcom,ufshc", "ufs_qcom.ko")
    phy = phandles[entries[host]["phys"]]
    ufs["phy"] = node(phy, "qcom,ufs-phy-qmp-v4-cape", PROVIDERS["qcom,ufs-phy-qmp-v4-cape"])
    if strings(entries["/aliases"]["ufshc1"]) != [host]:
        raise ValueError("ufshc1 does not reference the expected UFS host")

    clocks_and_pins = {}
    for compatible in ("qcom,cape-gcc", "qcom,cape-dispcc", "qcom,cape-pinctrl"):
        path, = [path for path, props in entries.items()
                 if compatible in strings(props.get("compatible", b""))]
        clocks_and_pins[compatible] = node(path, compatible, PROVIDERS[compatible])

    return {"display": display, "touch": touch, "ufs": ufs, "clock_and_pin_providers": clocks_and_pins}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", type=Path, help="directory produced by unpack_bootimg")
    parser.add_argument("module_order", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        base = list(trees((args.payload / "dtb").read_bytes()))[DTB_INDEX]
        overlay = overlay_at((args.payload / "recovery_dtbo").read_bytes(), DTBO_INDEX)
        revisions = check_identity(base, overlay)
        order = args.module_order.read_text().splitlines()
        args.output.mkdir(parents=True, exist_ok=True)
        paths = {name: args.output / name for name in ("base.dtb", "overlay.dtbo", "merged.dtb")}
        paths["base.dtb"].write_bytes(base)
        paths["overlay.dtbo"].write_bytes(overlay)
        subprocess.run(["fdtoverlay", "-i", paths["base.dtb"], "-o", paths["merged.dtb"], paths["overlay.dtbo"]],
                       check=True)
        report = {
            "scope": "offline_community_reference",
            "selection": {"soc_id": SOC_ID, "board_revision": BOARD_REVISION, "dtb_index": DTB_INDEX,
                          "dtbo_index": DTBO_INDEX, "overlay_board_revisions": revisions},
            "sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()},
            "devices": describe(paths["merged.dtb"].read_bytes(), order),
            "driver_module_count": len(order),
            "driver_order_sha256": hashlib.sha256(args.module_order.read_bytes()).hexdigest(),
        }
        (args.output / "board.json").write_text(json.dumps(report, indent=2) + "\n")
    except (OSError, ValueError, KeyError, IndexError, struct.error, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Flip4 board inspection failed: {error}\n")


if __name__ == "__main__":
    main()
