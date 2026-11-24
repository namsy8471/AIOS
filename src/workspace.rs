//! Host-side transactions for a dedicated, single-subvolume document workspace.
use rustix::fs::{CWD, RenameFlags, renameat_with};
use std::ffi::OsString;
use std::fs::{self, File};
use std::io::{self, Read};
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
    agent: bool,
) -> io::Result<u8> {
    // util-linux binds the namespace init's lifetime to the unshare supervisor.
    let mut command = if agent {
        crate::agent::launcher(branch, args)?
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

pub fn run(args: &[OsString], agent: bool) -> io::Result<ExitCode> {
    if args.len() < 3 || args[1] != "--" {
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
    let staging = parent.join(format!(".aios-session-{}", std::process::id()));
    fs::create_dir(&staging)?;
    let branch = staging.join("documents");
    let start = Instant::now();
    if let Err(err) = btrfs("snapshot", &[&root, &branch]) {
        fs::remove_dir(&staging)?;
        return Err(err);
    }
    eprintln!("checkpoint_us={}", start.elapsed().as_micros());
    // The workload is PID 1 in its own PID namespace. Linux tears down all
    // remaining processes there when PID 1 exits, including detached writers.
    let result = run_worker(&branch, &args[2..], &interrupted, agent);
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
    if !accepted {
        eprintln!("rollback_us={}", start.elapsed().as_micros());
    }
    Ok(ExitCode::from(if signal == 0 {
        result?
    } else {
        128 + signal as u8
    }))
}
