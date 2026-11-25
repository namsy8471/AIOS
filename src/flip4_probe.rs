//! Diskless PID 1 for the unsigned Flip4 board diagnostics ramdisk.
use crate::{hardware, mount_virtual_fs, pmsg};
use serde_json::json;
use std::{fs, io, io::Write, path::Path, process::Command};

fn emit(name: &str, value: serde_json::Value) {
    let line = format!("AIOS_FLIP4_{name} {value}");
    let _ = writeln!(io::stdout().lock(), "{line}");
    if let Ok(mut log) = fs::OpenOptions::new().write(true).open("/dev/kmsg") {
        const MAX_PAYLOAD: usize = 720;
        if line.len() <= MAX_PAYLOAD {
            let _ = log.write_all(format!("<6>{line}\n").as_bytes());
        } else {
            let mut remaining = line.as_str();
            let mut part = 1;
            while !remaining.is_empty() {
                let mut end = remaining.len().min(MAX_PAYLOAD);
                while !remaining.is_char_boundary(end) {
                    end -= 1;
                }
                let (chunk, rest) = remaining.split_at(end);
                let record = format!("<6>AIOS_FLIP4_{name} part={part} {chunk}\n");
                let _ = log.write_all(record.as_bytes());
                remaining = rest;
                part += 1;
            }
        }
    }
}

const FLIP4_NODES: [&str; 4] = [
    "soc/i2c@a80000/touchscreen@49",
    "soc/i2c@984000/touchscreen@20",
    "soc/qcom,dsi-display-primary",
    "soc/ufshc@1d84000",
];

pub(crate) fn scope(tree: &Path) -> &'static str {
    let compatible = fs::read(tree.join("compatible")).unwrap_or_default();
    let mut compatibles = compatible.split(|byte| *byte == 0);
    if compatibles
        .clone()
        .any(|value| value == b"linux,dummy-virt")
    {
        return "qemu_virt";
    }
    if compatibles.any(|value| value == b"qcom,cape")
        && fs::read(tree.join("qcom,msm-id")).is_ok_and(|ids| {
            ids.chunks_exact(8)
                .any(|entry| entry[..4] == 530u32.to_be_bytes())
        })
        && FLIP4_NODES.iter().all(|node| tree.join(node).is_dir())
    {
        return "cape_flip4_candidate";
    }
    "unmatched"
}

const SNAPSHOT_PREFIX: &str = "AIOS_FLIP4_SNAPSHOT ";

fn persist(snapshot: &serde_json::Value) -> io::Result<()> {
    let mut device = pmsg::open()?;
    let text = snapshot.to_string();
    let mut remaining = text.as_str();
    let mut index = 0;
    while !remaining.is_empty() {
        let mut end = remaining.len().min(600);
        while !remaining.is_char_boundary(end) {
            end -= 1;
        }
        let (chunk, rest) = remaining.split_at(end);
        let record = format!(
            "{SNAPSHOT_PREFIX}{}",
            json!({"index":index, "last":rest.is_empty(), "data":chunk})
        );
        device.write_all(&pmsg::frame(record.as_bytes())?)?;
        remaining = rest;
        index += 1;
    }
    Ok(())
}

fn read_previous() -> io::Result<Option<serde_json::Value>> {
    mount_virtual_fs(c"pstore", c"/pstore")?;
    let raw = match fs::read("/pstore/pmsg-ramoops-0") {
        Ok(raw) => raw,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error),
    };
    let mut text = String::new();
    let mut next = 0;
    for entry in raw.split(|byte| *byte == 0) {
        let Some(record) = entry.strip_prefix(SNAPSHOT_PREFIX.as_bytes()) else {
            continue;
        };
        let part: serde_json::Value = serde_json::from_slice(record)?;
        if part["index"] != next {
            return Err(io::Error::other("pmsg snapshot chunk is out of order"));
        }
        text.push_str(
            part["data"]
                .as_str()
                .ok_or_else(|| io::Error::other("missing pmsg snapshot data"))?,
        );
        next += 1;
        if part["last"] == true {
            return Ok(Some(serde_json::from_str(&text)?));
        }
    }
    Err(io::Error::other(
        "no complete AIOS board snapshot in pstore",
    ))
}

