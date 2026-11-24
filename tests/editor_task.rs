use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

// The same sequence and file oracle run against each native editor.
fn exercise(toolkit: &str, mut adapter: Command) {
    eprintln!("Testing {toolkit} editor");
    let dir = std::env::temp_dir().join(format!("aios-{toolkit}-{}", std::process::id()));
    fs::create_dir(&dir).unwrap();
    let file = dir.join("document.txt");
    fs::write(&file, "시작").unwrap();
    let mut child = adapter
        .arg(&file)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    let mut input = child.stdin.take().unwrap();
    let mut replies = BufReader::new(child.stdout.take().unwrap()).lines();
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        assert_eq!(replies.next().unwrap().unwrap(), "ready");
        let mut action = |line: &str, expected: &str| {
            writeln!(input, "{line}").unwrap();
            input.flush().unwrap();
            assert_eq!(replies.next().unwrap().unwrap(), expected, "{line}");
        };
        action("append 검토 완료", "ok");
        action("save", "ok");
        let expected = "시작\n검토 완료".as_bytes();
        let until = Instant::now() + Duration::from_secs(5);
        while fs::read(&file).unwrap() != expected && Instant::now() < until {
            std::thread::sleep(Duration::from_millis(30));
        }
        assert_eq!(fs::read(&file).unwrap(), expected);
        action("append 저장되면 안 됨", "ok");
        action("inject-modal", "injected");
        action("save", "blocked-modal");
    }));
    drop(input);
    let status = child.wait().unwrap();
    let final_bytes = fs::read(&file).unwrap();
    fs::remove_dir_all(dir).unwrap();
    if let Err(err) = result {
        std::panic::resume_unwind(err);
    }
    assert!(status.success());
    assert_eq!(final_bytes, "시작\n검토 완료".as_bytes());
}

#[cfg(target_os = "linux")]
#[test]
#[ignore = "requires GTK, Qt and an AT-SPI desktop"]
fn linux_editors() {
    for toolkit in ["gtk", "qt"] {
        let mut adapter = Command::new("python3");
        adapter.args(["tests/linux_editor_driver.py", toolkit]);
        exercise(toolkit, adapter);
    }
}

#[cfg(windows)]
#[test]
#[ignore = "requires an interactive Windows desktop"]
fn windows_editor() {
    for toolkit in ["wpf", "winforms"] {
        let mut adapter = Command::new("powershell");
        adapter.args([
            "-NoProfile",
            "-STA",
            "-File",
            "tests/windows_editor.ps1",
            "-Toolkit",
            toolkit,
            "-Document",
        ]);
        exercise(toolkit, adapter);
    }
}
