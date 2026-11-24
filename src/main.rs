use std::{fs, io, path::Path};
#[cfg(target_os = "linux")]
mod agent;
#[cfg(target_os = "linux")]
mod document;
#[cfg(target_os = "linux")]
mod flip4_probe;
#[cfg(target_os = "linux")]
mod hardware;
#[cfg(target_os = "linux")]
mod pmsg;
#[cfg(target_os = "linux")]
mod stream_worker;
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

#[cfg(target_os = "linux")]
fn kernel_capabilities() -> serde_json::Value {
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
    serde_json::json!({
        "landlock_abi": (abi >= 0).then_some(abi),
        "query_errno": error,
        "document_worker_minimum_abi": 3,
        "meets_abi_minimum": abi >= 3,
    })
}

fn main() -> io::Result<std::process::ExitCode> {
    #[cfg(target_os = "linux")]
    if std::process::id() == 1 && Path::new("/etc/aios-flip4-board-probe").is_file() {
        flip4_probe::run();
    }
    #[cfg(target_os = "linux")]
    if std::process::id() == 1 && Path::new("/etc/aios-document-console").exists() {
        if Path::new("/usr/bin/flip4-driver-loader").is_file() {
            load_flip4_reference_drivers()?;
        }
        let model = match guest_model_path() {
            Ok(path) => Some(path),
            Err(error) => {
                eprintln!("AIOS_MODEL_DISK_UNAVAILABLE {error}");
                None
            }
        };
        return document_console(Path::new("/work"), true, model);
    }
    #[cfg(target_os = "linux")]
    if std::process::id() == 1 && Path::new("/aios-boot-probe").is_file() {
        use std::io::Write;
        let report = serde_json::json!({
            "pid": std::process::id(),
            "arch": std::env::consts::ARCH,
            "kernel": kernel_capabilities(),
        });
        let mut log = fs::OpenOptions::new().write(true).open("/dev/kmsg")?;
        // Each write to /dev/kmsg creates a separate kernel log record.
        let record = format!("<4>AIOS_EARLY_INIT {report}\n");
        log.write_all(record.as_bytes())?;
        if Path::new("/aios-pstore-probe").is_file() {
            return probe_pstore(&record);
        }
        unsafe {
            libc::reboot(libc::RB_POWER_OFF);
        }
        return Err(io::Error::last_os_error());
    }
    let mut args = std::env::args_os().skip(1);
    if let Some(command) = args.next() {
        #[cfg(target_os = "linux")]
        if command == "document-console" {
            use std::os::fd::AsRawFd;
            let work = args
                .next()
                .ok_or_else(|| io::Error::other("expected a workspace directory"))?;
            let model = match args.next() {
                None => None,
                Some(flag) if flag == "--model-dir" => {
                    let directory = args
                        .next()
                        .ok_or_else(|| io::Error::other("expected a model directory"))?;
                    if args.next().is_some() || unsafe { libc::geteuid() } == 0 {
                        return Err(io::Error::other(
                            "standalone model mode requires an unprivileged invocation and one model directory",
                        ));
                    }
                    Some(fs::canonicalize(directory)?)
                }
                Some(_) => return Err(io::Error::other("expected optional --model-dir DIRECTORY")),
            };
            let work = Path::new(&work);
            let directory = fs::File::open(work)?;
            if !directory.metadata()?.is_dir() {
                return Err(io::Error::other("expected a workspace directory"));
            }
            if unsafe { libc::flock(directory.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } < 0 {
                return Err(io::Error::last_os_error());
            }
            let result = document_console(work, false, model.as_deref());
            drop(directory);
            return result;
        }
        #[cfg(target_os = "linux")]
        if command == "append-stream-worker" || command == "probe-stream-worker" {
            let addition = args
                .next()
                .and_then(|s| s.into_string().ok())
                .ok_or_else(|| io::Error::other("expected append text"))?;
            stream_worker::worker(&addition, command == "probe-stream-worker")?;
            return Ok(std::process::ExitCode::SUCCESS);
        }
        #[cfg(target_os = "linux")]
        if command == "kernel-capabilities" {
            println!("{}", kernel_capabilities());
            return Ok(std::process::ExitCode::SUCCESS);
        }
        #[cfg(target_os = "linux")]
        if command == "display-capabilities" {
            println!("{}", hardware::display_capabilities()?);
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
fn probe_pstore(record: &str) -> io::Result<std::process::ExitCode> {
    use std::io::Write;
    for (kind, path) in [(c"sysfs", c"/sys"), (c"pstore", c"/pstore")] {
        let flags = libc::MS_NOSUID | libc::MS_NODEV | libc::MS_NOEXEC;
        if unsafe {
            libc::mount(
                kind.as_ptr(),
                path.as_ptr(),
                kind.as_ptr(),
                flags,
                std::ptr::null(),
            )
        } != 0
        {
            return Err(io::Error::last_os_error());
        }
    }
    let message = record.strip_prefix("<4>").unwrap_or(record).as_bytes();
    let message = message.strip_suffix(b"\n").unwrap_or(message);
    let frame = pmsg::frame(message)?;
    match fs::read("/pstore/pmsg-ramoops-0") {
        Ok(previous)
            if previous
                .windows(frame.len())
                .any(|window| window[..10] == frame[..10] && window[18..] == frame[18..]) =>
        {
            println!("AIOS_PSTORE_RECOVERED");
            unsafe { libc::reboot(libc::RB_POWER_OFF) };
        }
        Ok(_) => {
            return Err(io::Error::other(
                "pstore did not contain the AIOS boot record",
            ));
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            pmsg::open()?.write_all(&frame)?;
            println!("AIOS_PSTORE_WRITTEN");
            unsafe { libc::reboot(libc::RB_AUTOBOOT) };
        }
        Err(error) => return Err(error),
    }
    Err(io::Error::last_os_error())
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
fn korean_append(instruction: &str) -> Option<&str> {
    let instruction = instruction.trim().trim_end_matches('.');
    let tail = [
        "장보기 메모에 ",
        "장보기 메모 마지막에 ",
        "메모에 ",
        "메모 끝에 ",
    ]
    .iter()
    .find_map(|prefix| instruction.strip_prefix(prefix))?;
    let quoted = [" 한 줄을 추가해 줘", " 추가해 줘", " 추가해줘"]
        .iter()
        .find_map(|suffix| tail.strip_suffix(suffix))?;
    for (left, right) in [('\'', '\''), ('"', '"'), ('‘', '’')] {
        if let Some(text) = quoted
            .strip_prefix(left)
            .and_then(|s| s.strip_suffix(right))
        {
            if !text.trim().is_empty()
                && !text.contains([left, right])
                && !text.chars().any(char::is_control)
            {
                return Some(text);
            }
        }
    }
    None
}

#[cfg(target_os = "linux")]
fn model_append_text(
    instruction: &str,
    model: &Path,
    guest_init: bool,
    structured: bool,
) -> io::Result<String> {
    use std::io::Read;
    use std::os::unix::process::{CommandExt, ExitStatusExt};
    use std::process::{ExitStatus, Stdio};
    if instruction.len() > 512
        || instruction.chars().any(char::is_control)
        || instruction.contains("<|")
    {
        return Err(io::Error::other("invalid instruction"));
    }
    let system = if structured {
        concat!(
            "Extract the exact text to append from the Korean memo request. ",
            "Return one JSON object with tool append_line and line. No markdown. ",
            "Example: 메모에 사과를 적어줘 -> {\"tool\":\"append_line\",\"line\":\"사과\"}"
        )
    } else {
        concat!(
            "Extract the exact text to append from the Korean memo request. ",
            "Output only that text without quotes. For example: 메모에 사과를 적어줘 -> 사과"
        )
    };
    let prompt = format!(
        "<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{instruction}<|im_end|>\n<|im_start|>assistant\n"
    );
    let started = std::time::Instant::now();
    let mut command = std::process::Command::new(model.join("llama-simple"));
    if guest_init {
        command.uid(65534).gid(65534);
    }
    let mut child = command
        .arg("-m")
        .arg(model.join("model.gguf"))
        .args([
            "-ngl",
            "0",
            "-n",
            if structured { "64" } else { "24" },
            &prompt,
        ])
        .env_clear()
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()?;
    let mut stdout = String::new();
    let read = child.stdout.take().unwrap().read_to_string(&mut stdout);
    let mut status = 0;
    let mut usage = std::mem::MaybeUninit::<libc::rusage>::uninit();
    loop {
        // Reap this exact model process and retrieve its lifetime peak RSS.
        if unsafe { libc::wait4(child.id() as i32, &mut status, 0, usage.as_mut_ptr()) } >= 0 {
            break;
        }
        let err = io::Error::last_os_error();
        if err.kind() != io::ErrorKind::Interrupted {
            return Err(err);
        }
    }
    read?;
    let status = ExitStatus::from_raw(status);
    if !status.success() {
        return Err(io::Error::other(format!("inference failed: {status}")));
    }
    let output = stdout.strip_prefix(&prompt).unwrap_or("").trim();
    let proposal;
    let text = if structured {
        proposal = serde_json::from_str(output).map_err(io::Error::other)?;
        model_proposed_line(&proposal)?
    } else {
        output
    };
    if text.is_empty() || text.chars().any(char::is_control) || !instruction.contains(text) {
        return Err(io::Error::other("model returned no verbatim memo text"));
    }
    let usage = serde_json::json!({
        "inference_ms": started.elapsed().as_millis(),
        "model_peak_rss_kib": unsafe { usage.assume_init() }.ru_maxrss,
    });
    println!("MODEL_USAGE {usage}");
    Ok(text.to_owned())
}

#[cfg(target_os = "linux")]
fn model_proposed_line(proposal: &serde_json::Value) -> io::Result<&str> {
    let fields = proposal.as_object().filter(|fields| {
        fields.len() == 2
            && fields.get("tool").and_then(|tool| tool.as_str()) == Some("append_line")
    });
    fields
        .and_then(|fields| fields.get("line"))
        .and_then(serde_json::Value::as_str)
        .ok_or_else(|| io::Error::other("expected append_line tool and one text line"))
}

#[cfg(all(test, target_os = "linux"))]
#[test]
fn graphical_model_accepts_only_append_line() {
    use serde_json::json;
    assert_eq!(
        model_proposed_line(&json!({"tool":"append_line","line":"우유"})).unwrap(),
        "우유"
    );
    for rejected in [
        json!({"tool":"replace_text","line":"우유"}),
        json!({"tool":"append_line","line":42}),
        json!({"tool":"append_line","line":"우유","revision":"forged"}),
        json!("우유"),
    ] {
        assert!(model_proposed_line(&rejected).is_err(), "{rejected}");
    }
}

#[cfg(target_os = "linux")]
fn load_flip4_reference_drivers() -> io::Result<()> {
    mount_virtual_fs(c"proc", c"/proc")?;
    let cmdline = fs::read_to_string("/proc/cmdline")?;
    if Path::new("/etc/aios-qemu-ramdisk").is_file()
        && cmdline
            .split_ascii_whitespace()
            .any(|arg| arg == "aios.qemu_document_disk=1")
        && cmdline
            .split_ascii_whitespace()
            .any(|arg| arg == "aios.qemu_recovery_drivers=1")
        && std::process::Command::new("/usr/bin/flip4-driver-loader")
            .status()?
            .success()
    {
        return Ok(());
    }
    Err(io::Error::other(
        "reference recovery drivers require a successful QEMU probe boot",
    ))
}

#[cfg(target_os = "linux")]
fn guest_model_path() -> io::Result<&'static Path> {
    if Path::new("/etc/aios-qemu-ramdisk").is_file() {
        if !Path::new("/proc/cmdline").is_file() {
            mount_virtual_fs(c"proc", c"/proc")?;
        }
        let cmdline = fs::read_to_string("/proc/cmdline")?;
        if cmdline
            .split_ascii_whitespace()
            .any(|arg| arg == "aios.qemu_document_disk=1")
            && cmdline
                .split_ascii_whitespace()
                .any(|arg| arg == "aios.qemu_model_partition=1")
        {
            fs::create_dir_all("/model")?;
            mount_document_ext4(
                c"/dev/sda1",
                c"/model",
                libc::MS_RDONLY | libc::MS_NODEV | libc::MS_NOSUID,
                Some(c"noload"),
                true,
            )?;
            println!("AIOS_MODEL_PARTITION_READ_ONLY");
            return Ok(Path::new("/model/opt/model"));
        }
        return Ok(Path::new("/opt/model"));
    }
    if !Path::new("/usr/bin/display-frame").is_file() {
        return Ok(Path::new("/opt/model"));
    }
    if !Path::new("/proc/cmdline").is_file() {
        mount_virtual_fs(c"proc", c"/proc")?;
    }
    if !fs::read_to_string("/proc/cmdline")?
        .split_whitespace()
        .any(|arg| arg == "aios.model_disk=1")
    {
        return Ok(Path::new("/opt/model"));
    }
    if !Path::new("/sys/class").is_dir() {
        mount_virtual_fs(c"sysfs", c"/sys")?;
    }
    if !Path::new("/dev/vdb").exists() {
        let device = fs::read_to_string("/sys/class/block/vdb/dev")?;
        let (major, minor) = device
            .trim()
            .split_once(':')
            .and_then(|(major, minor)| {
                Some((major.parse::<u32>().ok()?, minor.parse::<u32>().ok()?))
            })
            .ok_or_else(|| io::Error::other("invalid model disk device number"))?;
        if unsafe {
            libc::mknod(
                c"/dev/vdb".as_ptr(),
                libc::S_IFBLK | 0o600,
                libc::makedev(major, minor),
            )
        } != 0
        {
            return Err(io::Error::last_os_error());
        }
    }
    fs::create_dir_all("/model")?;
    let flags = libc::MS_RDONLY | libc::MS_NODEV | libc::MS_NOSUID;
    if unsafe {
        libc::mount(
            c"/dev/vdb".as_ptr(),
            c"/model".as_ptr(),
            c"ext4".as_ptr(),
            flags,
            c"noload".as_ptr().cast(),
        )
    } != 0
    {
        return Err(io::Error::last_os_error());
    }
    Ok(Path::new("/model/opt/model"))
}

#[cfg(target_os = "linux")]
fn mount_virtual_fs(kind: &std::ffi::CStr, path: &std::ffi::CStr) -> io::Result<()> {
    let flags = libc::MS_RDONLY | libc::MS_NOSUID | libc::MS_NODEV | libc::MS_NOEXEC;
    if unsafe {
        libc::mount(
            kind.as_ptr(),
            path.as_ptr(),
            kind.as_ptr(),
            flags,
            std::ptr::null(),
        )
    } != 0
    {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}

#[cfg(target_os = "linux")]
struct DisplaySession {
    child: std::process::Child,
    replies: io::BufReader<std::process::ChildStdout>,
}

#[cfg(target_os = "linux")]
impl DisplaySession {
    fn request(session: &mut Option<Self>, text: &str) -> io::Result<i32> {
        use std::io::{BufRead, Write};
        use std::process::{Command, Stdio};

        if session.is_none() {
            let mut child = Command::new("/usr/bin/display-frame")
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .spawn()?;
            let replies = io::BufReader::new(child.stdout.take().expect("piped display output"));
            *session = Some(Self { child, replies });
        }
        let display = session.as_mut().expect("display session initialized");
        let response = (|| {
            writeln!(
                display.child.stdin.as_mut().expect("piped display input"),
                "{text}"
            )?;
            let mut line = String::new();
            while display.replies.read_line(&mut line)? != 0 {
                let message = line.trim_end_matches('\n');
                if let Some(status) = message.strip_prefix("RESULT ") {
                    return status.parse().map_err(io::Error::other);
                }
                println!("{message}");
                io::stdout().flush()?;
                line.clear();
            }
            Err(io::Error::new(
                io::ErrorKind::UnexpectedEof,
                "display session ended",
            ))
        })();
        if response.is_err() {
            let _ = display.child.kill();
            *session = None;
        }
        response
    }
}

#[cfg(target_os = "linux")]
impl Drop for DisplaySession {
    fn drop(&mut self) {
        self.child.stdin.take();
        let _ = self.child.wait();
    }
}

#[cfg(target_os = "linux")]
fn mount_document_ext4(
    device: &std::ffi::CStr,
    target: &std::ffi::CStr,
    flags: libc::c_ulong,
    options: Option<&std::ffi::CStr>,
    wait_for_usb: bool,
) -> io::Result<()> {
    let data = options.map_or(std::ptr::null(), |options| options.as_ptr().cast());
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(15);
    loop {
        if unsafe {
            libc::mount(
                device.as_ptr(),
                target.as_ptr(),
                c"ext4".as_ptr(),
                flags,
                data,
            )
        } == 0
        {
            return Ok(());
        }
        let error = io::Error::last_os_error();
        // With a ramdisk PID 1 can run before QEMU USB storage is registered.
        if !wait_for_usb
            || !matches!(error.raw_os_error(), Some(libc::ENXIO | libc::ENODEV))
            || std::time::Instant::now() >= deadline
        {
            return Err(error);
        }
        std::thread::sleep(std::time::Duration::from_millis(100));
    }
}

#[cfg(target_os = "linux")]
fn document_console(
    work: &Path,
    guest_init: bool,
    model: Option<&Path>,
) -> io::Result<std::process::ExitCode> {
    use sha2::{Digest, Sha256};
    use std::io::BufRead;
    let path = work.join("note.txt");
    let staged = work.join(".aios-note-staging");
    if guest_init && Path::new("/etc/aios-qemu-work-partition").is_file() {
        // This image's second partition is dedicated to documents.
        let ramdisk = Path::new("/etc/aios-qemu-ramdisk").is_file();
        if ramdisk {
            if !Path::new("/proc/cmdline").is_file() {
                mount_virtual_fs(c"proc", c"/proc")?;
            }
            if !fs::read_to_string("/proc/cmdline")?
                .split_ascii_whitespace()
                .any(|argument| argument == "aios.qemu_document_disk=1")
            {
                return Err(io::Error::other(
                    "reference ramdisk requires the QEMU document disk",
                ));
            }
        }
        let flags = libc::MS_NODEV | libc::MS_NOSUID | libc::MS_NOEXEC;
        mount_document_ext4(c"/dev/sda2", c"/work", flags, None, ramdisk)?;
    }
    let stream = !guest_init || Path::new("/etc/aios-stream-worker").is_file();
    let executable = if guest_init {
        "/init".into()
    } else {
        std::env::current_exe()?
    };
    if stream {
        use std::os::unix::process::ExitStatusExt;
        let status = stream_worker::run(
            &executable,
            fs::File::options().write(true).open("/dev/null")?,
            "",
            true,
        )?;
        if status.signal() != Some(libc::SIGKILL) {
            return Err(io::Error::other("strict seccomp open probe failed"));
        }
        println!("AIOS_STREAM_POLICY open-denied");
    }
    let mut display = None;
    println!("AIOS_DOCUMENT_READY pid={}", std::process::id());
    for request in io::stdin().lock().lines() {
        let line = request?;
        if line == "poweroff" {
            if !guest_init {
                println!("AIOS_REJECT invalid-request");
                continue;
            }
            drop(display.take());
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
            std::process::Command::new(&executable)
                .arg("kernel-capabilities")
                .status()?;
            continue;
        }
        if line == "display-capabilities" {
            let result = (|| {
                if guest_init && !Path::new("/sys/class").is_dir() {
                    fs::create_dir_all("/sys")?;
                    mount_virtual_fs(c"sysfs", c"/sys")?;
                }
                hardware::display_capabilities()
            })();
            match result {
                Ok(report) => println!("AIOS_DISPLAY {report}"),
                Err(error) => println!("AIOS_REJECT display-unavailable {error}"),
            }
            continue;
        }
        if line == "display-frame" && guest_init {
            match DisplaySession::request(&mut display, "") {
                Ok(0) => println!("AIOS_FRAME_DONE"),
                _ => println!("AIOS_REJECT display-frame-unavailable"),
            }
            continue;
        }
        let original = match fs::read_to_string(&path) {
            Ok(text) => text,
            Err(error) => {
                println!("AIOS_REJECT storage-read-error {error}");
                continue;
            }
        };
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
        let generated;
        let confirmation = guest_init
            .then(|| line.strip_prefix("confirm-append "))
            .flatten();
        let model_confirmation = guest_init
            .then(|| line.strip_prefix("model-confirm-append "))
            .flatten();
        let korean = line.strip_prefix("korean ");
        let model_request = model_confirmation
            .or_else(|| line.strip_prefix("model-append "))
            .zip(model);
        let edit = if let Some(request) = korean.or(model_request.map(|(request, _)| request)) {
            let Some((revision, instruction)) = request.split_once(' ') else {
                println!("AIOS_REJECT invalid-request");
                continue;
            };
            if revision != observed {
                println!("AIOS_REJECT invalid-edit");
                continue;
            }
            if matches!(
                instruction.trim().trim_end_matches('.'),
                "메모 보여줘" | "메모 보여 줘" | "장보기 메모 보여줘"
            ) {
                println!("AIOS_READ revision={observed}");
                continue;
            }
            if let Some(text) = korean_append(instruction).filter(|_| model_confirmation.is_none())
            {
                Some((revision, text))
            } else if let Some((_, model_dir)) = model_request {
                match model_append_text(
                    instruction,
                    model_dir,
                    guest_init,
                    model_confirmation.is_some(),
                ) {
                    Ok(text) => generated = text,
                    Err(error) => {
                        println!("AIOS_REJECT {error}");
                        continue;
                    }
                }
                Some((revision, generated.as_str()))
            } else {
                None
            }
        } else {
            confirmation
                .or_else(|| line.strip_prefix("append "))
                .and_then(|r| r.split_once(' '))
        };
        let Some((revision, text)) = edit else {
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
        if confirmation.is_some() || model_confirmation.is_some() {
            if text.len() > 512 || text.trim().is_empty() || text.chars().any(char::is_control) {
                println!("AIOS_REJECT invalid-edit");
                continue;
            }
            if model_confirmation.is_some() {
                let proposal = serde_json::json!({
                    "name": "append_line",
                    "arguments": {"document": "note.txt", "revision": revision, "line": text},
                });
                println!("MODEL_PROPOSAL {proposal}");
            }
            match DisplaySession::request(&mut display, text) {
                Ok(0) => {}
                Ok(42) => {
                    println!("AIOS_REJECT confirmation-canceled");
                    continue;
                }
                _ => {
                    println!("AIOS_REJECT display-frame-unavailable");
                    continue;
                }
            }
            match fs::read_to_string(&path) {
                Ok(current) if current == original => {}
                Ok(_) => {
                    println!("AIOS_REJECT invalid-edit");
                    continue;
                }
                Err(error) => {
                    println!("AIOS_REJECT storage-read-error {error}");
                    continue;
                }
            }
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
        if stream && original.len() + addition.len() > 4 * 1024 * 1024 {
            println!("AIOS_REJECT invalid-edit");
            continue;
        }
        let publish = (|| -> io::Result<Option<fs::File>> {
            use std::io::Write;
            let directory = fs::File::open(work)?;
            // The console owns the staging name, including any interrupted save.
            match fs::remove_file(&staged) {
                Err(e) if e.kind() != io::ErrorKind::NotFound => return Err(e),
                _ => {}
            }
            let status = if stream {
                let mut output = fs::File::options()
                    .append(true)
                    .create_new(true)
                    .open(&staged)?;
                output.write_all(original.as_bytes())?;
                stream_worker::run(&executable, output, &addition, false)?
            } else {
                fs::write(&staged, &original)?;
                std::process::Command::new("/init")
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
                    .status()?
            };
            if !status.success()
                || (stream && format!("{:x}", Sha256::digest(fs::read(&staged)?)) != expected)
            {
                return Ok(None);
            }
            fs::File::open(&staged)?.sync_all()?;
            fs::rename(&staged, &path)?;
            Ok(Some(directory))
        })();
        match publish {
            Ok(Some(directory)) => match directory.sync_all() {
                Ok(()) => println!("AIOS_SAVED revision={expected}"),
                Err(error) => println!("AIOS_UNCONFIRMED revision={expected} {error}"),
            },
            Ok(None) => {
                let _ = fs::remove_file(&staged);
                println!("AIOS_REJECT worker-error");
            }
            Err(error) => {
                let _ = fs::remove_file(&staged);
                println!("AIOS_REJECT storage-write-error {error}");
            }
        }
    }
    if guest_init {
        Err(io::Error::other("Document console lost its input"))
    } else {
        Ok(std::process::ExitCode::SUCCESS)
    }
}

#[cfg(target_os = "linux")]
fn guest_memory() -> io::Result<serde_json::Value> {
    // The Flip4 disk boots directly into PID 1, without an initramfs mounting procfs.
    if std::process::id() == 1 && !Path::new("/proc/self/status").exists() {
        fs::create_dir_all("/proc")?;
        let flags = libc::MS_RDONLY | libc::MS_NOSUID | libc::MS_NODEV | libc::MS_NOEXEC;
        if unsafe {
            libc::mount(
                c"proc".as_ptr(),
                c"/proc".as_ptr(),
                c"proc".as_ptr(),
                flags,
                std::ptr::null(),
            )
        } != 0
        {
            return Err(io::Error::last_os_error());
        }
    }
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
