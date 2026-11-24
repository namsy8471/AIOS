use std::{fs, io, path::Path};

struct Editor {
    revision: u64,
    modal_open: bool,
}

impl Editor {
    fn save(&self, observed: u64, document: &Path, contents: &str) -> io::Result<bool> {
        if self.modal_open || self.revision != observed {
            return Ok(false);
        }
        fs::write(document, contents)?;
        Ok(true)
    }
}

fn demo(directory: &Path) -> io::Result<()> {
    let document = directory.join("note.txt");
    let mut editor = Editor {
        revision: 1,
        modal_open: false,
    };
    let observed = editor.revision;
    assert!(editor.save(observed, &document, "first draft")?);
    editor.modal_open = true;
    assert!(!editor.save(observed, &document, "unexpected modal write")?);
    editor.modal_open = false;
    editor.revision += 1;
    assert!(!editor.save(observed, &document, "stale write")?);
    assert_eq!(fs::read_to_string(document)?, "first draft");
    println!("AIOS: save verified; modal and stale requests stopped");
    Ok(())
}

fn run_demo() -> io::Result<()> {
    let dir = std::env::temp_dir().join(format!("aios-demo-{}", std::process::id()));
    fs::create_dir(&dir)?;
    let result = demo(&dir);
    let cleanup = fs::remove_dir_all(dir);
    result.and(cleanup)
}

fn main() -> io::Result<()> {
    run_demo()?;
    #[cfg(target_os = "linux")]
    if std::process::id() == 1 {
        println!("AIOS_BOOT_OK pid=1");
        unsafe extern "C" {
            fn reboot(cmd: std::ffi::c_int) -> std::ffi::c_int;
        }
        // Linux LINUX_REBOOT_CMD_POWER_OFF, called only by the guest init.
        unsafe { reboot(0x4321fedc) };
        return Err(io::Error::last_os_error());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    #[cfg(target_os = "linux")]
    #[test]
    #[ignore = "requires GTK 3, AT-SPI2 and a graphical D-Bus session"]
    fn gtk_modal_blocks_save() -> std::io::Result<()> {
        use std::io::{BufRead, BufReader, Write};
        use std::process::{Command, Stdio};

        let mut observer = Command::new("python3")
            .arg("tests/gtk_observer.py")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()?;
        let mut observations = BufReader::new(observer.stdout.take().unwrap()).lines();
        let dir = std::env::temp_dir().join(format!("aios-gtk-{}", std::process::id()));
        std::fs::create_dir(&dir)?;
        let file = dir.join("document.txt");
        for (expected, contents) in [("ready", "original"), ("modal", "unwanted write")] {
            let state = observations.next().expect("observer exited")?;
            assert_eq!(state, expected);
            let editor = super::Editor {
                revision: 1,
                modal_open: state == "modal",
            };
            assert_eq!(editor.save(1, &file, contents)?, expected == "ready");
            if expected == "ready" {
                writeln!(observer.stdin.as_mut().unwrap(), "open")?;
            }
        }
        assert!(observer.wait()?.success());
        assert_eq!(std::fs::read_to_string(&file)?, "original");
        std::fs::remove_dir_all(dir)?;
        Ok(())
    }

    #[test]
    fn save_contract() {
        super::run_demo().unwrap();
    }
}
