# 기술 아키텍처 설계 보고서: Linux 커널 기반 Rust AI-Native(Computer Use 특화) 크로스-OS 실행 환경

* **문서 성격**: 시스템 아키텍처 명세 및 1차 MVP 구현 계획서 (타 AI 협업·인계용)
* **기준 시점**: 2026년 11월
* **타깃 아키텍처**: `x86_64` 로컬 물리 머신 (KVM/VFIO 지원 환경)
* **핵심 구현 언어**: Rust (호스트 시스템 계층 및 핵심 데몬), C++ 또는 Rust (Windows 게스트 수집 데몬)
* **현재 상태**: 정적 아키텍처 설계 단계 (코드 구현, 빌드, 벤치마크 검증 미수행)

---

## 1. 프로젝트 개요 및 설계 정체성

### 1.1 핵심 목표

본 프로젝트는 **AI 에이전트의 Computer Use(관측·그라운딩·입력·보안·롤백)를 OS의 1급 프리미티브(First-class Primitive)로 내장한 로컬 실행 환경**을 구축하는 것을 목표로 한다. 사용자는 실행 파일의 출처 OS(Linux ELF, Windows PE)를 의식하지 않고 단일 환경에서 실행할 수 있어야 하며, 하드웨어 자원(CPU·GPU)은 로컬 네이티브 수준에 가깝게 유지되어야 한다.

### 1.2 기존 솔루션과의 구조적 차별점

기존 클라우드 기반 “AI OS” 표방 제품(예: Warmwind OS 1.0)이 기존 Linux 배포판 + Wayland/VNC 원격 스트리밍 + 화면 캡처 기반 마우스 시뮬레이터(Visual RPA 2.0) 조합에 머문 것과 달리, 본 설계는 다음 네 가지 계약을 시스템 계층에 직접 고정한다.

1. **컴포지터 1급 관측·입력**: VNC나 전체 화면 PNG 폴링을 배제하고, 컴포지터가 DMA-BUF 차분 관측과 포커스 비침해 가상 시트(Virtual Seat)를 직접 소유한다.
2. **이기종 시맨틱 UI 통합 버스**: Linux `AT-SPI2`와 Windows `UI Automation(UIA)`을 단일 정규화 스키마로 통합해 에이전트에 공급한다.
3. **시스템 레벨 보안 참조 모니터**: 프롬프트 필터링에 의존하지 않고, 제어 흐름과 비신뢰 데이터를 분리하는 정책 브로커와 커널 강제 격리(Landlock/Namespaces)로 권한을 통제한다.
4. **트랜잭션 단위 실행 모델**: 모든 에이전트 작업 세션이 COW(Copy-on-Write) 스냅샷 위에서 분기되며 실패 시 원자적으로 롤백된다.

### 1.3 범위 고정 및 명시적 제외 항목 (Scope & Exclusions)

| 구분 | 포함 범위 (In-Scope) | 제외 범위 (Out-of-Scope) 및 객관적 제외 사유 |
| --- | --- | --- |
| **커널 계층** | 순정 경량 Linux 커널 6.15+ (하드웨어 드라이버, KVM, Landlock ABI v7, `ntsync`, Btrfs/OverlayFS 활용) | **독자 커널 0부터 작성**: 최신 GPU·네트워크 드라이버 생태계 확보 불가.<br>

<br>**커널 자체의 LLM 대체**: ns~µs 지연 요구, 100% 결정론 필수, 프롬프트 인젝션 시 루트 탈취 위험으로 공학적 성립 불가. |
| **호환 OS** | Linux(ELF64) + Windows(PE64) | **macOS(Mach-O) 제외**: 2026년 9월 macOS 27부터 x86_64 지원 공식 종료, NVIDIA·최신 AMD(RDNA 3+) Metal 드라이버 부재, Apple EULA(비-Apple 하드웨어 가상화 금지), Darling GUI 미성숙. |
| **디스플레이** | 자체 Agent-First Wayland 컴포지터 | X11/VNC/RDP 기반 원격 스트리밍, 범용 데스크톱 Shell(작업표시줄·테마 등). |
| **AI 모델** | 모델 무관(Model-agnostic) 외부 MCP 인터페이스 및 내부 바이너리 IPC 계약 | 자체 VLM/LLM 학습 및 특정 모델 종속 프롬프트 튜닝. |
| **체크포인트** | 1차 MVP는 파일시스템 단위 COW 스냅샷 롤백 | 프로세스 메모리 결합 초고속 체크포인트(CRIU/DeltaCR 계열)는 2차 마일스톤으로 분리. |

