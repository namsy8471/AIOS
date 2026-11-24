use landlock::{
    ABI, Access, AccessFs, CompatLevel, Compatible, PathBeneath, PathFd, Ruleset, RulesetAttr,
    RulesetCreatedAttr, RulesetStatus,
};
use std::ffi::OsString;
use std::io;
use std::os::unix::process::CommandExt;
use std::path::Path;
use std::process::{Command, Stdio};

#[derive(Clone, Copy, PartialEq)]
pub enum Profile {
    Document,
    Desktop,
}

pub fn launcher(branch: &Path, args: &[OsString], profile: Profile) -> io::Result<Command> {
    let mut cmd = Command::new("/usr/bin/bwrap");
    cmd.env_clear()
        .env("PATH", "/usr/bin:/bin")
        .env("LANG", "C.UTF-8")
        .args([
            "--die-with-parent",
            "--unshare-all",
            "--new-session",
            "--cap-drop",
            "ALL",
        ]);
    for dir in ["/usr", "/bin", "/lib", "/lib64"] {
        if Path::new(dir).is_dir() {
            cmd.args(["--ro-bind", dir, dir]);
        }
    }
    if profile == Profile::Desktop {
        cmd.args([
            "--tmpfs",
            "/tmp",
            "--perms",
            "0700",
            "--dir",
            "/tmp/runtime",
        ])
        .env("XDG_RUNTIME_DIR", "/tmp/runtime")
        .env("HOME", "/tmp")
        .env("GSETTINGS_BACKEND", "memory")
        .env("GDK_BACKEND", "wayland")
        .env("WAYLAND_DISPLAY", "wayland-aios");
        for dir in ["/etc/fonts", "/etc/xdg"] {
            if Path::new(dir).is_dir() {
                cmd.args(["--ro-bind", dir, dir]);
            }
        }
    }
    cmd.args(["--dev", "/dev", "--proc", "/proc", "--ro-bind"])
        .arg(std::env::current_exe()?)
        .args(["/aios-launch", "--bind"])
        .arg(branch)
        .args([
            "/work",
            "--chdir",
            "/work",
            "--",
            "/aios-launch",
            if profile == Profile::Desktop {
                "restrict-desktop"
            } else {
                "restrict-worker"
            },
        ])
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::piped());
    // Landlock applies at open time. Only the three null descriptors may reach
    // bwrap, even when the caller explicitly passed other descriptors to AIOS.
    unsafe {
        cmd.pre_exec(|| {
            if libc::syscall(
                libc::SYS_close_range,
                3_u32,
                u32::MAX,
                libc::CLOSE_RANGE_CLOEXEC,
            ) < 0
            {
                return Err(io::Error::last_os_error());
            }
            Ok(())
        });
    }
    Ok(cmd)
}

pub fn exec_worker(args: &[OsString], desktop: bool) -> io::Result<std::process::ExitCode> {
    let program = args
        .first()
        .ok_or_else(|| io::Error::other("missing worker program"))?;
    let abi = ABI::V3; // Includes cross-directory rename and file truncation.
    let handled = AccessFs::from_all(abi);
    let runtime = AccessFs::from_read(abi);
    let document = AccessFs::ReadFile
        | AccessFs::ReadDir
        | AccessFs::WriteFile
        | AccessFs::Truncate
        | AccessFs::MakeReg
        | AccessFs::MakeDir
        | AccessFs::RemoveFile
        | AccessFs::RemoveDir
        | AccessFs::Refer;
    let mut policy = Ruleset::default()
        .set_compatibility(CompatLevel::HardRequirement)
        .handle_access(handled)
        .map_err(io::Error::other)?
        .create()
        .map_err(io::Error::other)?;
    for dir in ["/usr", "/bin", "/lib", "/lib64"] {
        if Path::new(dir).is_dir() {
            policy = policy
                .add_rule(PathBeneath::new(
                    PathFd::new(dir).map_err(io::Error::other)?,
                    runtime,
                ))
                .map_err(io::Error::other)?;
        }
    }
    if desktop {
        for (path, rights) in [
            (
                "/tmp",
                document | AccessFs::MakeSock | AccessFs::MakeFifo | AccessFs::MakeSym,
            ),
            ("/proc", AccessFs::ReadFile | AccessFs::ReadDir),
            ("/etc/fonts", AccessFs::ReadFile | AccessFs::ReadDir),
            ("/etc/xdg", AccessFs::ReadFile | AccessFs::ReadDir),
            ("/dev/null", AccessFs::ReadFile | AccessFs::WriteFile),
            ("/dev/urandom", AccessFs::ReadFile.into()),
            ("/dev/shm", document),
        ] {
            if Path::new(path).exists() {
                policy = policy
                    .add_rule(PathBeneath::new(
                        PathFd::new(path).map_err(io::Error::other)?,
                        rights,
                    ))
                    .map_err(io::Error::other)?;
            }
        }
    }
    let status = policy
        .add_rule(PathBeneath::new(
            PathFd::new("/work").map_err(io::Error::other)?,
            document,
        ))
        .map_err(io::Error::other)?
        .restrict_self()
        .map_err(io::Error::other)?;
    if status.ruleset != RulesetStatus::FullyEnforced {
        return Err(io::Error::other(
            "document policy could not be fully enforced",
        ));
    }
    if desktop {
        let mut compositor = Command::new("/usr/bin/weston")
            .args([
                "--backend=headless-backend.so",
                "--shell=kiosk-shell.so",
                "--socket=wayland-aios",
                "--idle-time=0",
                "--no-config",
                "--log=/tmp/weston.log",
            ])
            .spawn()?;
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
        while !Path::new("/tmp/runtime/wayland-aios").exists() {
            if compositor.try_wait()?.is_some() || std::time::Instant::now() >= deadline {
                return Err(io::Error::other(format!(
                    "Weston startup failed: {}",
                    std::fs::read_to_string("/tmp/weston.log").unwrap_or_default()
                )));
            }
            std::thread::sleep(std::time::Duration::from_millis(20));
        }
        return Err(Command::new("/usr/bin/dbus-run-session")
            .args(["--config-file=/usr/share/dbus-1/session.conf", "--"])
            .args(args)
            .exec());
    }
    Err(Command::new(program).args(&args[1..]).exec())
}
