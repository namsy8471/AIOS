//! Diskless PID 1 for the unsigned Flip4 board diagnostics ramdisk.
use crate::{hardware, mount_virtual_fs};
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

fn scope(tree: &Path) -> &'static str {
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

fn probe() -> io::Result<bool> {
    mount_virtual_fs(c"proc", c"/proc")?;
    mount_virtual_fs(c"sysfs", c"/sys")?;
    let qemu_opt_in = fs::read_to_string("/proc/cmdline")?
        .split_ascii_whitespace()
        .any(|arg| arg == "aios.qemu_flip4_probe=1");
    let tree = Path::new("/sys/firmware/devicetree/base");
    let scope = scope(tree);
    let model = fs::read(tree.join("model")).ok().map(|raw| {
        String::from_utf8_lossy(&raw)
            .trim_end_matches('\0')
            .to_owned()
    });
    emit("BOARD", json!({"scope":scope, "model":model}));
    let load_drivers = scope == "cape_flip4_candidate" || (scope == "qemu_virt" && qemu_opt_in);
    let loader = load_drivers.then(|| Command::new("/usr/bin/flip4-driver-loader").status());
    let (exit_code, error) = match loader {
        Some(Ok(status)) => (status.code(), None),
        Some(Err(error)) => (None, Some(error.to_string())),
        None => (None, None),
    };
    emit(
        "MODULES",
        json!({"attempted":load_drivers, "exit_code":exit_code, "error":error}),
    );
    // Keep console records separate so a long device list cannot hide the scope.
    emit("DISPLAY", hardware::display_capabilities()?);
    emit("DEVICES", hardware::device_numbers()?);
    emit("DONE", json!({"scope":scope}));
    // Tests may request poweroff. A physical diagnostic keeps PID 1 resident.
    Ok(qemu_opt_in && scope == "qemu_virt")
}

pub fn run() -> ! {
    match probe() {
        Ok(true) => unsafe {
            libc::reboot(libc::RB_POWER_OFF);
            emit("ERROR", json!(io::Error::last_os_error().to_string()));
        },
        Ok(false) => (),
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
