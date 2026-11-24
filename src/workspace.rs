//! Host-side transactions for a dedicated, single-subvolume document workspace.
use rustix::fs::{CWD, RenameFlags, renameat_with};
use std::ffi::OsString;
use std::fs::{self, File};
use std::io::{self, Read, Write};
use std::os::fd::AsRawFd;
use std::os::unix::process::CommandExt;
use std::path::Path;
use std::process::{Command, ExitCode, Stdio};
use std::sync::{
    Arc,
    atomic::{AtomicUsize, Ordering},
};
use std::time::{Duration, Instant};

fn run_worker(
    branch: &Path,
    args: &[OsString],
    interrupted: &AtomicUsize,
    agent: Option<crate::agent::Profile>,
) -> io::Result<u8> {
    // util-linux binds the namespace init's lifetime to the unshare supervisor.
    let mut command = if let Some(profile) = agent {
        crate::agent::launcher(branch, args, profile)?
    } else {
        let mut cli = Command::new("unshare");
        cli.args([
            "--user",
            "--map-root-user",
            "--pid",
            "--mount-proc",
            "--fork",
            "--kill-child=KILL",
            "--",
        ])
        .args(args)
        .current_dir(branch);
        cli
    };
    let mut worker = command.process_group(0).spawn()?;
    let diagnostic = worker.stderr.take().map(|mut pipe| {
        std::thread::spawn(move || {
            let mut prefix = Vec::new();
            pipe.by_ref().take(4096).read_to_end(&mut prefix)?;
            io::copy(&mut pipe, &mut io::sink())?;
            Ok::<_, io::Error>(prefix)
        })
    });
    loop {
        let signal = interrupted.load(Ordering::SeqCst);
        if signal != 0 {
            worker.kill()?;
            worker.wait()?;
            return Ok(128 + signal as u8);
        }
        if let Some(status) = worker.try_wait()? {
            if let Some(reader) = diagnostic {
                let bytes = reader
                    .join()
                    .map_err(|_| io::Error::other("worker log reader stopped"))??;
                if !status.success() && !bytes.is_empty() {
                    eprintln!("agent stderr {:?}", String::from_utf8_lossy(&bytes));
                }
            }
            return Ok(status.code().unwrap_or(1) as u8);
        }
        std::thread::sleep(Duration::from_millis(5));
    }
}

fn btrfs(operation: &str, paths: &[&Path]) -> io::Result<()> {
    let status = Command::new("btrfs")
        .args(["subvolume", operation])
        .args(paths)
        .stdout(Stdio::null())
        .status()?;
    if !status.success() {
        return Err(io::Error::other(format!(
            "btrfs subvolume {operation} failed: {status}"
        )));
    }
    Ok(())
}

fn flush_volume(volume: &File) -> io::Result<()> {
    if unsafe { libc::syncfs(volume.as_raw_fd()) } == 0 {
        Ok(())
    } else {
        Err(io::Error::last_os_error())
    }
}

// The trusted broker owns this pipe. The sandboxed editor has null stdin/stdout.
fn review(interrupted: &AtomicUsize) -> io::Result<u8> {
    let mut output = io::stdout().lock();
    writeln!(output, "AIOS_REVIEW_READY")?;
    output.flush()?;
    let deadline = Instant::now() + Duration::from_secs(120);
    let mut input = libc::pollfd {
        fd: libc::STDIN_FILENO,
        events: libc::POLLIN,
        revents: 0,
    };
    while interrupted.load(Ordering::SeqCst) == 0 && Instant::now() < deadline {
        let ready = unsafe { libc::poll(&mut input, 1, 100) };
        if ready < 0 {
            let err = io::Error::last_os_error();
            if err.kind() == io::ErrorKind::Interrupted {
                continue;
            }
            return Err(err);
        }
        if ready > 0 {
            let mut decision = [0];
            return Ok(
                if io::stdin().read(&mut decision)? == 1 && decision == *b"Y" {
                    0
                } else {
                    43
                },
            );
        }
    }
    Ok(43)
}

