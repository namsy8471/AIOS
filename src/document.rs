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
    let [filename, observed, ranges @ .., expected] = args else {
        return Err(io::Error::other(
            "expected document, revision, byte range, inserted text and resulting revision",
        ));
    };
    if ranges.is_empty() || ranges.len() > 32 * 3 || ranges.len() % 3 != 0 {
        return Err(io::Error::other("expected between 1 and 32 edit ranges"));
    }
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
    let mut text = String::from_utf8(original).map_err(io::Error::other)?;
    let mut first_change = text.len();
    for range in ranges.chunks_exact(3) {
        let start = number(&range[0])?;
        let end = start
            .checked_add(number(&range[1])?)
            .ok_or_else(|| io::Error::other("invalid byte range"))?;
        let insert = range[2]
            .to_str()
            .ok_or_else(|| io::Error::other("invalid UTF-8"))?;
        if !text.is_char_boundary(start)
            || !text.is_char_boundary(end)
            || insert.len() > 8194
            || text.len() - (end - start) + insert.len() > MAX_BYTES
        {
            return Err(io::Error::other("invalid edit range or size"));
        }
        first_change = first_change.min(start);
        text.replace_range(start..end, insert);
    }
    file.seek(io::SeekFrom::Start(first_change as u64))?;
    file.write_all(&text.as_bytes()[first_change..])?;
    file.set_len(text.len() as u64)?;
    if expected.to_str() != Some(&format!("{:x}", Sha256::digest(contents(&mut file)?))) {
        return Err(io::Error::other("staged contents failed verification"));
    }
    Ok(ExitCode::SUCCESS)
}