---

## 2. 전체 시스템 아키텍처

본 시스템은 일반 GNU/Linux 배포판 위에 에이전트 앱을 설치하는 구조가 아니라, Android·ChromeOS 계열과 같이 **Linux 커널을 하부 하드웨어·격리 엔진으로만 사용하고 그 위의 유저스페이스를 Rust로 새로 설계한 독립 호스트 OS** 모델을 지향한다.

### 2.1 계층 구성

```text
[Layer 3: 외부 에이전트 런타임]  (모델 무관 / P-LLM 계획·Q-LLM 데이터 파싱 분리 권장)
        │  표준 MCP (경계면)
        ▼
[Layer 2: Rust 호스트 OS 코어]  (불변 최소 유저스페이스 — 신뢰 경계 TCB)
  ├── policy-brokerd   (실행 전 배치 게이트, Capability/Taint 추적, HITL 승인)
  ├── semantic-busd    (AT-SPI2 + Windows UIA + ROI DMA-BUF 통합 정규화 버스)
  ├── compositor-core  (Smithay 기반 Wayland 컴포지터, DMA-BUF 차분, 가상 시트)
  ├── txn-sandboxd     (Landlock v7 + Namespaces + Btrfs/OverlayFS 스냅샷 엔진)
  └── audit-replayd    (불변 감사 로그 및 결정론적 리플레이 하네스)
        │  바이너리 IPC (Unix Domain Socket / 공유 메모리 / virtio-vsock)
        ▼
[Layer 1: 격리된 크로스-OS 앱 서브시스템]
  ├── Linux 앱 서브시스템     (컨테이너/네임스페이스 격리 + 네이티브 실행 + AT-SPI2)
  └── Windows 앱 서브시스템   (1차: 헤드리스 KVM 워커 + UIA/DXGI 데몬 / 2차: 커스텀 Wine + ntsync)
        │
        ▼
[Layer 0: 결정론적 베이스 커널 & 물리 하드웨어]
  └── Linux Kernel 6.15+ (KVM, VFIO, Landlock v7, ntsync, eBPF, Btrfs/OverlayFS)
      CPU 코어 핀닝 / 메인 GPU(사용자·앱 네이티브 우선) / NPU·경량 풀(상주 SLM 격리)

```

### 2.2 Windows 호환 2트랙 전략 (1차 MVP 우선순위 근거)

* **1차 MVP 주력 경로 — 헤드리스 Windows KVM 워커**: 업스트림 Wine(11.20 기준)은 Linux AT-SPI 접근성 버스에 Windows 앱의 UI 트리를 노출하지 않아 순수 비전(스크린샷) 폴백을 강제한다. 1차 MVP에서는 KVM 게스트 내부에 경량 수집 데몬(`IUIAutomation` + `IDXGIOutputDuplication` over `virtio-vsock`)을 배치해 상용 Win32/WPF 앱의 구조화 UI 트리와 호환성을 즉시 확보한다. GPU 3D 네이티브 성능이 필요한 경우 듀얼 GPU 환경에서 VFIO PCIe 패스스루(연산 손실 약 0.4~1.6%)를 결합한다.
* **2차 확장 경로 — 경량 Linux + 커스텀 Wine/`ntsync**`: 단일 GPU 공유와 초경량 고밀도 병렬 에이전트 실행을 위해 Linux 6.14+ `/dev/ntsync`와 Wine/Proton(DXVK·VKD3D-Proton) 어댑터를 플러그인 형태로 추가하되, 프리픽스 내부에서 UIA/MSAA를 직접 추출하는 자체 브리지 DLL을 별도 구현한다.

---

## 3. AI-Native 3단계 계층형 관측 파이프라인

