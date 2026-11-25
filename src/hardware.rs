//! Read the Linux device inventory without opening graphics or input devices.
use serde_json::{Value, json};
use std::{
    fs, io,
    os::unix::fs::{FileTypeExt, MetadataExt},
    path::Path,
};

fn entries(root: &str) -> io::Result<Vec<fs::DirEntry>> {
    let mut items = match fs::read_dir(root) {
        Ok(items) => items.collect::<io::Result<Vec<_>>>()?,
        Err(error) if error.kind() == io::ErrorKind::NotFound => Vec::new(),
        Err(error) => return Err(error),
    };
    items.sort_by_key(fs::DirEntry::file_name);
    Ok(items)
}

fn text(path: &Path) -> Option<String> {
    fs::read_to_string(path)
        .ok()
        .map(|value| value.trim().to_owned())
}

fn driver(path: &Path) -> Option<String> {
    fs::read_link(path)
        .ok()?
        .file_name()?
        .to_str()
        .map(str::to_owned)
}

pub fn display_capabilities() -> io::Result<Value> {
    let mut cards = Vec::new();
    let mut connectors = Vec::new();
    for entry in entries("/sys/class/drm")? {
        let file_name = entry.file_name();
        let Some(name) = file_name.to_str() else {
            continue;
        };
        let Some(card) = name.strip_prefix("card") else {
            continue;
        };
        let path = entry.path();
        if !card.is_empty() && card.bytes().all(|byte| byte.is_ascii_digit()) {
            cards.push(json!({"name":name,"driver":driver(&path.join("device/driver"))}));
        } else if card.split_once('-').is_some_and(|(index, _)| {
            !index.is_empty() && index.bytes().all(|byte| byte.is_ascii_digit())
        }) {
            connectors.push(json!({"name":name,"status":text(&path.join("status")),
                "modes":text(&path.join("modes")).map(|modes| modes.lines().map(str::to_owned).collect::<Vec<_>>())}));
        }
    }
    let mut touchscreens = Vec::new();
    let mut absolute_inputs = Vec::new();
    for entry in entries("/sys/class/input")? {
        let device = entry.path().join("device");
        if !entry.file_name().to_string_lossy().starts_with("event") {
            continue;
        }
        if let Some(name) = text(&device.join("name")) {
            let input = json!({"event":entry.file_name().to_string_lossy(),"name":name,
                "driver":driver(&device.join("device/driver"))});
            if name.contains("touchscreen") {
                touchscreens.push(input.clone());
            }
            if text(&device.join("capabilities/abs")).is_some_and(|bits| {
                bits.bytes()
                    .any(|byte| byte.is_ascii_hexdigit() && byte != b'0')
            }) {
                absolute_inputs.push(input);
            }
        }
    }
    Ok(
        json!({"drm_cards":cards,"drm_connectors":connectors,"touchscreens":touchscreens,
        "absolute_inputs":absolute_inputs}),
    )
}

/// Report kernel-assigned device numbers without opening the device nodes.
pub fn device_numbers() -> io::Result<Value> {
    let mut report = serde_json::Map::new();
    for (kind, class, prefix) in [
        ("drm", "/sys/class/drm", "/dev/dri"),
        ("input", "/sys/class/input", "/dev/input"),
        ("block", "/sys/class/block", "/dev"),
    ] {
        let mut devices = Vec::new();
        for entry in entries(class)? {
            let Some((major, minor)) = device_number(&entry.path()) else {
                continue;
            };
            if let Some(name) = entry.file_name().to_str() {
                devices
                    .push(json!({"path":format!("{prefix}/{name}"), "major":major, "minor":minor}));
            }
        }
        report.insert(kind.to_owned(), Value::Array(devices));
    }
    Ok(Value::Object(report))
}

fn device_number(sysfs: &Path) -> Option<(u32, u32)> {
    let numbers = text(&sysfs.join("dev"))?;
    let (major, minor) = numbers.split_once(':')?;
    Some((major.parse().ok()?, minor.parse().ok()?))
}

/// Populate the display device nodes when the initramfs has no devtmpfs.
pub fn prepare_display_nodes() -> io::Result<()> {
    for (class, output, prefix) in [
        ("/sys/class/drm", "/dev/dri", "card"),
        ("/sys/class/input", "/dev/input", "event"),
    ] {
        fs::create_dir_all(output)?;
        for entry in entries(class)? {
            let name = entry.file_name();
            let Some(index) = name.to_str().and_then(|name| name.strip_prefix(prefix)) else {
                continue;
            };
            if index.is_empty() || !index.bytes().all(|byte| byte.is_ascii_digit()) {
                continue;
            }
            let Some((major, minor)) = device_number(&entry.path()) else {
                continue;
            };
            let path = Path::new(output).join(name);
            let number = libc::makedev(major, minor);
            match fs::symlink_metadata(&path) {
                Ok(info) if info.file_type().is_char_device() && info.rdev() == number => continue,
                Ok(_) => {
                    return Err(io::Error::other(format!(
                        "invalid device node {}",
                        path.display()
                    )));
                }
                Err(error) if error.kind() == io::ErrorKind::NotFound => {}
                Err(error) => return Err(error),
            }
            let path = std::ffi::CString::new(path.as_os_str().as_encoded_bytes())?;
            if unsafe { libc::mknod(path.as_ptr(), libc::S_IFCHR | 0o600, number) } != 0 {
                return Err(io::Error::last_os_error());
            }
        }
    }
    Ok(())
}
