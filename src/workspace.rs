//! Host-side transactions for a dedicated, single-subvolume document workspace.
use rustix::fs::{CWD, RenameFlags, renameat_with};
use std::ffi::OsString;
use std::fs::{self, File};
use std::io;

use std::path::Path;
use std::process::{Command, ExitCode, Stdio};
use std::time::Instant;

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

pub fn run(args: &[OsString]) -> io::Result<ExitCode> {
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
    let result = Command::new("unshare")
        .args([
            "--user",
            "--map-root-user",
            "--pid",
            "--fork",
            "--kill-child=KILL",
            "--",
        ])
        .args(&args[2..])
        .current_dir(&branch)
        .status();
    let accepted = result.as_ref().is_ok_and(|status| status.success());
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
    let status = result?;
    Ok(ExitCode::from(status.code().unwrap_or(1) as u8))
}
