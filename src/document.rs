//! Apply a broker-validated text edit to the staged document after Landlock setup.
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

pub fn edit(args: &[OsString]) -> io::Result<ExitCode> {
    let [filename, observed, offset, removed, inserted, expected] = args else {
        return Err(io::Error::other(
            "expected document, revision, byte range, inserted text and resulting revision",
        ));
    };
    let name = Path::new(filename);
    if name.file_name() != Some(filename.as_os_str()) {
        return Err(io::Error::other("expected a single document name"));
    }
    let mut file = OpenOptions::new()
        .read(true)
        .write(true)
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
    let number = |arg: &OsString| {
        arg.to_str()
            .and_then(|s| s.parse::<usize>().ok())
            .ok_or_else(|| io::Error::other("invalid byte range"))
    };
    let start = number(offset)?;
    let end = start
        .checked_add(number(removed)?)
        .ok_or_else(|| io::Error::other("invalid byte range"))?;
    let text = std::str::from_utf8(&original).map_err(io::Error::other)?;
    let insert = inserted
        .to_str()
        .ok_or_else(|| io::Error::other("invalid UTF-8"))?;
    if !text.is_char_boundary(start)
        || !text.is_char_boundary(end)
        || insert.len() > 8194
        || original.len() - (end - start) + insert.len() > MAX_BYTES
    {
        return Err(io::Error::other("invalid edit range or size"));
    }
    file.seek(io::SeekFrom::Start(start as u64))?;
    file.write_all(insert.as_bytes())?;
    file.write_all(&original[end..])?;
    file.set_len((original.len() - (end - start) + insert.len()) as u64)?;
    if expected.to_str() != Some(&format!("{:x}", Sha256::digest(contents(&mut file)?))) {
        return Err(io::Error::other("staged contents failed verification"));
    }
    Ok(ExitCode::SUCCESS)
}
