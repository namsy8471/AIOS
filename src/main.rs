use std::{fs, io, path::Path};
#[cfg(target_os = "linux")]
mod agent;
#[cfg(target_os = "linux")]
mod document;
#[cfg(target_os = "linux")]
mod workspace;

struct Editor {
    revision: u64,
    modal_open: bool,
}

impl Editor {
    fn save(&self, observed: u64, document: &Path, contents: &str) -> io::Result<bool> {
        if self.modal_open || self.revision != observed {
            return Ok(false);
        }
        fs::write(document, contents)?;
        Ok(true)
    }
}

fn demo(directory: &Path) -> io::Result<()> {
    let document = directory.join("note.txt");
    let mut editor = Editor {
        revision: 1,
        modal_open: false,
    };
    let observed = editor.revision;
    assert!(editor.save(observed, &document, "first draft")?);
    editor.modal_open = true;
    assert!(!editor.save(observed, &document, "unexpected modal write")?);
    editor.modal_open = false;
    editor.revision += 1;
    assert!(!editor.save(observed, &document, "stale write")?);
    assert_eq!(fs::read_to_string(document)?, "first draft");
    println!("AIOS: save verified; modal and stale requests stopped");
    Ok(())
}

fn run_demo() -> io::Result<()> {
    let dir = std::env::temp_dir().join(format!("aios-demo-{}", std::process::id()));
    fs::create_dir(&dir)?;
    let result = demo(&dir);
    let cleanup = fs::remove_dir_all(dir);
    result.and(cleanup)
}

fn main() -> io::Result<std::process::ExitCode> {
    #[cfg(target_os = "linux")]
    if std::process::id() == 1 && Path::new("/etc/aios-document-console").exists() {
        return document_console();
    }
    let mut args = std::env::args_os().skip(1);
    if let Some(command) = args.next() {
        #[cfg(target_os = "linux")]
        if command == "kernel-capabilities" {
            // LANDLOCK_CREATE_RULESET_VERSION queries the ABI without installing a policy.
            let abi = unsafe {
                libc::syscall(
                    libc::SYS_landlock_create_ruleset,
                    std::ptr::null::<u8>(),
                    0usize,
                    1u32,
                )
            };
            let error = (abi < 0)
                .then(|| io::Error::last_os_error().raw_os_error())
                .flatten();
            println!(
                "{}",
                serde_json::json!({
                    "landlock_abi": (abi >= 0).then_some(abi),
                    "query_errno": error,
                    "document_worker_minimum_abi": 3,
                    "meets_abi_minimum": abi >= 3,
                })
            );
            return Ok(std::process::ExitCode::SUCCESS);
        }
        #[cfg(target_os = "linux")]
        if command == "workspace-run" || command == "agent-run" || command == "agent-gui-run" {
            let profile = match command.to_str() {
                Some("agent-run") => Some(agent::Profile::Document),
                Some("agent-gui-run") => Some(agent::Profile::Desktop),
                _ => None,
            };
            return workspace::run(&args.collect::<Vec<_>>(), profile);
        }
        #[cfg(target_os = "linux")]
        if command == "restrict-worker" || command == "restrict-desktop" {
            return agent::exec_worker(&args.collect::<Vec<_>>(), command == "restrict-desktop");
        }
        return Err(io::Error::other(format!("unknown command: {command:?}")));
    }
    #[cfg(target_os = "linux")]
    if std::process::id() == 1 && Path::new("/opt/aios/guest.py").is_file() {
        let status = std::process::Command::new("/usr/bin/python3")
            .arg("/opt/aios/guest.py")
            .status();
        match status {
            Ok(code) if code.success() => println!("AIOS_RUNTIME_STOPPED"),
            other => eprintln!("AIOS runtime failed: {other:?}"),
        }
        unsafe {
            libc::sync();
            libc::reboot(libc::RB_POWER_OFF);
        }
        return Err(io::Error::last_os_error());
    }
    run_demo()?;
    #[cfg(target_os = "linux")]
    if std::process::id() == 1 {
        if cfg!(target_arch = "aarch64") {
            measure_guest_edits()?;
        }
        verify_guest_policy()?;
        println!("AIOS_BOOT_OK pid=1");
        unsafe extern "C" {
            fn reboot(cmd: std::ffi::c_int) -> std::ffi::c_int;
        }
        // Linux LINUX_REBOOT_CMD_POWER_OFF, called only by the guest init.
        unsafe { reboot(0x4321fedc) };
        return Err(io::Error::last_os_error());
    }
    Ok(std::process::ExitCode::SUCCESS)
}

