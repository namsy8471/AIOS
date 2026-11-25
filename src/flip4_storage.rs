//! Explicit ext4 volume selection for the Flip4 document initramfs.
use crate::{flip4_probe, mount_document_ext4, mount_virtual_fs};
use std::ffi::{CStr, CString};
use std::os::unix::fs::FileExt;
use std::path::Path;
use std::{fs, io, thread, time};

const MOUNT_FLAGS: libc::c_ulong = libc::MS_NODEV | libc::MS_NOSUID;

struct Volume<'a> {
    name: &'a str,
    uuid: [u8; 16],
}

impl<'a> Volume<'a> {
    fn parse(value: &'a str) -> io::Result<Self> {
        let invalid = || io::Error::other("expected a partition name and an ext4 UUID");
        let (name, uuid) = value.split_once(':').ok_or_else(invalid)?;
        if name.is_empty() || !name.bytes().all(|byte| byte.is_ascii_alphanumeric()) {
            return Err(invalid());
        }
        let mut hex = uuid.split('-');
        let mut length = 0;
        let mut digits = [0; 32];
        for width in [8, 4, 4, 4, 12] {
            let part = hex
                .next()
                .filter(|part| part.len() == width)
                .ok_or_else(invalid)?;
            if !part.bytes().all(|byte| byte.is_ascii_hexdigit()) {
                return Err(invalid());
            }
            digits[length..length + width].copy_from_slice(part.as_bytes());
            length += width;
        }
        if hex.next().is_some() {
            return Err(invalid());
        }
        let mut bytes = [0; 16];
        for (byte, pair) in bytes.iter_mut().zip(digits.chunks_exact(2)) {
            let pair = std::str::from_utf8(pair).map_err(|_| invalid())?;
            *byte = u8::from_str_radix(pair, 16).map_err(|_| invalid())?;
        }
        if bytes == [0; 16] {
            return Err(invalid());
        }
        Ok(Self { name, uuid: bytes })
    }

    fn node(&self, label: &[u8], native: bool) -> io::Result<CString> {
        let sysfs = Path::new("/sys/class/block").join(self.name);
        let deadline = time::Instant::now() + time::Duration::from_secs(15);
        let number = loop {
            if sysfs.join("partition").is_file() {
                break fs::read_to_string(sysfs.join("dev"))?;
            }
            if time::Instant::now() >= deadline {
                return Err(io::Error::other(format!(
                    "partition {} unavailable",
                    self.name
                )));
            }
            thread::sleep(time::Duration::from_millis(100));
        };
        if native
            && !fs::canonicalize(&sysfs)?.components().any(|part| {
                matches!(
                    part.as_os_str().as_encoded_bytes(),
                    b"1d84000.ufshc" | b"ufshc@1d84000"
                )
            })
        {
            return Err(io::Error::other(format!(
                "partition {} is not on the Flip4 UFS host",
                self.name
            )));
        }
        let (major, minor) = number
            .trim()
            .split_once(':')
            .and_then(|(major, minor)| {
                Some((major.parse::<u32>().ok()?, minor.parse::<u32>().ok()?))
            })
            .ok_or_else(|| io::Error::other("invalid partition device number"))?;
        let path = format!("/dev/aios-volume-{}", self.name);
        let node = CString::new(path.as_bytes())?;
        if unsafe {
            libc::mknod(
                node.as_ptr(),
                libc::S_IFBLK | 0o600,
                libc::makedev(major, minor),
            )
        } != 0
        {
            return Err(io::Error::last_os_error());
        }

        let mut superblock = [0; 136];
        fs::File::open(&path)?.read_exact_at(&mut superblock, 1024)?;
        if superblock[56..58] != [0x53, 0xef]
            || superblock[104..120] != self.uuid
            || !superblock[120..136].starts_with(label)
            || superblock[120 + label.len()..136]
                .iter()
                .any(|&byte| byte != 0)
        {
            return Err(io::Error::other(format!(
                "{} does not match the configured ext4 volume",
                self.name
            )));
        }
        Ok(node)
    }
}

fn volume_settings(settings: &str) -> io::Result<(Volume<'_>, Volume<'_>)> {
    let mut lines = settings.lines();
    let invalid = || io::Error::other("expected work and model volume settings");
    let work = Volume::parse(
        lines
            .next()
            .and_then(|line| line.strip_prefix("work="))
            .ok_or_else(invalid)?,
    )?;
    let model = Volume::parse(
        lines
            .next()
            .and_then(|line| line.strip_prefix("model="))
            .ok_or_else(invalid)?,
    )?;
    if lines.next().is_some() || work.name == model.name || work.uuid == model.uuid {
        return Err(invalid());
    }
    Ok((work, model))
}

fn regular_file(path: &str) -> io::Result<()> {
    if !fs::symlink_metadata(path)?.file_type().is_file() {
        return Err(io::Error::other(format!(
            "expected regular AIOS file {path}"
        )));
    }
    Ok(())
}

fn mount_readonly(device: &CStr, target: &CStr, flags: libc::c_ulong) -> io::Result<()> {
    mount_document_ext4(
        device,
        target,
        flags | libc::MS_RDONLY,
        Some(c"noload"),
        false,
    )
}

