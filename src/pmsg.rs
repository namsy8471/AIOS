//! Android-compatible log frames for the reserved-RAM pmsg backend.
use std::{fs, io, time::SystemTime};

pub fn frame(message: &[u8]) -> io::Result<Vec<u8>> {
    const TAG: &[u8] = b"\x04AIOS\0"; // ANDROID_LOG_INFO and tag
    let length = u16::try_from(18 + TAG.len() + message.len() + 1)
        .map_err(|_| io::Error::other("pmsg frame exceeds its length field"))?;
    let timestamp = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .map_err(io::Error::other)?;
    // Android liblog's packed pmsg header, log header, and text payload.
    // These probes run as root with PID and TID 1.
    let mut frame = vec![b'l'];
    frame.extend_from_slice(&length.to_le_bytes());
    frame.extend_from_slice(&0u16.to_le_bytes()); // UID
    frame.extend_from_slice(&1u16.to_le_bytes()); // PID
    frame.push(0); // LOG_ID_MAIN
    frame.extend_from_slice(&1u16.to_le_bytes()); // TID
    frame.extend_from_slice(&(timestamp.as_secs() as u32).to_le_bytes());
    frame.extend_from_slice(&timestamp.subsec_nanos().to_le_bytes());
    frame.extend_from_slice(TAG);
    frame.extend_from_slice(message);
    frame.push(0);
    Ok(frame)
}

pub fn open() -> io::Result<fs::File> {
    let numbers = fs::read_to_string("/sys/class/pmsg/pmsg0/dev")?;
    let (major, minor) = numbers
        .trim()
        .split_once(':')
        .and_then(|(major, minor)| Some((major.parse::<u32>().ok()?, minor.parse::<u32>().ok()?)))
        .ok_or_else(|| io::Error::other("invalid pmsg device number"))?;
    if unsafe {
        libc::mknod(
            c"/dev/pmsg0".as_ptr(),
            libc::S_IFCHR | 0o600,
            libc::makedev(major, minor),
        )
    } != 0
    {
        return Err(io::Error::last_os_error());
    }
    fs::OpenOptions::new().write(true).open("/dev/pmsg0")
}
