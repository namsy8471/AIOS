use landlock::{
    ABI, Access, AccessFs, CompatLevel, Compatible, PathBeneath, PathFd, Ruleset, RulesetAttr,
    RulesetCreatedAttr, RulesetStatus,
};
use std::ffi::OsString;
use std::io;
use std::os::unix::process::CommandExt;
use std::path::Path;
use std::process::{Command, Stdio};

pub fn launcher(branch: &Path, args: &[OsString]) -> io::Result<Command> {
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
            "restrict-worker",
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

pub fn exec_worker(args: &[OsString]) -> io::Result<std::process::ExitCode> {
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
    Err(Command::new(program).args(&args[1..]).exec())
}