#[cfg(target_os = "linux")]
fn document_page(text: &str, revision: &str, request: &str) -> Option<serde_json::Value> {
    let mut fields = request.split_whitespace();
    let requested = fields.next()?;
    let offset = fields.next()?.parse::<usize>().ok()?;
    let limit = fields.next()?.parse::<usize>().ok()?;
    if requested != revision || !(1..=512).contains(&limit) || fields.next().is_some() {
        return None;
    }
    let remaining = text.get(offset..)?;
    let length = remaining
        .char_indices()
        .nth(limit)
        .map_or(remaining.len(), |(index, _)| index);
    let end = offset + length;
    Some(serde_json::json!({
        "revision": revision,
        "text": &remaining[..length],
        "next_byte": (end < text.len()).then_some(end),
    }))
}

#[cfg(target_os = "linux")]
fn document_console() -> io::Result<std::process::ExitCode> {
    use sha2::{Digest, Sha256};
    use std::io::BufRead;
    let path = Path::new("/work/note.txt");
    let staged = Path::new("/work/.aios-note-staging");
    println!("AIOS_DOCUMENT_READY pid=1");
    for request in io::stdin().lock().lines() {
        let line = request?;
        if line == "poweroff" {
            unsafe {
                libc::sync();
                libc::reboot(libc::RB_POWER_OFF);
            }
            return Err(io::Error::last_os_error());
        }
        if line == "memory" {
            match guest_memory() {
                Ok(report) => println!("AIOS_MEMORY {report}"),
                Err(error) => println!("AIOS_REJECT memory-unavailable {error}"),
            }
            continue;
        }
        if line == "kernel-capabilities" {
            std::process::Command::new("/init")
                .arg("kernel-capabilities")
                .status()?;
            continue;
        }
        let original = fs::read_to_string(path)?;
        let observed = format!("{:x}", Sha256::digest(original.as_bytes()));
        if line == "inspect" {
            println!("AIOS_DOCUMENT revision={observed} bytes={}", original.len());
            continue;
        }
        if let Some(request) = line.strip_prefix("read ") {
            match document_page(&original, &observed, request) {
                Some(page) => println!("AIOS_PAGE {page}"),
                None => println!("AIOS_REJECT invalid-read"),
            }
            continue;
        }
        let Some((revision, text)) = line.strip_prefix("append ").and_then(|r| r.split_once(' '))
        else {
            println!("AIOS_REJECT invalid-request");
            continue;
        };
        if revision != observed
            || text.is_empty()
            || text.len() > 8192
            || text.contains(['\0', '\r'])
        {
            println!("AIOS_REJECT invalid-edit");
            continue;
        }
        let addition = if original.is_empty() || original.ends_with('\n') {
            text.to_owned()
        } else {
            format!("\n{text}")
        };
        let mut hash = Sha256::new();
        hash.update(original.as_bytes());
        hash.update(addition.as_bytes());
        let expected = format!("{:x}", hash.finalize());
        // This console owns the workspace and reserves the staging filename.
        fs::write(staged, &original)?;
        let status = std::process::Command::new("/init")
            .args([
                "restrict-worker",
                "--aios-edit",
                ".aios-note-staging",
                &observed,
                &original.len().to_string(),
                "0",
                &addition,
                &expected,
            ])
            .status()?;
        if !status.success() {
            fs::remove_file(staged)?;
            println!("AIOS_REJECT worker-error");
            continue;
        }
        fs::File::open(staged)?.sync_all()?;
        fs::rename(staged, path)?;
        fs::File::open("/work")?.sync_all()?;
        println!("AIOS_SAVED revision={expected}");
    }
    Err(io::Error::other("Document console lost its input"))
}

#[cfg(target_os = "linux")]
fn guest_memory() -> io::Result<serde_json::Value> {
    fn kib(report: &str, key: &str) -> io::Result<u64> {
        report
            .lines()
            .find_map(|line| {
                let value = line.strip_prefix(key)?.strip_suffix(" kB")?;
                value.trim().parse().ok()
            })
            .ok_or_else(|| io::Error::other(format!("missing memory counter {key}")))
    }
    let system = fs::read_to_string("/proc/meminfo")?;
    let process = fs::read_to_string("/proc/self/status")?;
    Ok(serde_json::json!({
        "total_kib": kib(&system, "MemTotal:")?,
        "available_kib": kib(&system, "MemAvailable:")?,
        "init_rss_kib": kib(&process, "VmRSS:")?,
    }))
}

