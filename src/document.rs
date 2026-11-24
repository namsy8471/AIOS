//! Apply a broker-validated suffix to the staged document after Landlock setup.
use sha2::{Digest, Sha256};
use std::ffi::OsString;
use std::fs::{File, OpenOptions};
use std::io::{self, Read, Seek, Write};
use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
use std::path::Path;
use std::process::ExitCode;

const MAX_BYTES: usize = 4 * 1024 * 1024;

fn contents(file: &mut File) -> io::Result<Vec<u8>> {
    file.rewind()?;
    let mut bytes = Vec::new();
    file.take((MAX_BYTES + 1) as u64).read_to_end(&mut bytes)?;
    if bytes.len() > MAX_BYTES {
        return Err(io::Error::other("document exceeds the size limit"));
    }
    Ok(bytes)
}

pub fn append(args: &[OsString]) -> io::Result<ExitCode> {
    let [filename, observed, suffix, expected] = args else {
        return Err(io::Error::other(
            "expected document, revision, suffix and resulting revision",
        ));
    };
    let name = Path::new(filename);
    if name.file_name() != Some(filename.as_os_str()) {
        return Err(io::Error::other("expected a single document name"));
    }
    let mut file = OpenOptions::new()
        .read(true)
        .append(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(Path::new("/work").join(name))?;
    let info = file.metadata()?;
    if !info.is_file() || info.nlink() != 1 {
        return Err(io::Error::other(
            "expected a regular document with a single link",
        ));
    }
    let original = contents(&mut file)?;
    if observed.to_str() != Some(&format!("{:x}", Sha256::digest(&original))) {
        return Ok(ExitCode::from(42));
    }
    let suffix = suffix
        .to_str()
        .ok_or_else(|| io::Error::other("expected UTF-8 suffix"))?;
    if suffix.len() > 8194 || original.len() + suffix.len() > MAX_BYTES {
        return Err(io::Error::other("append exceeds the size limit"));
    }
    file.write_all(suffix.as_bytes())?;
    if expected.to_str() != Some(&format!("{:x}", Sha256::digest(contents(&mut file)?))) {
        return Err(io::Error::other("staged contents failed verification"));
    }
    Ok(ExitCode::SUCCESS)
}
