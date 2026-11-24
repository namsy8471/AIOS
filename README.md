# AIOS

Computer Use 에이전트를 위한 Linux 커널 기반 Rust 실행 환경을 만드는 학습 프로젝트입니다.

## 첫 번째 실험

QEMU가 Linux 커널을 부팅하면 커널이 initramfs의 `/init`을 PID 1로 실행합니다. 이 Rust 프로그램은 임시 디렉터리에 문서를 저장하고, 모달이 열리거나 관측 시점의 문서 버전이 오래되면 후속 저장을 중단합니다. 마지막으로 파일 내용을 다시 읽어 최초 저장본이 유지됐는지 확인하고 VM을 종료합니다. 편집기 상태는 메모리에서 모사합니다.

## 내 컴퓨터에서 실행

Rust stable과 Cargo가 설치된 터미널에서 다음을 실행합니다. Windows에서도 같은 저장 로직을 확인할 수 있습니다.

```sh
cargo run --locked
cargo test --locked
```

예상 출력은 `AIOS: save verified; modal and stale requests stopped`입니다.

## 실제 커널 부팅 확인

GitHub Actions의 **Boot and save contract**에서 **Boot the Rust init** 로그를 열어 `AIOS_BOOT_OK pid=1`을 확인합니다. Linux x86_64에서는 QEMU, GNU cpio, gzip, sudo와 읽을 수 있는 initramfs 지원 커널 이미지를 준비한 뒤 직접 실행할 수 있습니다.

```sh
rustup target add x86_64-unknown-linux-musl
bash scripts/boot-test.sh /path/to/vmlinuz
```

`src/main.rs`에는 저장 판정과 PID 1 진입점이, `scripts/boot-test.sh`에는 initramfs 생성 및 VM 부팅 과정이 있습니다. 먼저 저장 판정에서 모달 검사를 빼고 테스트 실패를 관찰한 뒤 복구해 보세요.

## GTK 저장 대화상자 관측

Linux 통합 테스트는 가상 화면에서 GTK 3 테스트 편집기를 실행합니다. 관측기는 AT-SPI2로 편집기의 프로세스와 창을 찾고, 저장 대화상자가 보이는 상태인지 확인합니다.

## 실제 편집기로 문서 저장

**Native editor save contract** 워크플로는 Linux와 Windows 데스크톱에서 같은 Rust 시나리오를 실행합니다. 임시 문서에 `시작`을 기록해 두면 편집기가 이 파일을 엽니다. 별도 프로세스가 접근성 API로 새 줄에 `검토 완료`를 입력하고 저장 버튼을 실행합니다. Rust가 디스크에서 UTF-8 바이트를 확인합니다. 이어서 미저장 내용을 추가하고 모달을 띄워 저장을 다시 요청합니다. 테스트는 요청 중단과 이전 저장본 보존을 모두 확인합니다.

각 어댑터는 테스트용 편집기 한 프로세스를 대상으로 합니다. GTK와 Qt는 AT-SPI2를 사용합니다. WPF는 UI Automation을 사용하고, WinForms의 기본 여러 줄 입력 상자는 UI Automation으로 찾은 뒤 MSAA로 본문을 편집합니다. CI의 Windows 작업은 GitHub의 Windows 호스트에서 실행됩니다. Linux 호스트와 Windows 게스트 사이의 전송 지연은 별도의 통합 측정 대상입니다.

## 다음 실험

1. Linux 호스트와 Windows KVM 게스트를 연결하고 같은 과제를 재현합니다.
2. 게스트의 UI 변경 시점과 호스트의 관측 시점을 계측합니다. p95 목표는 50ms 미만입니다.
3. 실제 앱에서 확인한 제약을 기준으로 입력 격리, 정책 브로커, 파일시스템 롤백을 추가합니다.
