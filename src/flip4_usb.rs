//! Send the diskless board diagnostic over a CDC ACM USB connection.
use std::io::{self, Read, Write};
use std::os::fd::AsRawFd;
use std::os::unix::fs::{OpenOptionsExt, symlink};
use std::path::Path;
use std::time::{Duration, Instant};
use std::{fs, thread};

fn open_serial(name: &str) -> io::Result<fs::File> {
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
    let node = std::ffi::CString::new(format!("/dev/{name}"))?;
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
    let serial = fs::OpenOptions::new()
        .read(true)
        .write(true)
        .custom_flags(libc::O_NONBLOCK | libc::O_NOCTTY)
        .open(Path::new("/dev").join(name))?;
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

fn configure(controller: &str) -> io::Result<fs::File> {
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
    fs::create_dir(gadget.join("strings/0x409"))?;
    fs::write(
        gadget.join("strings/0x409/product"),
        "AIOS Flip4 Diagnostic\n",
    )?;
    let function = gadget.join("functions/acm.diagnostic");
    fs::create_dir(&function)?;
    fs::create_dir(gadget.join("configs/c.1"))?;
    symlink(&function, gadget.join("configs/c.1/acm.diagnostic"))?;
    fs::write(gadget.join("UDC"), format!("{controller}\n"))?;
    let index = fs::read_to_string(function.join("port_num"))?
        .trim()
        .parse::<u32>()
        .map_err(io::Error::other)?;
    open_serial(&format!("ttyGS{index}"))
}

pub fn broadcast(snapshot: &str) -> io::Result<()> {
    let mut serial = configure("a600000.dwc3")?;
    loop {
        // Opening the port late or reconnecting still receives a complete report.
        let _ = serial.write_all(snapshot.as_bytes());
        thread::sleep(Duration::from_secs(1));
    }
}

pub fn verify_dummy(snapshot: &str) -> io::Result<()> {
    let mut gadget = configure("dummy_udc.0")?;
    let mut host = open_serial("ttyACM0")?;
    gadget.write_all(snapshot.as_bytes())?;
    let mut received = Vec::new();
    let deadline = Instant::now() + Duration::from_secs(5);
    while Instant::now() < deadline {
        let mut bytes = [0; 1024];
        match host.read(&mut bytes) {
            Ok(count) => received.extend_from_slice(&bytes[..count]),
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => (),
            Err(error) => return Err(error),
        }
        if received.ends_with(b"\n") {
            return if received == snapshot.as_bytes() {
                Ok(())
            } else {
                Err(io::Error::other("USB diagnostic bytes did not match"))
            };
        }
        thread::sleep(Duration::from_millis(20));
    }
    Err(io::Error::new(
        io::ErrorKind::TimedOut,
        "USB diagnostic did not reach the host TTY",
    ))
}
