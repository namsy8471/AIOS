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

Linux 통합 테스트는 가상 화면에서 GTK 3 테스트 편집기를 실행합니다. 별도 프로세스가 AT-SPI2로 편집기 창을 찾으면 Rust가 임시 문서를 저장합니다. 편집기에 저장 대화상자를 연 뒤 관측기가 같은 프로세스의 창에서 `MODAL`과 `SHOWING`을 확인하면 Rust가 두 번째 저장을 중단하고 파일 내용을 검증합니다. GitHub Actions의 **GTK save observation**에서 실행 결과를 확인할 수 있습니다.

## 다음 실험

1. GTK 접근성 액션으로 실제 편집기의 저장을 요청하고 생성된 파일을 확인합니다.
2. Windows 게스트의 WPF 편집기에서 UI Automation으로 같은 과제를 수행합니다.
3. 실제 앱에서 확인한 제약을 기준으로 입력 격리, 정책 브로커, 파일시스템 롤백을 추가합니다.
