# AIOS

Computer Use 에이전트를 위한 Linux 커널 기반 Rust 실행 환경을 만드는 학습 프로젝트입니다. AI가 문서와 앱 기능을 구조화된 도구로 직접 쓰는 것을 우선합니다. 화면이 필요한 작업에는 앱의 접근성 API를 통해 본문과 버튼을 조작합니다.

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

### 펌웨어에서 ISO 부팅

**Boot and save contract**의 성공한 실행에서 `aios-x86_64-boot` 아티팩트를 다운로드할 수 있습니다. 압축 파일에는 ISO, SHA-256 체크섬, BIOS와 UEFI 부팅 로그가 들어 있습니다. 이 이미지는 GRUB에서 Linux를 시작하고 Rust PID 1의 문서 저장 및 Landlock 쓰기 권한 검사를 마친 후 VM을 종료합니다.

ISO를 다시 만들려면 위의 직접 부팅 테스트로 생성한 initramfs에 같은 커널을 사용합니다. 빌드 환경에는 GRUB의 i386-pc와 x86_64-efi 모듈, xorriso, mtools, OVMF가 필요합니다. CI는 디스크 없는 x86-64 VM 두 대에서 동일한 ISO로 부팅합니다.

```sh
bash scripts/boot-iso.sh /path/to/vmlinuz build/initramfs.gz
(cd build/firmware && sha256sum -c SHA256SUMS)
```

## 부팅한 AIOS에서 문서 편집

문서 실험에는 별도의 `aios-runtime.iso`를 사용합니다. 읽기 전용 ISO에는 Linux 커널, Rust PID 1, MCP 서버와 GTK·Qt 테스트 편집기가 들어갑니다. 문서는 별도의 가상 디스크에 저장합니다. 이 디스크에는 `AIOS-DATA` 레이블의 Btrfs 파일시스템과 `documents` 서브볼륨, 편집을 허용할 UTF-8 파일 `note.txt`가 있어야 합니다.

**Bootable document runtime** 워크플로는 빈 임시 디스크에 이 구조를 준비하고 QEMU를 BIOS로 부팅합니다. 첫 번째 직렬 포트는 부팅 로그와 종료 명령에, 두 번째 포트는 MCP 요청과 응답에 사용합니다. 테스트는 문서 버전을 조회하고 GTK로 한글 한 줄을 저장한 다음 이전 버전의 요청을 다시 보냅니다. VM이 종료되면 가상 디스크를 읽기 전용으로 열어 최종 바이트를 대조합니다. 성공한 실행에서는 ISO, SHA-256 체크섬, 부팅 로그를 아티팩트로 받을 수 있습니다.

## GTK 저장 대화상자 관측

Linux 통합 테스트는 가상 화면에서 GTK 3 테스트 편집기를 실행합니다. 관측기는 AT-SPI2로 편집기의 프로세스와 창을 찾고, 저장 대화상자가 보이는 상태인지 확인합니다.

## 실제 편집기로 문서 저장

**Native editor save contract** 워크플로는 Linux와 Windows 데스크톱에서 같은 Rust 시나리오를 실행합니다. 임시 문서에 `시작`을 기록해 두면 편집기가 이 파일을 엽니다. 별도 프로세스가 접근성 API로 새 줄에 `검토 완료`를 입력하고 저장 버튼을 실행합니다. Rust가 디스크에서 UTF-8 바이트를 확인합니다. 이어서 미저장 내용을 추가하고 모달을 띄워 저장을 다시 요청합니다. 테스트는 요청 중단과 이전 저장본 보존을 모두 확인합니다.

각 어댑터는 테스트용 편집기 한 프로세스를 대상으로 합니다. GTK와 Qt는 AT-SPI2를 사용합니다. WPF는 UI Automation을 사용하고, WinForms의 기본 여러 줄 입력 상자는 UI Automation으로 찾은 뒤 MSAA로 본문을 편집합니다. CI의 Windows 작업은 GitHub의 Windows 호스트에서 실행됩니다. Linux 호스트와 Windows 게스트 사이의 전송 지연은 별도의 통합 측정 대상입니다.

## Linux 문서 작업의 취소와 복원

`aios workspace-run PATH -- PROGRAM [ARG...]`은 전용 Btrfs 서브볼륨의 쓰기 가능한 스냅샷을 만들고 프로그램의 작업 디렉터리를 그곳으로 설정합니다. 프로그램이 정상 종료하면 작업 사본을 원래 경로에 원자적으로 게시합니다. 오류 종료, Ctrl+C 또는 SIGTERM에서는 사본을 폐기합니다. 세션의 PID 네임스페이스가 종료되면서 남은 자동 저장 프로세스도 정리됩니다.

호스트에는 Btrfs 도구와 util-linux의 `unshare`가 필요합니다. 같은 상위 디렉터리에서 AIOS 문서 세션은 한 번에 하나씩 실행됩니다. 프로그램은 작업 디렉터리 기준으로 문서를 열어야 하며, 세션 동안 원본 서브볼륨은 AIOS가 단독 관리해야 합니다. 작업 폴더 밖의 쓰기와 네트워크 전송은 복구 범위 밖입니다. 호스트 강제 종료로 남은 작업 사본은 상위 디렉터리의 `.aios-session-*`에서 확인할 수 있습니다.

`Workspace recovery` CI는 파일 1만 개의 해시, 실패 후 자동 저장 방지, 실행 중 취소, 동시 세션 차단 및 다음 세션의 저장을 검사합니다. `Native editor save contract` CI는 GTK 편집기가 작업 사본에 저장한 뒤 취소하고 새 편집기가 원본을 열어 다시 저장하는 과정까지 검사합니다.