fn touch_updates_disabled(tree: &Path) -> bool {
    [
        ("soc/i2c@a80000/touchscreen@49", "sec"),
        ("soc/i2c@984000/touchscreen@20", "zinitix"),
    ]
    .into_iter()
    .all(|(path, prefix)| {
        let node = tree.join(path);
        fs::read(node.join(format!("{prefix},bringup"))).is_ok_and(|value| value == [0, 0, 0, 1])
            && fs::read(node.join(format!("{prefix},firmware_name")))
                .is_ok_and(|value| !value.is_empty() && value.iter().all(|&byte| byte == 0))
    })
}

pub fn prepare() -> io::Result<(&'static Path, bool)> {
    mount_virtual_fs(c"proc", c"/proc")?;
    mount_virtual_fs(c"sysfs", c"/sys")?;
    let tree = Path::new("/sys/firmware/devicetree/base");
    let scope = flip4_probe::scope(tree);
    let native = scope == "cape_flip4_candidate";
    if !native
        && !(scope == "qemu_virt"
            && fs::read_to_string("/proc/cmdline")?
                .split_ascii_whitespace()
                .any(|arg| arg == "aios.qemu_flip4_storage_test=1"))
    {
        return Err(io::Error::other(
            "unsupported board for Flip4 document boot",
        ));
    }
    let settings = fs::read_to_string("/etc/aios-flip4-volumes")?;
    let (work, model) = volume_settings(&settings)?;
    if native {
        let touch = touch_updates_disabled(tree)
            && !Path::new("/lib/firmware").exists()
            && fs::read_to_string("/sys/module/firmware_class/parameters/path")
                .is_ok_and(|value| value.trim().is_empty());
        let mut loader = std::process::Command::new("/usr/bin/flip4-driver-loader");
        if !touch {
            loader.arg("--without-touch");
        }
        if !loader.status()?.success() {
            return Err(io::Error::other("Flip4 driver probe failed"));
        }
        println!("AIOS_FLIP4_TOUCH_NO_UPDATE {touch}");
    }
    let model = model.node(b"AIOS_MODEL", native)?;
    let work = work.node(b"AIOS_WORK", native)?;
    mount_readonly(&model, c"/model", MOUNT_FLAGS)?;
    regular_file("/model/opt/model/llama-simple")?;
    regular_file("/model/opt/model/model.gguf")?;
    println!("AIOS_MODEL_PARTITION_READ_ONLY");

    let flags = MOUNT_FLAGS | libc::MS_NOEXEC;
    mount_readonly(&work, c"/work", flags)?;
    let validation = (|| {
        regular_file("/work/.aios-work-volume")?;
        regular_file("/work/note.txt")?;
        if fs::read("/work/.aios-work-volume")? != b"AIOS document volume v1\n" {
            return Err(io::Error::other("invalid AIOS work volume marker"));
        }
        Ok(())
    })();
    if unsafe { libc::umount(c"/work".as_ptr()) } != 0 {
        return Err(io::Error::last_os_error());
    }
    validation?;
    mount_document_ext4(&work, c"/work", flags, None, false)?;
    println!("AIOS_FLIP4_STORAGE_READY {scope}");
    Ok((Path::new("/model/opt/model"), native))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn touch_gate_rejects_the_stock_update_settings() -> io::Result<()> {
        let tree = std::env::temp_dir().join(format!("aios-touch-policy-{}", std::process::id()));
        fs::create_dir(&tree)?;
        let result = (|| {
            assert!(!touch_updates_disabled(&tree));
            for (path, prefix) in [
                ("soc/i2c@a80000/touchscreen@49", "sec"),
                ("soc/i2c@984000/touchscreen@20", "zinitix"),
            ] {
                let node = tree.join(path);
                fs::create_dir_all(&node)?;
                fs::write(node.join(format!("{prefix},bringup")), [0, 0, 0, 1])?;
                fs::write(node.join(format!("{prefix},firmware_name")), [0])?;
            }
            assert!(touch_updates_disabled(&tree));
            fs::write(
                tree.join("soc/i2c@a80000/touchscreen@49/sec,firmware_name"),
                b"tsp.bin\0",
            )?;
            assert!(!touch_updates_disabled(&tree));
            Ok(())
        })();
        result.and(fs::remove_dir_all(tree))
    }

    #[test]
    fn requires_two_distinct_explicit_partitions() {
        let first = "11111111-1111-4111-8111-111111111111";
        let second = "22222222-2222-4222-8222-222222222222";
        let settings = format!("work=sda2:{first}\nmodel=sda1:{second}\n");
        let (work, model) = volume_settings(&settings).unwrap();
        assert_eq!((work.name, model.name), ("sda2", "sda1"));
        for invalid in [
            settings.replace("sda1", "sda2"),
            settings.replace(second, first),
            settings.replace("sda2", "../sda2"),
            settings.replace(first, "00000000-0000-0000-0000-000000000000"),
            settings.replace(first, "11111+11-1111-4111-8111-111111111111"),
            format!("{settings}extra=ignored\n"),
        ] {
            assert!(volume_settings(&invalid).is_err(), "{invalid}");
        }
    }
}