fn probe() -> io::Result<Option<libc::c_int>> {
    mount_virtual_fs(c"proc", c"/proc")?;
    mount_virtual_fs(c"sysfs", c"/sys")?;
    let cmdline = fs::read_to_string("/proc/cmdline")?;
    let qemu_opt_in = cmdline
        .split_ascii_whitespace()
        .any(|arg| arg == "aios.qemu_flip4_probe=1");
    let tree = Path::new("/sys/firmware/devicetree/base");
    let scope = scope(tree);
    let model = fs::read(tree.join("model")).ok().map(|raw| {
        String::from_utf8_lossy(&raw)
            .trim_end_matches('\0')
            .to_owned()
    });
    let board = json!({"scope":scope, "model":model});
    emit("BOARD", board.clone());
    let qemu_pstore = scope == "qemu_virt"
        && cmdline
            .split_ascii_whitespace()
            .any(|arg| arg == "aios.qemu_flip4_pstore=1");
    if qemu_pstore {
        if let Some(previous) = read_previous()? {
            emit("RECOVERED", previous);
            return Ok(Some(libc::RB_POWER_OFF));
        }
    }
    let load_drivers = scope == "cape_flip4_candidate" || (scope == "qemu_virt" && qemu_opt_in);
    // Both recovery touchscreen drivers can update controller firmware on probe.
    let without_touch = scope == "cape_flip4_candidate"
        || (scope == "qemu_virt"
            && cmdline
                .split_ascii_whitespace()
                .any(|arg| arg == "aios.qemu_flip4_without_touch=1"));
    let loader = load_drivers.then(|| {
        let mut command = Command::new("/usr/bin/flip4-driver-loader");
        if without_touch {
            command.arg("--without-touch");
        }
        command.status()
    });
    let (exit_code, error) = match loader {
        Some(Ok(status)) => (status.code(), None),
        Some(Err(error)) => (None, Some(error.to_string())),
        None => (None, None),
    };
    let modules = json!({"attempted":load_drivers, "exit_code":exit_code, "error":error,
        "touch_modules_enabled":load_drivers && !without_touch});
    emit("MODULES", modules.clone());
    let display = hardware::display_capabilities()?;
    let devices = hardware::device_numbers()?;
    emit("DISPLAY", display.clone());
    emit("DEVICES", devices.clone());
    if qemu_pstore || scope == "cape_flip4_candidate" {
        let snapshot =
            json!({"board":board, "modules":modules, "display":display, "devices":devices});
        let result = persist(&snapshot);
        emit(
            "PSTORE",
            json!({"written":result.is_ok(), "error":result.as_ref().err().map(ToString::to_string)}),
        );
        if qemu_pstore {
            result?;
            return Ok(Some(libc::RB_AUTOBOOT));
        }
    }
    emit("DONE", json!({"scope":scope}));
    // A physical diagnostic keeps PID 1 resident.
    Ok((qemu_opt_in && scope == "qemu_virt").then_some(libc::RB_POWER_OFF))
}

pub fn run() -> ! {
    match probe() {
        Ok(Some(action)) => unsafe {
            libc::reboot(action);
            emit("ERROR", json!(io::Error::last_os_error().to_string()));
        },
        Ok(None) => (),
        Err(error) => emit("ERROR", json!(error.to_string())),
    }
    loop {
        unsafe { libc::pause() };
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn classify_only_the_expected_device_tree() -> io::Result<()> {
        let path = std::env::temp_dir().join(format!(
            "aios-test-flip4-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir(&path)?;
        let result = (|| {
            fs::write(path.join("compatible"), b"linux,dummy-virt\0")?;
            assert_eq!(scope(&path), "qemu_virt");
            fs::write(path.join("compatible"), b"qcom,cape\0")?;
            fs::write(path.join("qcom,msm-id"), [0, 0, 2, 18, 0, 1, 0, 0])?;
            assert_eq!(scope(&path), "unmatched");
            for node in FLIP4_NODES {
                fs::create_dir_all(path.join(node))?;
            }
            assert_eq!(scope(&path), "cape_flip4_candidate");
            fs::write(path.join("qcom,msm-id"), [0, 0, 2, 19, 0, 1, 0, 0])?;
            assert_eq!(scope(&path), "unmatched");
            Ok(())
        })();
        let cleanup = fs::remove_dir_all(path);
        result.and(cleanup)
    }
}