#[cfg(target_os = "linux")]
fn measure_guest_edits() -> io::Result<()> {
    use sha2::{Digest, Sha256};
    use std::process::Command;
    use std::time::Instant;

    let path = Path::new("/work/arm64-note.txt");
    let mut expected = String::from("작업 기록");
    fs::write(path, &expected)?;
    let mut samples = Vec::new();
    for index in 1..=20 {
        let line = format!("\n검토 완료 {index}");
        let start = Instant::now();
        let observed = format!("{:x}", Sha256::digest(expected.as_bytes()));
        let offset = expected.len().to_string();
        expected.push_str(&line);
        let revision = format!("{:x}", Sha256::digest(expected.as_bytes()));
        let status = Command::new("/init")
            .args([
                "restrict-worker",
                "--aios-edit",
                "arm64-note.txt",
                &observed,
                &offset,
                "0",
                &line,
                &revision,
            ])
            .status()?;
        if !status.success() || fs::read(path)? != expected.as_bytes() {
            return Err(io::Error::other("ARM64 worker edit failed verification"));
        }
        samples.push(start.elapsed().as_micros());
    }
    // No other children have been launched by the minimal init at this point.
    // Linux reports the largest individual child's peak RSS in KiB.
    let mut usage = std::mem::MaybeUninit::uninit();
    if unsafe { libc::getrusage(libc::RUSAGE_CHILDREN, usage.as_mut_ptr()) } != 0 {
        return Err(io::Error::last_os_error());
    }
    let peak = unsafe { usage.assume_init() }.ru_maxrss;
    println!("AIOS_ARM64_EDITS samples_us={samples:?} peak_worker_rss_kib={peak}");
    fs::remove_file(path)?;
    Ok(())
}

#[cfg(target_os = "linux")]
fn verify_guest_policy() -> io::Result<()> {
    // Run the same document operation on both sides of the filesystem grant.
    let worker = |directory: &str| {
        std::process::Command::new("/init")
            .args(["restrict-worker", "/usr/bin/aios"])
            .env("TMPDIR", directory)
            .output()
    };
    let allowed = worker("/work")?;
    if !allowed.status.success() {
        return Err(io::Error::other(
            String::from_utf8_lossy(&allowed.stderr).into_owned(),
        ));
    }
    let denied = worker("/tmp")?;
    if denied.status.success()
        || !String::from_utf8_lossy(&denied.stderr).contains("Permission denied")
    {
        return Err(io::Error::other(
            "expected the guest kernel to deny the second write",
        ));
    }
    println!("AIOS_GUEST_POLICY_OK allowed=/work denied=/tmp");
    Ok(())
}

#[cfg(test)]
mod tests {
    #[cfg(target_os = "linux")]
    #[test]
    #[ignore = "requires GTK 3, AT-SPI2 and a graphical D-Bus session"]
    fn gtk_modal_blocks_save() -> std::io::Result<()> {
        use std::io::{BufRead, BufReader, Write};
        use std::process::{Command, Stdio};

        let mut observer = Command::new("python3")
            .arg("tests/gtk_observer.py")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()?;
        let mut observations = BufReader::new(observer.stdout.take().unwrap()).lines();
        let dir = std::env::temp_dir().join(format!("aios-gtk-{}", std::process::id()));
        std::fs::create_dir(&dir)?;
        let file = dir.join("document.txt");
        for (expected, contents) in [("ready", "original"), ("modal", "unwanted write")] {
            let state = observations.next().expect("observer exited")?;
            assert_eq!(state, expected);
            let editor = super::Editor {
                revision: 1,
                modal_open: state == "modal",
            };
            assert_eq!(editor.save(1, &file, contents)?, expected == "ready");
            if expected == "ready" {
                writeln!(observer.stdin.as_mut().unwrap(), "open")?;
            }
        }
        assert!(observer.wait()?.success());
        assert_eq!(std::fs::read_to_string(&file)?, "original");
        std::fs::remove_dir_all(dir)?;
        Ok(())
    }

    #[test]
    fn save_contract() {
        super::run_demo().unwrap();
    }
}
