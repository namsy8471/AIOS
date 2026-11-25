//! Send the diskless board diagnostic over a CDC ACM USB connection.
use std::io::{self, Read, Write};
use std::os::fd::AsRawFd;
use std::os::unix::fs::{OpenOptionsExt, symlink};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};
use std::{fs, thread};

fn serial_node(name: &str) -> io::Result<PathBuf> {
    let sysfs = Path::new("/sys/class/tty").join(name).join("dev");
    let deadline = Instant::now() + Duration::from_secs(5);
    let numbers = loop {
        match fs::read_to_string(&sysfs) {
            Ok(numbers) => break numbers,
            Err(error) if error.kind() == io::ErrorKind::NotFound && Instant::now() < deadline => {
                thread::sleep(Duration::from_millis(50));
            }
            Err(error) => return Err(error),
        }
    };
    let (major, minor) = numbers
        .trim()
        .split_once(':')
        .and_then(|(major, minor)| Some((major.parse::<u32>().ok()?, minor.parse::<u32>().ok()?)))
        .ok_or_else(|| io::Error::other("invalid serial device number"))?;
    let path = Path::new("/dev").join(name);
    let node = std::ffi::CString::new(path.as_os_str().as_encoded_bytes())?;
    if unsafe {
        libc::mknod(
            node.as_ptr(),
            libc::S_IFCHR | 0o600,
            libc::makedev(major, minor),
        )
    } != 0
    {
        return Err(io::Error::last_os_error());
    }
    Ok(path)
}

fn open_serial(path: &Path, nonblocking: bool) -> io::Result<fs::File> {
    let flags = libc::O_NOCTTY | if nonblocking { libc::O_NONBLOCK } else { 0 };
    let serial = fs::OpenOptions::new()
        .read(true)
        .write(true)
        .custom_flags(flags)
        .open(path)?;
    let mut term = std::mem::MaybeUninit::uninit();
    let fd = serial.as_raw_fd();
    if unsafe { libc::tcgetattr(fd, term.as_mut_ptr()) } != 0 {
        return Err(io::Error::last_os_error());
    }
    let mut term = unsafe { term.assume_init() };
    unsafe { libc::cfmakeraw(&mut term) };
    if unsafe { libc::tcsetattr(fd, libc::TCSANOW, &term) } != 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(serial)
}

fn configure(controller: &str, product: &str) -> io::Result<PathBuf> {
    if !Path::new("/sys/class/udc").join(controller).is_dir() {
        return Err(io::Error::other(format!(
            "USB controller {controller} is unavailable"
        )));
    }
    fs::create_dir("/config")?;
    let flags = libc::MS_NOSUID | libc::MS_NODEV | libc::MS_NOEXEC;
    if unsafe {
        libc::mount(
            c"configfs".as_ptr(),
            c"/config".as_ptr(),
            c"configfs".as_ptr(),
            flags,
            std::ptr::null(),
        )
    } != 0
    {
        return Err(io::Error::last_os_error());
    }
    let gadget = Path::new("/config/usb_gadget/aios-diagnostic");
    fs::create_dir(gadget)?;
    // Use the Linux USB CDC ACM serial gadget identifiers for the diagnostic.
    fs::write(gadget.join("idVendor"), "0x0525\n")?;
    fs::write(gadget.join("idProduct"), "0xa4a7\n")?;
    fs::write(gadget.join("bDeviceClass"), "0x02\n")?;
    fs::write(gadget.join("bDeviceSubClass"), "0x02\n")?;
    fs::create_dir(gadget.join("strings/0x409"))?;
    fs::write(gadget.join("strings/0x409/product"), product)?;
    let function = gadget.join("functions/acm.diagnostic");
    fs::create_dir(&function)?;
    fs::create_dir(gadget.join("configs/c.1"))?;
    symlink(&function, gadget.join("configs/c.1/acm.diagnostic"))?;
    fs::write(gadget.join("UDC"), format!("{controller}\n"))?;
    let index = fs::read_to_string(function.join("port_num"))?
        .trim()
        .parse::<u32>()
        .map_err(io::Error::other)?;
    serial_node(&format!("ttyGS{index}"))
}

pub fn broadcast(snapshot: &str) -> io::Result<()> {
    let path = configure("a600000.dwc3", "AIOS Flip4 Diagnostic\n")?;
    let packet = format!("\n{snapshot}");
    let mut serial = None;
    loop {
        if serial.is_none() {
            serial = open_serial(&path, true).ok();
        }
        // Reopen after a hangup and start each report on a fresh line.
        if let Some(port) = &mut serial
            && let Err(error) = port.write_all(packet.as_bytes())
            && error.kind() != io::ErrorKind::WouldBlock
        {
            serial = None;
        }
        thread::sleep(Duration::from_secs(1));
    }
}

fn verify_serial_line(serial: &mut fs::File, expected: &[u8]) -> io::Result<()> {
    let mut received = Vec::new();
    let deadline = Instant::now() + Duration::from_secs(5);
    while Instant::now() < deadline {
        let mut bytes = [0; 1024];
        match serial.read(&mut bytes) {
            Ok(count) => received.extend_from_slice(&bytes[..count]),
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => (),
            Err(error) => return Err(error),
        }
        if received.ends_with(b"\n") {
            return if received == expected {
                Ok(())
            } else {
                Err(io::Error::other("USB diagnostic bytes did not match"))
            };
        }
        thread::sleep(Duration::from_millis(20));
    }
    Err(io::Error::new(
        io::ErrorKind::TimedOut,
        "USB serial line was not received",
    ))
}

pub fn verify_dummy(snapshot: &str) -> io::Result<()> {
    let mut gadget = open_serial(&configure("dummy_udc.0", "AIOS Flip4 Diagnostic\n")?, true)?;
    let mut host = open_serial(&serial_node("ttyACM0")?, true)?;
    host.write_all(b"inspect\n")?;
    verify_serial_line(&mut gadget, b"inspect\n")?;
    gadget.write_all(snapshot.as_bytes())?;
    verify_serial_line(&mut host, snapshot.as_bytes())
}

pub fn document_sessions() -> io::Result<()> {
    let path = configure("a600000.dwc3", "AIOS Flip4 Document\n")?;
    loop {
        let serial = open_serial(&path, false)?;
        std::process::Command::new("/init")
            .arg("flip4-usb-document")
            .stdin(serial.try_clone()?)
            .stdout(serial)
            .status()?;
        // A host disconnect ends its worker. A new connection gets a new session.
        thread::sleep(Duration::from_millis(250));
    }
}