pub fn run(args: &[OsString], agent: Option<crate::agent::Profile>) -> io::Result<ExitCode> {
    let reviewed = agent.is_some() && args.get(1).is_some_and(|arg| arg == "--review");
    let separator = if reviewed { 2 } else { 1 };
    if args.len() <= separator + 1 || args[separator] != "--" {
        return Err(io::Error::other(
            "usage: aios workspace-run PATH -- PROGRAM [ARG...]",
        ));
    }
    let root = fs::canonicalize(&args[0])?;
    let parent = root
        .parent()
        .ok_or_else(|| io::Error::other("expected a workspace under a managed directory"))?;
    let lock = File::open(parent)?;
    let interrupted = Arc::new(AtomicUsize::new(0));
    for signal in [signal_hook::consts::SIGINT, signal_hook::consts::SIGTERM] {
        signal_hook::flag::register_usize(signal, interrupted.clone(), signal as usize)?;
    }
    lock.try_lock()
        .map_err(|e| io::Error::other(format!("workspace parent unavailable: {e}")))?;
    btrfs("show", &[&root])?;
    let nested = Command::new("btrfs")
        .args(["subvolume", "list", "-o"])
        .arg(&root)
        .output()?;
    if !nested.status.success() || !nested.stdout.is_empty() {
        return Err(io::Error::other(
            "expected a single Btrfs subvolume without nested subvolumes",
        ));
    }
    // Reserve the name by creating a directory exclusively. Never reuse staging
    // left by an interrupted process or let btrfs snapshot into an existing dir.
    let managed_guest = std::env::var_os("AIOS_MANAGED_GUEST").as_deref() == Some("1".as_ref());
    let nonce = fs::read_to_string("/proc/sys/kernel/random/uuid")?;
    let staging = parent.join(format!(".aios-session-{}", nonce.trim()));
    fs::create_dir(&staging)?;
    if managed_guest {
        // Only the privileged guest broker can mark a directory for boot recovery.
        let directory = File::open(&staging)?;
        let marker = b"v1";
        if unsafe {
            libc::fsetxattr(
                directory.as_raw_fd(),
                c"trusted.aios.transaction".as_ptr(),
                marker.as_ptr().cast(),
                marker.len(),
                libc::XATTR_CREATE,
            )
        } != 0
        {
            let err = io::Error::last_os_error();
            fs::remove_dir(&staging)?;
            return Err(err);
        }
    }
    let branch = staging.join("documents");
    let start = Instant::now();
    if let Err(err) = btrfs("snapshot", &[&root, &branch]) {
        fs::remove_dir(&staging)?;
        return Err(err);
    }
    eprintln!("checkpoint_us={}", start.elapsed().as_micros());
    // The workload is PID 1 in its own PID namespace. Linux tears down all
    // remaining processes there when PID 1 exits, including detached writers.
    let result =
        run_worker(&branch, &args[separator + 1..], &interrupted, agent).and_then(|code| {
            if reviewed && code == 0 {
                if managed_guest {
                    flush_volume(&lock)?;
                }
                review(&interrupted)
            } else {
                Ok(code)
            }
        });
    let signal = interrupted.load(Ordering::SeqCst);
    let accepted = signal == 0 && matches!(result, Ok(0));
    let start = Instant::now();
    if accepted {
        renameat_with(CWD, &root, CWD, &branch, RenameFlags::EXCHANGE)?;
    }
    btrfs("delete", &[&branch]).map_err(|err| {
        io::Error::other(format!(
            "workspace {}; cleanup pending at {}: {err}",
            if accepted { "published" } else { "preserved" },
            staging.display()
        ))
    })?;
    fs::remove_dir(&staging)?;
    if accepted && managed_guest {
        flush_volume(&lock)?;
    }
    if !accepted {
        eprintln!("rollback_us={}", start.elapsed().as_micros());
    }
    Ok(ExitCode::from(if signal == 0 {
        result?
    } else {
        128 + signal as u8
    }))
}
