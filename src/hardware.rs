//! Read the Linux device inventory without opening graphics or input devices.
use serde_json::{Value, json};
use std::{fs, io, path::Path};

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