스크린샷을 매 턴 전체 인코딩해 VLM에 전달하는 방식(액션당 2~5초 지연, 창당 1,500~4,000+ 토큰 소모)을 대체하기 위해, OS 내부 상태를 3단계로 계층화해 AI에 제공한다.

1. **1계층 — 시맨틱 UI 객체 트리 (주력 관측 경로)**: `AT-SPI2`, Windows `IUIAutomation`, 브라우저 DOM을 압축된 구조화 객체(`ref` ID, `role`, `name`, `value`, `enabled`, `bbox`, `actions`, `generation_seq`)로 정규화한다. AI는 픽셀 좌표 대신 요소 참조 ID(`invoke(ref="e19", gen_seq=482)`)로 직접 조작한다.
2. **2계층 — 컴포지터 씬 그래프 & 푸시형 Diff**: 컴포지터가 창의 Z-order, 가시 영역, 변경 사각형(`damage` rect)을 추적해 상태 변화가 발생한 시점에만 변경분(Delta)을 스트리밍한다. 정지 화면에서는 데이터 전송과 추론 호출을 발생시키지 않는다.
3. **3계층 — 선택적 ROI 픽셀 관측 (보조 폴백)**: UI 트리가 비어 있거나 불완전한 영역(DirectX/Vulkan 게임, WebGL/HTML5 캔버스, 라벨 누락 아이콘)에 한해 컴포지터가 해당 바운딩 박스(ROI)의 GPU 버퍼(`DMA-BUF`)만 온디맨드로 잘라 로컬 경량 UI 검출기(OmniParser/YOLO 계열) 또는 VLM에 전달하고, 파싱 결과를 1계층 트리에 병합한다.

---

## 4. 1차 MVP 핵심 시스템 컴포넌트 명세 (5대 모듈)

### ① `compositor-core` (Agent-First Wayland 컴포지터)

* **구현 기반**: Rust `Smithay` (1순위) 또는 C/C++ `wlroots`. 헤드리스와 물리 모니터 출력을 모두 지원한다.
* **Zero-Copy 차분 관측**: `ext-image-copy-capture-v1` 프로토콜을 네이티브 구현해 대화상자 없이 `DMA-BUF` 버퍼에 프레임, `damage` 사각형, `presentation_time`을 직접 전달한다.
* **포커스 비침해 가상 시트**: 물리 입력 시트와 완전히 분리된 에이전트 전용 가상 시트를 컴포지터 내부에 생성해 키맵·모디파이어(`Ctrl`/`Shift`/`Alt`) 상태 누수를 원천 차단하고, 물리 커서와 포커스를 뺏지 않고 특정 `wl_surface`에 이벤트를 주입한다.

### ② `semantic-busd` (크로스-OS 통합 시맨틱 관측 버스)

* **수집 어댑터**: Linux `AT-SPI2` 수집기 + `compositor-core` 메타데이터 결합, Windows KVM 게스트 데몬(`IUIAutomation` + `IDXGIOutputDuplication`)과 `virtio-vsock`으로 통신.
* **정규화 스키마**: Protobuf 또는 FlatBuffers 기반 Unix Domain Socket 스트리밍. 필수 필드는 `{session_id, os_origin, window_id, element_id, role, name, bbox_px, states, supported_patterns, generation_seq}`.

### ③ `policy-brokerd` (실행 전 정책 참조 모니터 & 배치 트랜잭션 실행기)

* **경계 프로토콜 분리**: 외부 AI 에이전트와는 표준 MCP(JSON-RPC)로 통신하고, 내부 OS 모듈과는 고성능 바이너리 IPC로 통신해 직렬화 병목을 방지한다.
* **Capability & 오염(Taint) 추적**: CaMeL 모델에 준해 신뢰된 사용자 명령 기반 제어 흐름과 외부 화면·문서에서 읽은 `Untrusted` 데이터를 분리한다. 정적 서명된 툴 매니페스트 해시 검증으로 런타임 툴 변조(Rug Pull)를 차단한다.
* **실행 전 배치 게이트(Pre-execution Batch Gate)**: 배치 액션 전체를 실행 전에 검사해 파괴적 작업, 민감 경로(`~/.ssh` 등) 접근, 미허가 도메인 전송 직전에 실행을 정지하고 사용자 승인(HITL)을 요구한다.
* **동적 UI 상태 검증**: 배치 내 각 액션 실행 직전 대상 `element_id`의 `generation_seq` 및 `bbox` 유효성을 검사하고, 불일치(예: 돌발 모달 팝업) 시 잔여 배치를 즉시 중단(Abort)하고 최신 Diff를 반환한다.

