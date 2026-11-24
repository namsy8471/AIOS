# AIOS

스마트폰과 컴퓨터에서 부팅하는 Linux 커널 기반 Rust AI 네이티브 OS를 만드는 학습 프로젝트입니다. AI는 문서와 앱의 상태를 구조화된 도구로 읽고, 권한이 있는 작업을 직접 요청하며, 실행 결과를 돌려받습니다. 사용자의 판단이 필요한 변경은 화면에서 확인하고, 화면 조작이 필요한 앱에는 접근성 API를 사용합니다.

## 최소 MVP

**합격 기준은 AIOS가 MCP 문서 도구로 받은 한글 변경을 저장하고, 같은 가상 디스크로 다시 부팅했을 때 원문과 변경 내용이 모두 일치하는 것입니다.** 이 실험은 고정된 MCP 요청을 보내므로 모델 계정이나 API 키가 필요 없습니다.

성공한 **Bootable document runtime** 실행에서 `aios-x86_64-document-runtime`을 받아 압축을 풉니다. Python 3과 QEMU x86_64가 있는 호스트에서 다음 명령으로 두 번의 부팅과 결과 비교를 재현할 수 있습니다.

```sh
python aios_mvp.py
```

실행마다 현재 폴더 아래에 별도 디렉터리를 만들고 가상 디스크, 부팅 로그 두 개, 수정 전후 본문과 SHA-256을 담은 `proof.json`을 남깁니다. VM에는 메모리 2 GiB를 할당합니다. CI 검증 호스트는 Linux x86_64입니다.

### PC용 UEFI USB 가상 부팅

같은 ISO를 QEMU에서 읽기 전용 USB 저장장치로 연결해 부팅할 수 있습니다. `--usb-uefi`에는 짝이 맞는 x86_64 UEFI 펌웨어와 변수 템플릿을 지정합니다. Ubuntu 24.04의 `ovmf` 패키지에서는 다음과 같이 실행합니다.

```sh
python aios_mvp.py --usb-uefi /usr/share/OVMF/OVMF_CODE_4M.fd /usr/share/OVMF/OVMF_VARS_4M.fd
```