## 에이전트의 파일·네트워크 권한

Linux의 `aios agent-run PATH -- PROGRAM [ARG...]`은 문서 작업 사본을 `/work`로 제공하고 전용 네트워크·PID·마운트 네임스페이스에서 프로그램을 실행합니다. 프로그램은 시스템 런타임을 읽고 실행하며 작업 사본에서 일반 파일과 디렉터리를 생성·수정·삭제할 수 있습니다. Landlock 파일 규칙을 적용할 수 없으면 작업이 실패합니다. 오류 종료 시 작업 사본의 변경 내용도 폐기됩니다.

이 명령은 설치된 Linux 호스트의 `/usr/bin/bwrap`과 Landlock ABI 3 이상을 사용합니다.

`aios agent-gui-run PATH -- PROGRAM [ARG...]`은 같은 문서 트랜잭션 안에서 전용 Wayland 화면과 D-Bus 세션을 시작합니다. 호스트에는 Weston과 D-Bus가 필요합니다. GTK는 세션 전용 소켓에 연결하며, 화면과 접근성 서비스의 임시 파일은 세션 종료 때 폐기됩니다. 이 단계에서 Weston은 자체 컴포지터를 개발하기 위한 참조 구현으로 사용합니다.

## MCP로 문서 한 줄 추가

Linux 호스트에서 MCP 클라이언트의 stdio 서버로 `runtime/mcp_server.py`를 실행할 수 있습니다. 서버용 Python 환경에는 `runtime/requirements.txt`의 의존성이 필요합니다. 클라이언트 실행 인수는 다음 예시처럼 설정합니다.

```text
/opt/aios/venv/bin/python /opt/aios/runtime/mcp_server.py --aios /usr/local/bin/aios --workspace /srv/aios/documents --document note.txt
```

운영자가 시작할 때 지정한 기존 UTF-8 문서 하나에 편집 권한이 부여됩니다. `inspect_document`는 파일명과 바이트 수, SHA-256 버전을 반환합니다. `read_text`는 해당 버전의 본문을 유니코드 문자 단위로 나눠 반환합니다. `append_line`은 기본적으로 격리된 Rust 작업자가 한 줄을 직접 추가합니다. `replace_text`는 정확히 한 번 일치하는 구절을 바꾸거나 삭제합니다. 두 작업 모두 스냅샷에서 버전을 다시 확인하고 저장한 바이트를 검증합니다. 편집기 동작을 사용하려면 `append_line`의 `editor`에 `gtk` 또는 `qt`를 지정합니다. 오래된 버전으로 재호출하면 중복 추가가 거절됩니다. 파일은 최대 4 MiB, 한 줄은 최대 8 KiB이며 작업 폴더는 전용 Btrfs 서브볼륨입니다.

클라이언트가 MCP 입력 요청(form elicitation)을 지원하면 `review: true`로 저장을 검토할 수 있습니다. 편집기가 작업 사본에 쓴 바이트를 확인한 뒤 MCP 서버가 저장 여부를 묻습니다. 클라이언트가 수락하고 `save`를 참으로 보내면 변경이 원본에 반영됩니다. 취소하거나 응답 시간이 지나면 작업 사본을 폐기합니다.

## Linux에서 문서 변경을 관측하는 시간

문서 저장 경로는 AT-SPI의 `object:text-changed` 이벤트를 구독합니다. 지정한 편집기 컨트롤에서 이벤트가 오면 본문을 다시 읽고, 요청한 내용과 일치해야 저장을 진행합니다.

**Native editor save contract**는 격리된 Wayland 세션에서 GTK와 Qt 각각에 서로 다른 한글 문자열을 100회 입력합니다. 시작 시각은 편집기의 텍스트 변경 콜백 진입 시점이고, 종료 시각은 관측기가 접근성 API로 일치하는 본문을 읽은 시점입니다. 두 프로세스가 같은 Linux 단조 시계를 사용합니다. 실행별 원자료와 95번째로 빠른 표본(p95), 최댓값은 `linux-text-observation-latency` 아티팩트에 들어갑니다. 설계의 50ms 기준은 Windows 가상 머신에서 Linux 호스트까지의 경로에 적용하므로 별도 측정이 필요합니다.

## Windows에서 문서 변경을 관측하는 시간

Windows 테스트에서는 별도 프로세스의 WPF·WinForms 편집기가 한글 문자열을 각각 100번 바꿉니다. 관측기는 WPF에서는 UI Automation으로, WinForms 기본 편집 상자에서는 MSAA로 새 본문을 조회합니다. 값이 일치할 때까지 조회 사이에 1ms의 대기를 요청합니다. 실제 조회 간격에는 Windows 스케줄링 시간도 포함됩니다.

편집기의 `TextChanged` 콜백과 관측기가 같은 본문을 읽은 시점에 각각 고해상도 카운터를 기록합니다. 각 표본의 카운터 값, 주파수, p95와 최댓값은 **Native editor save contract**의 `windows-text-observation-latency` 아티팩트에 있습니다. 측정 구간은 GitHub Windows 호스트 안에서 끝납니다.

## 남은 통합 검증

1. Linux 호스트와 Windows KVM 게스트를 연결하고 같은 과제를 재현합니다.
2. 게스트의 UI 변경 시점과 호스트의 관측 시점을 계측합니다. p95 목표는 50ms 미만입니다.
3. 실제 앱에서 확인한 제약을 기준으로 입력 격리, 정책 브로커, 파일시스템 롤백을 추가합니다.