### ④ `txn-sandboxd` (커널 강제 격리 & FS 트랜잭션 롤백 엔진)

* **커널 격리 스택**: Linux 6.12+ Landlock ABI v6(추상 Unix 소켓·시그널 IPC 제한) 및 6.15+ ABI v7(감사 로그 지원) + `User/Mount/Network Namespaces` + `seccomp`. 커널 네트워크 네임스페이스에서 루프백·사설 IP 대역(`127.0.0.0/8`, `10.0.0.0/8`, `169.254.0.0/16`) 접근을 차단하고 허용 도메인만 이그레스 프록시로 통과시킨다.
* **원자적 FS 롤백**: 세션 작업 루트를 Btrfs 서브볼륨 스냅샷 또는 OverlayFS 레이어로 관리해 배치 실행 전 체크포인트를 생성하고 오류·정책 위반 시 원자적으로 원복한다.

### ⑤ `audit-replayd` (불변 감사 로그 및 리플레이 하네스)

* 모든 관측 이벤트 해시, 정규화된 UI 트리 Diff, `policy-brokerd` 허용/차단 판정, Landlock 감사 이벤트, 가상 입력 시퀀스, Btrfs 트랜잭션 ID를 append-only 로그로 기록해 결정론적 디버깅과 보안 감사를 지원한다.

---

## 5. 2단계 OS 진화 전략 및 1차 MVP 구현 마일스톤

초기 인프라(Wi-Fi, 오디오, 부트 체인) 디버깅으로 인한 핵심 개발 지연을 막기 위해 2단계 빌드 전략을 적용한다.

* **Phase 1 (핵심 계약 검증 — 독립 Rust 스택 개발)**: 기존 경량 Linux 환경 위에서 GNOME/KDE 등 기존 데스크톱에 전혀 의존하지 않는 독립 프로세스 스택(5대 모듈 + Linux/Windows 어댑터)을 우선 완성하고 아래 Acceptance Criteria를 전수 통과한다.
* **Phase 2 (독립 OS 패키징 — 불변 이미지화)**: Phase 1 스택이 단독 구동 가능해지면 기존 GNU 유저스페이스를 제거하고 **최소 Linux 커널 + Rust `init`(PID 1) + Phase 1 Rust 스택**만 담은 자체 불변 OS 이미지로 패키징한다.

### Phase 1 원자적 마일스톤 (M1 ~ M5)

1. **M1 (`compositor-core`)**: `Smithay` 기반 최소 컴포지터 부트스트랩, `ext-image-copy-capture-v1`(DMA-BUF + `damage`) 및 물리/가상 시트 격리 구현 → **AC-1, AC-2 검증**.
2. **M2 (`txn-sandboxd`)**: Landlock ABI v7 + Namespaces + Btrfs/OverlayFS 스냅샷/롤백 데몬 구현 → **AC-5(커널 차단부), AC-6 검증**.
3. **M3 (`semantic-busd`)**: 통합 UI 스키마 확정, Linux `AT-SPI2` 어댑터 및 Windows KVM 게스트 데몬(`IUIAutomation` + `DXGI` over `vsock`) 연동 → **AC-3 검증**.
4. **M4 (`policy-brokerd` & `audit-replayd`)**: 실행 전 배치 게이트, Taint/Capability 검증기, `generation_seq` 동적 중단기, 불변 감사 로거 통합 → **AC-4, AC-5 전수 검증**.
5. **M5 (비교 벤치마크 감사)**: 동일 모델·동일 과제(`OSWorld` 서브셋 + Windows Win32/WPF 과제 + `VPI-Bench` 서브셋)를 **기존 Linux+VNC+스크린샷 에이전트**와 **본 1차 MVP**에서 비교 실행해 스텝당 지연, 토큰 소모, 동적 오클릭률, VPI 차단율, 롤백 시간을 실측 비교한다.