문서는 별도 가상 디스크에 저장합니다. CI는 두 부팅의 UEFI 로그에서 USB 장치를 확인하고, 재부팅 후 문서가 일치하면 `usb-proof.json`과 부팅 로그를 아티팩트에 추가합니다. 실물 PC 부팅과 Secure Boot는 별도 검증 대상입니다. [GRUB 부팅 이미지 문서](https://www.gnu.org/software/grub/manual/grub/grub.html#Making-a-GRUB-bootable-CD_002dROM)

### 로컬 모델로 같은 작업 실행하기

GitHub Actions에서 **Bootable document runtime → Run workflow**를 실행하면 Linux 호스트 CPU에서 Qwen2.5-3B-Instruct를 구동합니다. 모델은 한국어 지시와 AIOS가 제공하는 문서 도구 목록을 받아 다음 호출을 선택합니다. 문서 저장은 부팅된 AIOS 안에서 수행합니다. 매번 다른 네 자리 숫자가 들어간 문장을 요청하고, 두 번째 부팅에서 원문과 추가한 한 줄이 정확히 일치하는지 검사합니다. 모델 추론에는 계정 등록이나 API 키가 필요 없습니다.

검증을 통과하면 위 아티팩트의 `model-proof.json`에서 지시문, 모델 응답, 실제 도구 호출과 재부팅 후 본문을 확인할 수 있습니다. 이미 호스트에서 llama-server를 실행 중이라면 압축을 푼 폴더에서 `python aios_mvp.py --model-port 18080`으로 같은 시험을 실행할 수 있습니다. 포트 번호는 서버 설정에 맞춰 지정합니다.

앞선 편집을 이어가려면 `--resume`에 완료된 실행 폴더를 지정합니다. 아래 예시는 첫 번째 결과의 가상 디스크를 새 폴더로 복사하고, 부팅한 문서가 이전 결과와 일치하는지 확인한 뒤 두 번째 지시를 수행합니다.

```sh
python aios_mvp.py --model-port 18080 --instruction "마지막 줄에 '승인 요청'을 추가해 줘." --output work-1
python aios_mvp.py --model-port 18080 --resume work-1 --instruction "'승인 요청'을 '승인 완료'로 바꿔 줘." --output work-2
```

한 번 부팅한 AIOS에 여러 지시를 연속으로 주려면 `python aios_mvp.py --model-port 18080 --interactive`로 실행합니다. 현재 본문이 표시되면 한 줄씩 지시를 입력합니다. 저장된 본문을 확인하고 다음 지시를 내릴 수 있습니다. 빈 줄로 마치면 같은 디스크로 다시 부팅해 마지막 본문을 검증하고, 각 지시와 변경 전후 해시를 `proof.json`에 기록합니다.

### 한 줄 저장 시간

동일한 커밋에서 AIOS 가상 머신을 두 번 독립적으로 실행해, 매 실행에서 직접 편집과 GTK 접근성 편집으로 같은 한글 한 줄을 여섯 쌍씩 추가했습니다. 각 쌍의 실행 순서는 번갈아 바꿨습니다. 호스트에서 문서 도구를 호출하기 직전부터 저장 응답을 받을 때까지 측정했고, 각 응답의 SHA-256과 종료 후 디스크에서 복원한 본문을 검증했습니다.

| 경로 | 검증된 저장 | 중앙값 | 최솟값–최댓값 |
| --- | ---: | ---: | ---: |
| AIOS 직접 편집 | 12/12 | 26.6 ms | 25.8–27.2 ms |
| GTK 앱을 열고 접근성 API로 입력·저장 | 12/12 | 326.2 ms | 291.8–716.3 ms |

GTK 측정에는 편집기 시작과 저장 확인이 포함됩니다. 두 경로 모두 모델 추론과 VM 부팅 시간은 제외합니다. 이미 열린 앱을 조작하는 시간, 스크린샷 기반 조작 시간, Windows에서의 성능은 별도 측정 대상입니다. [첫 번째 실행](https://github.com/namsy8471/AIOS/actions/runs/45373950240) · [두 번째 실행](https://github.com/namsy8471/AIOS/actions/runs/45373951004)

## 개발 우선순위

1. **스마트폰에 AIOS를 이식합니다.** 첫 대상은 갤럭시 Z 플립4입니다. 실기기에서 AIOS를 부팅하고 화면·터치, 로컬 모델, 메모 저장과 재부팅 후 복원을 검증합니다. 확인한 실물 모델은 `SM-F721N`, 펌웨어는 `F721NKSU8IZJC`입니다. 이 기기는 현재 부트로더가 잠겨 있고 개발자 옵션에 OEM 잠금 해제가 표시되지 않습니다. 기존 Android 안에서 로컬 추론과 AIOS 저장을 검증했고, AIOS 자체 부팅은 미검증입니다.
2. **컴퓨터에 AIOS를 이식합니다.** x86_64 PC에서 AIOS 자체를 부팅하고 문서 도구, 그래픽 환경, 저장·복원을 검증합니다. Windows 앱의 Computer Use 속도 개선은 컴퓨터에서 기존 앱을 연동하는 작업으로 이어갑니다.

## 첫 번째 실험

### ARM64 문서 콘솔

플립4 복구용 참조 커널을 오프라인으로 조사할 때는 `python scripts/inspect-phone-kernel.py <압축을 푼 ARM64 Image>`를 사용합니다. 고정된 커뮤니티 바이너리에서 추출한 버전은 `5.10.168-android12-9-Flippity-`입니다. 내장 빌드 설정에는 initramfs·ext4·F2FS·SELinux가 활성화되어 있었고 devtmpfs·Btrfs·사용자 네임스페이스는 비활성화되어 있었습니다. Landlock 항목은 없었습니다. 검사 결과의 `null`은 설정에서 항목을 찾지 못했다는 뜻입니다. 이 커널을 대상으로 초기 사용자 공간을 만들 때는 장치 노드를 제공할 경로와 문서 작업 격리를 각각 검증해야 합니다. [조사한 ARM64 커널](https://github.com/rainbowdashh/android_device_samsung_b4q/blob/fbe65008eff1589606ee3164a0ef91ef8b124894/prebuilt/kernel)

플립4의 공개 복구 이미지에 포함된 `dtbo.img`를 분석하면 B4Q 하드웨어 오버레이가 10개 있습니다. 그 파일의 `dtbo-hw_rev`부터 `dtbo-hw_rev_end`까지를 포함 범위로 읽으면 `waipio` 항목은 0·1·3, `cape` 항목은 2·5·6·7·8·9·10–32입니다. 4에 해당하는 항목은 이 파일에서 확인되지 않습니다. 실기기의 펌웨어와 보드 정보를 확보한 뒤 해당 펌웨어의 오버레이와 대조해야 합니다. 연결 정보 수집기는 Android에서 읽을 수 있는 경우 보드 ID와 하드웨어 리비전을 원래 바이트 순서의 16진수로 기록합니다. [분석한 커뮤니티 DTBO](https://github.com/rainbowdashh/android_device_samsung_b4q/blob/fbe65008eff1589606ee3164a0ef91ef8b124894/prebuilt/dtbo.img)

연결한 `SM-F721N`의 Android는 `CAPE`, SoC ID `530`, 보드 리비전 `13`, DTB 인덱스 `0`, DTBO 인덱스 `9`를 보고했습니다. 커뮤니티 복구 이미지의 DTB 0번도 `CAPE`와 ID `530`을 선언하고, DTBO 9번은 같은 SoC의 리비전 `10–32`를 대상으로 합니다. 이 대조는 참조 기기 트리 후보를 좁힙니다. 실기 펌웨어의 기기 트리 및 부팅 호환성은 별도 검증 대상입니다. [Android 기기 트리 테이블 형식](https://source.android.com/docs/core/architecture/dto/partitions)

플립4 실기기 준비에는 세부 모델, 펌웨어 빌드, 실행 중인 커널 버전이 필요합니다. Windows에서 USB 디버깅을 이미 허용한 기기가 한 대 연결되어 있으면 `scripts/flip4-inventory.ps1`로 해당 값을 읽을 수 있습니다. PC에서 조사한 커뮤니티 플립4 복구 환경의 설정은 ARM64, 부팅 헤더 v2, 페이지 크기 4096을 사용합니다. 실물 펌웨어와 일치하는지는 별도 확인이 필요합니다. [플립4 복구 보드 설정](https://github.com/rainbowdashh/android_device_samsung_b4q/blob/fbe65008eff1589606ee3164a0ef91ef8b124894/BoardConfig.mk)

AIOS 문서 작업자는 Landlock ABI 3 이상을 요구합니다. 조사한 SM8475 커뮤니티 커널 소스는 5.10.226이며 해당 커밋의 보안 서브시스템과 ARM64용 공통 시스템 호출 목록에서 Landlock 구현을 찾지 못했습니다. Linux에서 `aios kernel-capabilities`를 실행하거나 AIOS ARM64 콘솔에 `kernel-capabilities`를 입력하면 현재 커널에서 관측한 ABI와 조회 오류 번호를 확인할 수 있습니다. [커널 버전](https://github.com/samsung-sm8475/android_kernel_samsung_sm8475/blob/b04999acacba1a4f7797cb7d402b0fefe153bba9/Makefile) · [보안 서브시스템](https://github.com/samsung-sm8475/android_kernel_samsung_sm8475/tree/b04999acacba1a4f7797cb7d402b0fefe153bba9/security)

초기 부팅 기록을 회수할 후보는 예약 RAM을 쓰는 `ramoops`입니다. `python scripts/inspect-flip4-ramoops.py dtb.img dtbo.img`로 확인한 커뮤니티 기본 기기 트리 다섯 개에는 모두 2MiB의 `pmsg-size`가 선언돼 있습니다. 이 노드에 `console-size`는 명시돼 있지 않습니다. 오버레이 열 개에는 삼성 `pstore_pmsg` 노드가 있고, 참조 커널에는 `PSTORE_RAM`, `PSTORE_PMSG`, `PSTORE_CONSOLE`이 내장돼 있습니다. 실기기 펌웨어에서 기록 장치가 등록되는지와 재부팅 뒤 로그를 읽을 수 있는지는 부팅 검증에서 확인할 항목입니다. [분석한 커뮤니티 DTB](https://github.com/rainbowdashh/android_device_samsung_b4q/blob/fbe65008eff1589606ee3164a0ef91ef8b124894/prebuilt/dtb.img)

**Boot and save contract** 실행의 `aios-arm64-qemu-console` 아티팩트에 Cortex-A53 가상 기기용 Linux 커널, 초기 부팅 파일, ext4 초기 디스크와 실행 스크립트가 있습니다. Linux 호스트에서 QEMU와 Bash를 사용합니다. 압축을 푼 폴더에서 다음과 같이 작업 디스크 사본을 부팅합니다.

```sh
sha256sum -c SHA256SUMS
cp starter.raw work.raw
bash arm64-console.sh work.raw
```

콘솔에서 `inspect`로 문서 버전을 조회하고 `append <조회한 해시> 추가할 한 줄`로 저장합니다. `poweroff`로 종료한 뒤 같은 디스크를 열어 이어갈 수 있습니다. 이 이미지는 QEMU의 가상 보드용이며 스마트폰 기종별 부팅 이미지는 별도로 필요합니다.

같은 실행 묶음에서 한국어로 한 줄 추가를 요청할 수 있습니다. 호스트에서 llama-server가 실행 중이면 아래처럼 작업 디스크와 지시를 전달합니다. 결과는 UTF-8 JSON으로 출력되며, 본문 조회에는 모델 서버가 필요 없습니다.

```sh
python3 arm64_model.py work.raw --model-port 18080 --instruction "문서 마지막에 '현장 확인' 한 줄을 추가해 줘."
python3 arm64_model.py work.raw --show
```

`python3 arm64_model.py work.raw --interactive`로 실행하면 같은 ARM64 게스트에서 지시를 이어갈 수 있습니다. 매번 저장한 본문을 다시 읽어 해시를 확인하고 결과를 한 줄의 JSON으로 출력합니다. 빈 줄을 입력하거나 입력을 닫으면 게스트가 종료됩니다.

### 플립4 부팅 이미지 검사

실물 SM-F721N에서 `scripts/flip4-driver-dependencies.ps1`을 실행하면 현재 커널에 로드된 화면·터치 모듈의 의존 관계를 읽습니다. 커뮤니티 소스에는 Qualcomm DRM과 두 터치 드라이버가 있습니다. 실물과 참조 이미지의 설정은 `python scripts/inspect-phone-kernel.py kernel --running-config physical-kernel.config.gz`로 비교할 수 있습니다. 조사한 두 커널에서 모듈 심벌 버전 검사가 켜져 있으므로, 모듈을 포함할 이미지는 대상 커널과 심벌 호환성을 확인해야 합니다. [Qualcomm DRM 소스](https://github.com/samsung-sm8475/android_vendor_qcom_opensource_display-drivers/tree/5b21c06f065d5f19817aeac45c3195bb6a07d7a6/msm) · [안쪽 화면 터치 소스](https://github.com/samsung-sm8475/android_kernel_samsung_sm8475/tree/b04999acacba1a4f7797cb7d402b0fefe153bba9/drivers/input/sec_input/stm_fst2ca78y_i2c) · [커버 화면 터치 소스](https://github.com/samsung-sm8475/android_kernel_samsung_sm8475/tree/b04999acacba1a4f7797cb7d402b0fefe153bba9/drivers/input/sec_input/touchscreen_fold/zinitix)

Windows에서 실제 펌웨어를 확인하려면 USB 디버깅이 허용된 플립4를 연결한 뒤 `scripts/flip4-inventory.ps1`을 실행합니다. 스크립트는 USB 기기 한 대를 선택해 모델과 빌드 번호, 보안 패치 버전, Android가 보고한 부트로더 잠금·Verified Boot 상태를 읽습니다. 펌웨어가 노출한 기기 트리 값도 함께 기록합니다. [Android SDK Platform-Tools](https://developer.android.com/tools/releases/platform-tools)

`python scripts/inspect-flip4-boot-image.py recovery.img`는 압축을 푼 Android 헤더 v2 파일에서 각 구성 요소의 위치·크기·SHA-256과 AVB 푸터 위치를 읽습니다. 커뮤니티 TWRP V2 이미지에서 확인한 페이지 크기는 4096바이트이며, 커널·DTB·복구 DTBO의 해시는 프로젝트에서 별도로 조사한 참조 파일들과 일치합니다. 푸터 검사는 파일 범위를 확인하며, 서명 검증과 실기기 호환성 판단에는 별도 증거가 필요합니다. [검사한 커뮤니티 복구 이미지](https://github.com/rainbowdashh/android_device_samsung_b4q/releases/tag/V2)

### 플립4 CAPE 보드 후보 빌드

고정된 TWRP V2 복구 이미지와 AIOS 문서 램디스크를 사용해 오프라인 후보를 만들 수 있습니다. Linux ARM64에서 `cpio`, `device-tree-compiler`, `gcc`, `libc6-dev`, `mkbootimg`, Python 3가 필요합니다. 교차 빌드에서는 정적 ARM64 C 컴파일러를 `CC`로 지정합니다.

```sh
bash scripts/flip4-reference-image.sh --board-image recovery.img document-init.cpio.gz build/flip4/reference-board
```

`flip4-reference-board-candidate`에는 Android v2 참조 이미지, 구성 요소 해시 `layout.json`, 램디스크의 모듈 로드 순서 `order.txt`, 병합한 `merged.dtb`와 조사 결과 `board.json`, 참조 커널 설정 `kernel.json`, QEMU의 두 부팅 로그와 문서 저장·복원 결과가 들어갑니다. 빌드에서 DTB 0번과 DTBO 테이블 9번의 SoC ID와 보드 리비전 범위를 확인하고, 원본 DTB·DTBO 테이블을 부팅 이미지에 보존합니다. 병합본은 오프라인 조사에 사용합니다. 후보에 포함된 문서 램디스크의 드라이버 로더와 디스크 선택은 현재 QEMU용 커널 인자에 의존합니다.

병합본에는 안쪽 `B4_S6E3FAC_AMF670BS01`과 커버 `B4_S6E36W3_AMB190ZB01` 패널, STM 및 Zinitix 터치, CAPE PHY를 참조하는 UFS 컨트롤러가 선언돼 있습니다. 보드 후보는 QEMU에서 로드한 80개 모듈에 터치 I²C, UFS PHY, CAPE 클록과 핀 제어 및 그 모듈 의존성을 더해 88개를 패키징합니다. `board.json`은 터치 노드가 선언한 펌웨어와 원본 복구 램디스크에서 검색된 경로를 기록합니다. 고정된 복구 램디스크에는 두 터치 펌웨어 경로가 모두 없습니다. 실기에서 필요한 펌웨어 확보, 드라이버 바인딩, 화면·터치 동작과 UFS 저장은 별도 검증이 필요합니다.

### 플립4 초기 부팅 진단

`flip4-board-diagnostics`의 서명되지 않은 참조 이미지는 Android나 문서 디스크 없이 Linux/Rust PID 1을 실행합니다. PID 1은 CAPE SoC 530과 플립4의 터치·디스플레이·UFS 노드를 실행 중인 기기 트리에서 확인한 뒤 참조 모듈을 로드합니다. 커널이 등록한 DRM, 입력, 블록 장치의 번호와 화면 상태를 읽어 직렬 콘솔과 커널 로그에 기록합니다. 진단은 블록 장치를 열지 않습니다. 커널이 pmsg를 제공하면 초기 램디스크 안에 pmsg 문자 장치만 만들고 진단 스냅샷을 예약 RAM에 기록합니다.

`qemu-proof.json`과 부팅 로그는 QEMU의 가상 기기 트리에서 수행한 진단 검증입니다. QEMU의 별도 ramoops 실행은 웜 리부트 뒤 스냅샷을 읽어 원래 보고와 대조합니다. QEMU에서는 명시적인 테스트 인자가 있는 부팅에서만 모듈을 로드합니다. 실기 진단은 초기 장치 탐색 중 펌웨어를 갱신할 수 있는 STM·Zinitix 모듈을 제외한 순서를 사용합니다. 같은 순서를 QEMU에서도 검증합니다. 실기기에서 모듈이 바인딩되는지와 로그를 회수할 수 있는지는 별도 검증이 필요합니다. [STM 갱신 경로](https://github.com/samsung-sm8475/android_kernel_samsung_sm8475/blob/b04999acacba1a4f7797cb7d402b0fefe153bba9/drivers/input/sec_input/stm_fst2ca78y_i2c/stm_fw.c#L1048) · [Zinitix 갱신 경로](https://github.com/samsung-sm8475/android_kernel_samsung_sm8475/blob/b04999acacba1a4f7797cb7d402b0fefe153bba9/drivers/input/sec_input/touchscreen_fold/zinitix/ztw522/zinitix_ts.c#L1735)

두 펌웨어 이름은 공개 커뮤니티 B4Q 파일과 일치합니다. STM 터치용 `fst2ca78y_b4.bin`의 SHA-256은 `6a72cf52fba1b156008fa384eb2e8c8db44321d593a6c97b0e3cacdc6a6c00cb`이고, 커버 터치용 `ztw522_b4.bin`은 `c6aa076fe2741b2cadf975abdf8e40d22e8776b0385aebc0d077d0ca618482ae`입니다. 실물 펌웨어와의 호환성은 확인이 필요하며 두 파일은 AIOS 진단 이미지에 포함되지 않습니다. [STM 파일](https://github.com/samsung-sm8475-dev/proprietary_vendor_samsung_b4q/blob/2e806fb410592af4b913436057bd29b694e51b0c/proprietary/vendor/firmware/tsp_stm/fst2ca78y_b4.bin) · [Zinitix 파일](https://github.com/samsung-sm8475-dev/proprietary_vendor_samsung_b4q/blob/2e806fb410592af4b913436057bd29b694e51b0c/proprietary/vendor/firmware/tsp_zinitix/ztw522_b4.bin)

### 플립4 커널로 가상 메모장 실행

**Flip4 reference kernel probe**의 `flip4-reference-unsigned` 묶음에는 `aios-flip4-document-reference-unsigned.img`가 있습니다. Android v2 컨테이너에서 꺼낸 커널과 AIOS 램디스크로 QEMU를 두 번 부팅합니다. 첫 부팅에서 별도 가상 디스크에 메모를 저장하고 이전 버전으로 보낸 요청이 거절되는지 확인합니다. 두 번째 부팅에서 저장한 본문과 해시를 대조합니다. 증거는 `document-proof.json`과 두 부팅 로그에 있습니다. 이 이미지의 플립4 실기 부팅은 검증이 남아 있습니다.

[드라이버와 로컬 모델을 함께 검증한 실행](https://github.com/namsy8471/AIOS/actions/runs/45425116253)의 `flip4-reference-drivers-model-proof`에는 같은 램디스크로 두 번 부팅해 모듈 80개를 매번 로드한 로그가 있습니다. 두 부팅에서 모델 파티션이 읽기 전용으로 마운트됐고, 실행기는 저장 전과 각 부팅 후 파티션의 SHA-256을 대조했습니다. 첫 부팅에서 모델이 추가한 `우유`는 두 번째 부팅에서 같은 문서 해시로 복원됐습니다. 이 검증은 QEMU 콘솔에서 실행됐습니다.

게스트 내부에서 Qwen2.5-0.5B 추론을 실행하려면 같은 워크플로 실행의 `flip4-guest-model-disk`와 `flip4-virtual-disk`를 한 폴더에 풉니다. Linux에서 `sha256sum -c MODEL_SHA256SUMS`로 검사하고 `cp split-model-starter.raw work.raw`로 작업용 디스크를 만듭니다. `python3 flip4_model.py work.raw --split-disk --guest-model --instruction "메모에 '우유'를 적어줘."`를 실행하면 게스트가 읽기 전용 시스템의 모델을 사용하고 별도 문서 파티션에 결과를 저장합니다. 표준 오류의 `inference_ms`는 모델 프로세스 시작부터 결과 검증까지의 게스트 경과 시간이며, `model_peak_rss_kib`는 해당 프로세스의 최대 상주 메모리입니다. 종료 후 `python3 flip4_model.py work.raw --split-disk --show`로 저장 내용을 읽습니다.

내장 한국어 명령은 모델 서버 없이 게스트 안에서 처리합니다. `python3 flip4_model.py work.raw --offline --interactive`를 실행한 뒤 `장보기 메모에 '사과 두 개' 추가해 줘.` 또는 `메모 보여줘`를 입력합니다. 추가할 본문은 따옴표로 감쌉니다. 지원 범위는 메모 한 줄 추가와 조회이며, 빈 줄을 입력하면 종료됩니다.

GitHub Actions의 **Flip4 reference kernel probe** 실행에서 `flip4-virtual-disk`를 받아 압축을 풉니다. 묶음에는 플립4 커뮤니티 커널, ext4 디스크, Python 실행기가 들어 있습니다. Linux에서 Python 3과 `qemu-system-aarch64`를 설치한 뒤 묶음 폴더에서 실행합니다.

```sh
sha256sum -c SHA256SUMS
cp starter.raw work.raw
python3 flip4_model.py work.raw --show
```

첫 실행은 저장된 ‘장보기’ 메모를 출력합니다. 호스트에서 프로젝트의 로컬 모델 서버가 18080 포트로 실행 중이면 `python3 flip4_model.py work.raw --instruction "메모 끝에 '우유' 한 줄을 추가해 줘."`로 편집합니다. 같은 디스크에 `--show`를 다시 실행하면 새로 부팅한 게스트가 저장된 본문을 읽습니다.

읽기 전용 시스템과 별도 문서 파티션으로 부팅하려면 `split-starter.raw`를 `split-work.raw`로 복사한 후 `python3 flip4_model.py split-work.raw --split-disk --offline --interactive`를 실행합니다. 저장한 내용은 `python3 flip4_model.py split-work.raw --split-disk --show`로 다시 읽습니다. Windows에서는 `qemu-system-aarch64.exe`가 실행 경로에 있어야 합니다.

### ARM64 그래픽 메모장

**Boot and save contract** 수동 실행의 `aios-arm64-display-package`를 압축 해제합니다. Python과 SDL을 지원하는 QEMU가 실행 경로에 있으면 묶음 폴더에서 `python arm64_touch.py work.raw`를 실행합니다. 터미널에서 추가할 문구를 입력하고 QEMU 창에서 저장 또는 취소를 선택합니다. 빈 줄로 종료한 뒤 같은 작업 디스크로 다시 열면 저장된 메모가 먼저 표시됩니다. 이 그래픽 묶음은 Alpine 커널과 VirtIO 가상 그래픽을 사용합니다. 화면을 처음 열 때 AIOS는 sysfs의 장치 번호로 필요한 DRM·입력 장치 파일을 준비합니다. 화면 프로그램은 연결된 DRM 출력을 검색하며, 1080×2640 DSI 안쪽 화면에서는 삼성 안쪽 터치 장치의 단일 손가락 입력을 사용합니다.

`/opt/model`에 모델과 실행기가 들어 있는 신뢰할 수 있는 ext4 이미지를 가지고 있다면 `python arm64_touch.py work.raw --model-source model.raw`로 연결합니다. 모델 디스크는 읽기 전용으로 연결되며 메모는 `work.raw`에 저장됩니다. 화면 확인을 요청하면 로컬 모델이 `append_line` JSON 도구를 제안합니다. AIOS가 대상 메모와 현재 문서 해시를 붙이고, 터치 후 저장 직전에 문서가 바뀌었는지 확인합니다. 수동 워크플로의 모델·화면 검증은 실제 모델의 두 제안에 대해 터치 취소와 승인을 각각 실행하고, 메모 복원 및 모델 디스크의 SHA-256을 대조합니다.

### x86_64 부팅 데모

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

### 호스트에서 부팅한 AIOS에 MCP 연결

가상 머신에 virtio-vsock 장치를 붙이면 AIOS는 게스트 포트 `4050`에서 호스트(CID 2)의 연결을 받습니다. 가상 NIC는 꺼 둘 수 있습니다. 한 번에 하나의 MCP 세션이 문서 권한을 사용하며, 연결을 닫으면 다음 클라이언트가 새 세션으로 접속합니다. vsock 장치 없이 부팅하면 두 번째 직렬 포트를 사용합니다.

Linux 호스트에서 `vhost-device-vsock`의 `--uds-path`를 VM 소유자만 접근할 수 있는 디렉터리에 둡니다. 이 소켓에 접근하는 클라이언트는 게스트에 설정된 문서 권한을 갖습니다. stdio MCP 클라이언트의 실행 명령은 `python3 scripts/vsock_stdio.py /path/to/host.sock`입니다. QEMU의 공유 메모리와 장치 설정 예시는 [부팅 시험 코드](tests/vsock_transport.py)에 있습니다.

## GTK 저장 대화상자 관측

Linux 통합 테스트는 가상 화면에서 GTK 3 테스트 편집기를 실행합니다. 관측기는 AT-SPI2로 편집기의 프로세스와 창을 찾고, 저장 대화상자가 보이는 상태인지 확인합니다.

## 실제 편집기로 문서 저장

**Native editor save contract** 워크플로는 Linux와 Windows 데스크톱에서 같은 Rust 시나리오를 실행합니다. 임시 문서에 `시작`을 기록해 두면 편집기가 이 파일을 엽니다. 별도 프로세스가 접근성 API로 새 줄에 `검토 완료`를 입력하고 저장 버튼을 실행합니다. Rust가 디스크에서 UTF-8 바이트를 확인합니다. 이어서 미저장 내용을 추가하고 모달을 띄워 저장을 다시 요청합니다. 테스트는 요청 중단과 이전 저장본 보존을 모두 확인합니다.

각 어댑터는 테스트용 편집기 한 프로세스를 대상으로 합니다. GTK와 Qt는 AT-SPI2를 사용합니다. WPF는 UI Automation을 사용하고, WinForms의 기본 여러 줄 입력 상자는 UI Automation으로 찾은 뒤 MSAA로 본문을 편집합니다. CI의 Windows 작업은 GitHub의 Windows 호스트에서 실행됩니다. Linux 호스트와 Windows 게스트 사이의 전송 지연은 별도의 통합 측정 대상입니다.

## Linux 문서 작업의 취소와 복원

`aios workspace-run PATH -- PROGRAM [ARG...]`은 전용 Btrfs 서브볼륨의 쓰기 가능한 스냅샷을 만들고 프로그램의 작업 디렉터리를 그곳으로 설정합니다. 프로그램이 정상 종료하면 작업 사본을 원래 경로에 원자적으로 게시합니다. 오류 종료, Ctrl+C 또는 SIGTERM에서는 사본을 폐기합니다. 세션의 PID 네임스페이스가 종료되면서 남은 자동 저장 프로세스도 정리됩니다.

호스트에는 Btrfs 도구와 util-linux의 `unshare`가 필요합니다. 같은 상위 디렉터리에서 AIOS 문서 세션은 한 번에 하나씩 실행됩니다. 프로그램은 작업 디렉터리 기준으로 문서를 열어야 하며, 세션 동안 원본 서브볼륨은 AIOS가 단독 관리해야 합니다. 작업 폴더 밖의 쓰기와 네트워크 전송은 복구 범위 밖입니다. 부팅 이미지에서는 저장 성공 응답을 보내기 전에 데이터 볼륨을 동기화합니다. 다음 부팅 시 전용 볼륨에서 AIOS가 권한 있는 파일시스템 속성으로 표시한 임시 작업만 정리합니다. 일반 호스트에서 실행한 세션과 이전 버전의 임시 작업은 관리자가 확인할 수 있도록 보존합니다.

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

### 여러 수정을 한 번에 저장

`edit_document`는 문서명, 조회한 버전, 순서가 있는 `edits` 목록을 받습니다. 한 요청에서 최대 32개의 `append_line` 또는 `replace_text`를 적용합니다. 앞에서 추가한 문장을 뒤에서 고칠 수 있습니다. 어느 한 단계에서 검색 구절이 없거나 두 번 이상 나오면 해당 단계 번호를 반환하고 원본을 유지합니다. `review: true`이면 모든 변경을 한 번에 검토하고 승인하거나 취소할 수 있습니다.

### 작업 기록 조회

부팅한 AIOS에서 `recent_activity`를 호출하면 현재 문서에 대한 최근 도구 요청 기록을 조회할 수 있습니다. 각 요청에는 시작과 종료 기록이 한 쌍으로 남습니다. 성공한 작업에는 문서 버전 해시가, 거절과 취소에는 결과 코드가 남습니다. 성공 여부를 기록하기 전에 전원이 끊기면 다음 부팅에서 `outcome_unknown`으로 표시합니다. 이때는 현재 문서 버전을 조회해 결과를 확인해야 합니다.

브로커는 본문과 편집 인자를 제외한 기록을 문서 작업 폴더 밖의 전용 SQLite 파일에 저장합니다. 레코드마다 직전 레코드의 해시를 포함해 부팅 시 순서를 검사합니다. 이 기록의 신뢰 범위는 게스트 관리자와 데이터 디스크까지입니다.

## Linux에서 문서 변경을 관측하는 시간

문서 저장 경로는 AT-SPI의 `object:text-changed` 이벤트를 구독합니다. 지정한 편집기 컨트롤에서 이벤트가 오면 본문을 다시 읽고, 요청한 내용과 일치해야 저장을 진행합니다.

**Native editor save contract**는 격리된 Wayland 세션에서 GTK와 Qt 각각에 서로 다른 한글 문자열을 100회 입력합니다. 시작 시각은 편집기의 텍스트 변경 콜백 진입 시점이고, 종료 시각은 관측기가 접근성 API로 일치하는 본문을 읽은 시점입니다. 두 프로세스가 같은 Linux 단조 시계를 사용합니다. 실행별 원자료와 95번째로 빠른 표본(p95), 최댓값은 `linux-text-observation-latency` 아티팩트에 들어갑니다. 설계의 50ms 기준은 Windows 가상 머신에서 Linux 호스트까지의 경로에 적용하므로 별도 측정이 필요합니다.

## 실행 중인 Windows 편집기에 연결

`runtime/windows_session.ps1`은 운영자가 지정한 프로세스 ID와 창 제목으로 열린 편집기에 연결합니다. WPF에서는 접근성 이름이 `Document`인 본문을, WinForms에서는 기본 EDIT 컨트롤 하나를 찾습니다. 두 경우 모두 `Save` 버튼이 필요합니다. 이 인터페이스는 표준 입력과 출력으로 `observe`, `append 한 줄`, `save`를 주고받습니다. 매 요청에서 UI Automation 캐시로 창과 컨트롤을 함께 조회하고, 모달이 열리면 편집을 중단합니다. 연결을 닫으면 편집기는 계속 실행됩니다. CI는 WPF와 WinForms 테스트 편집기를 별도 프로세스에서 연 뒤 이 경로로 한글 문서를 각각 20회 저장합니다.

## Windows에서 문서 변경을 관측하는 시간

Windows 테스트에서는 별도 프로세스의 WPF·WinForms 편집기가 한글 문자열을 각각 100번 바꿉니다. 관측기는 WPF에서는 UI Automation으로, WinForms 기본 편집 상자에서는 MSAA로 새 본문을 조회합니다. 값이 일치할 때까지 조회 사이에 1ms의 대기를 요청합니다. 실제 조회 간격에는 Windows 스케줄링 시간도 포함됩니다.

편집기의 `TextChanged` 콜백과 관측기가 같은 본문을 읽은 시점에 각각 고해상도 카운터를 기록합니다. 각 표본의 카운터 값, 주파수, p95와 최댓값은 **Native editor save contract**의 `windows-text-observation-latency` 아티팩트에 있습니다. 측정 구간은 GitHub Windows 호스트 안에서 끝납니다.

## 남은 통합 검증

1. Linux 호스트와 Windows KVM 게스트를 연결하고 같은 과제를 재현합니다.
2. 게스트의 UI 변경 시점과 호스트의 관측 시점을 계측합니다. p95 목표는 50ms 미만입니다.
3. 실제 앱에서 확인한 제약을 기준으로 입력 격리, 정책 브로커, 파일시스템 롤백을 추가합니다.
