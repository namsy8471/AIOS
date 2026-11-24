//! Fixed append operation for the phone console. stdout is the staging file.
use std::io;
use std::path::Path;
use std::process::{Command, ExitStatus, Stdio};

pub fn run(
    executable: &Path,
    output: std::fs::File,
    addition: &str,
    probe: bool,
) -> io::Result<ExitStatus> {
    Command::new(executable)
        .arg(if probe {
            "probe-stream-worker"
        } else {
            "append-stream-worker"
        })
        .arg(addition)
        .env_clear()
        .stdin(Stdio::null())
        .stdout(output)
        .stderr(Stdio::null())
        .status()
}

pub fn worker(addition: &str, probe: bool) -> io::Result<()> {
    let mut remaining = addition.as_bytes();
    unsafe {
        if libc::syscall(libc::SYS_close_range, 3u32, u32::MAX, 0u32) < 0
            || libc::prctl(libc::PR_SET_NO_NEW_PRIVS, 1usize, 0usize, 0usize, 0usize) < 0
            || libc::prctl(libc::PR_SET_SECCOMP, 1usize, 0usize, 0usize, 0usize) < 0
        {
            return Err(io::Error::last_os_error());
        }
        // Strict seccomp permits read, write, exit and signal return only.
        // Both an allowed and an ordinary failed open return to the caller.
        // Only a signal termination counts as a successful confinement probe.
        if probe {
            libc::open(c"/dev/null".as_ptr(), libc::O_RDONLY);
        }
        while !remaining.is_empty() {
            let n = libc::write(1, remaining.as_ptr().cast(), remaining.len());
            if n <= 0 {
                libc::syscall(libc::SYS_exit, 1);
            } else {
                remaining = &remaining[n as usize..];
            }
        }
        libc::syscall(libc::SYS_exit, 0);
    }
    unreachable!()
}