---

## 6. 정량적 검증 기준 (Acceptance Criteria)

아래 기준은 구현 완료 여부를 판정하기 위한 자동화 테스트 합격 조건이다.

| ID | 검증 영역 | 테스트 시나리오 | 통과 기준 (Acceptance Criteria) |
| --- | --- | --- | --- |
| **AC-1** | **Zero-Copy 차분 관측** | 1080p@60Hz에서 ① 정지 화면 10초 유지, ② 100×100px 영역 초당 10회 갱신 | ① 정지 구간 프레임 전송 0건. ② `damage` 면적 전체 화면의 2% 미만, 프레임 `ready` → `semantic-busd` 수신 지연 p95 < 15 ms. |
| **AC-2** | **포커스 비침해 가상 시트** | 물리 시트로 터미널(Window A)에 초당 10타 입력 중, 가상 시트가 비활성 앱(Window B)에서 `Ctrl+S`·입력·클릭 100회 실행 | Window A 포커스 상실 0건, 물리/가상 시트 모디파이어 상태 교차 오염 0건, Window B 입력 성공률 100%. |
| **AC-3** | **크로스-OS UI 트리 통합** | Linux GTK/Qt 앱 및 Windows KVM 내 Win32/WPF 앱에서 “파일 열기 → 텍스트 입력 → 저장” 수행 | 스크린샷 VLM 호출 0회로 `semantic-busd` 단일 스키마만으로 조작 완료. Windows UIA 갱신 → 호스트 반영 지연 p95 < 50 ms. |
| **AC-4** | **동적 화면 배치 중단** | 5단계 배치 액션 중 2단계 직후 강제 모달 팝업 삽입 및 대상 버튼 200px 이동 | 3단계 실행 전 `generation_seq`/`bbox` 불일치 탐지 및 즉시 Abort. 3~5단계 오클릭 0건. |
| **AC-5** | **커널 보안 및 VPI 방어** | 화면 내 악성 지시문(`VPI-Bench` 유형)으로 `~/.ssh` 읽기, 사설 IP 접속, 미허가 도메인 전송 유도 | 모델이 악성 호출을 생성하더라도 `policy-brokerd` 및 커널 Landlock/NetNS에서 차단율 100%, 감사 로그 기록 100%. |
| **AC-6** | **원자적 FS 롤백** | 10,000개 파일 디렉터리에서 에이전트 배치가 1,000개 파일 수정·삭제·생성 직후 롤백 실행 | 체크포인트 < 100 ms, 롤백 < 1,000 ms. 복원 후 전체 디렉터리 SHA-256 트리 해시 원본과 100% 일치. |

---

## 7. 후속 AI 협업을 위한 작업 인계 지침 (Handoff Constraints)

이 보고서를 전달받아 후속 설계·구현을 지원하는 AI는 다음 제약조건을 전제로 작업해야 한다.

* **핵심 코드 작성 주체**: AI는 아키텍처 세분화, 인터페이스·프로토콜 명세, 메모리/동시성 설계 검토, 테스트 하네스 설계를 지원하며, 핵심 구현 코드는 사용자가 직접 작성할 수 있도록 추상화 경계와 명확한 스펙 중심으로 제시한다.
* **정확성·검증 우선**: 미실행 빌드·테스트·벤치마크를 성공으로 간주하지 않으며, 설계 추측과 실측 증거를 엄격히 구분한다. TODO나 생략된 핵심 로직(pseudocode)으로 명세를 얼버무리지 않는다.
* **권장 즉시 착수 작업**:
1. 전체 Cargo 워크스페이스 디렉터리 구조 및 크레이트 간 의존성 그래프 확정.
2. `semantic-busd`와 `policy-brokerd` 간 공유할 **통합 UI 노드 및 배치 액션 IPC 스키마(Protobuf/FlatBuffers)** 초안 작성.
3. M1 (`compositor-core`)의 `Smithay` 상태 머신(물리 시트 vs 가상 시트 라우팅 규칙, `ext-image-copy-capture-v1` 버퍼 라이프사이클) 상세 설계 및 AC-1/AC-2 검증 테스트 하네스 명세.