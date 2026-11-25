# TLA · 플립4와 Windows 협업

Android 앱이 한국어 지시를 받고, Windows PC는 더 긴 문서 작업을 맡는다. 첫 시연의 기준 기기는 갤럭시 Z 플립4 SM-F721N이다. Android 앱과 Windows 작업자는 같은 요청 형식을 사용하므로 이후 PC 작업자를 네이티브 애플리케이션이나 AIOS 가상 머신으로 옮길 수 있다.

TLA는 **Thanks, Local Agent**의 약자다. 첫 화면은 대화이며, 하단 입력창에 `메모에 우유 추가`, `메모 보기` 또는 `오늘 날씨 검색`을 보낼 수 있다. 메모 변경과 검색 전송에는 각각 승인 단계가 있다. 하단의 **도구**에서 웹 검색과 앱 동작을 열고, **도구 · 설정**에서 문서 작업과 PC 연결을 관리할 수 있다. 대화 메시지는 앱이 열린 동안 표시되고, 승인해 저장한 메모와 보고서는 다음 실행에서도 읽을 수 있다. 기존 Android 패키지와 서명으로 업데이트하면 앱의 기존 파일을 이어서 사용한다.

`구글에 네이버 검색 해줘`에서 Google은 검색 서비스이고 검색어는 `네이버`다. 대화에서 `설정에서 밝기 올려줘`, `화면 밝기 70%로 설정해 줘`, `미디어 음량 줄여`도 승인 후 실행할 수 있다. 화면 밝기를 처음 바꿀 때는 Android의 시스템 설정 변경 권한이 필요하다. 자동 밝기가 켜져 있으면 수동 전환을 함께 승인받는다. 음량은 미디어 출력에 적용한다. [Android 시스템 설정 API](https://developer.android.com/reference/android/provider/Settings.System)

`5분 타이머 맞춰줘`는 확인 후 시간 값을 시계 앱으로 보낸다. `카메라 열어줘`, `화면 설정 열어줘`, `와이파이 설정 열어줘`, `블루투스 설정 열어줘`는 Android의 해당 화면을 연다. [Android 일반 인텐트](https://developer.android.com/guide/components/intents-common)

### 플립4 실행 가능 범위

| 동작 | 확인한 범위 |
| --- | --- |
| 화면·Wi-Fi·블루투스 설정 | 플립4에서 각각의 시스템 화면을 직접 열었다. 화면 진입과 토글 변경은 별도 동작이다. |
| 시계·카메라 | 타이머, 알람, 카메라 인텐트를 처리할 앱이 설치돼 있었다. TLA의 타이머 승인과 취소는 계측의 인텐트 가로채기로 검증한다. |
| 다른 앱 버튼 및 스와이프 | 사용자가 허용한 접근성 서비스로 별도 시험 앱에서 검증했다. 실제 게임을 대상으로 한 출석이나 플레이의 성공 여부는 대상 앱별로 확인해야 한다. |
| 결제 | 실제 구매는 시험하지 않았다. 구매 테스트는 시험 상품과 결제 수단을 쓰며, 운영 환경에서는 사용자가 금액과 대상을 확인하고 결제 앱의 인증을 진행한다. |

[Android 접근성 서비스](https://developer.android.com/reference/android/accessibilityservice/AccessibilityService) · [Google Play Billing 시험](https://developer.android.com/google/play/billing/test)

| 단계 | 결과 | 검증 |
| --- | --- | --- |
| 1 | 플립4에 설치 가능한 APK | 실기에서 앱이 시작되고 메모와 PC 작업 화면이 열린다. |
| 2 | 휴대폰 단독 메모 작업 | 비행기 모드에서 한국어 지시를 로컬 모델로 해석하고, 미리 보기에서 승인하면 저장한다. 앱을 종료하고 다시 열어 본문을 비교한다. |
| 3 | Windows 협업 | 폰에서 선택한 세 문서의 이름과 보낼 내용을 확인한다. 승인 후 Windows 로컬 모델이 회의 보고서 초안을 생성하고 폰이 결과를 받아 검토와 저장을 제공한다. |
| 4 | 같은 작업 비교 | 고정 입력의 예상 결과를 확인하고 직접 실행과 TLA 사용의 완료 시간과 사용자 개입 횟수를 기록한다. 앱이 열린 상태와 처음 시작한 상태를 구분한다. |

현재 협업은 같은 로컬 네트워크에서 폰이 PC로 직접 HTTPS 요청을 보낸다. 앱은 페어링 파일의 인증서만 신뢰하고 서버 주소도 검사한다. PC 작업자는 페어링 토큰을 확인하고 승인한 텍스트 문서와 지시만 받는다. Windows의 모델 서버는 같은 PC의 루프백 주소에서 실행한다.

시험 전후에 모델 추론 시간, 지시를 보내고 미리 보기까지 걸린 시간, 승인 후 저장 시간, PC 연동 왕복 시간을 분리해 적는다. 보고서 초안에 요구한 정보가 모두 있는지와 원본 문서가 유지됐는지 확인한다.

## 빌드와 검증

Windows에서 `scripts/build-mobile-model-runner.ps1`에 Android NDK r27d, Ninja 및 `llama.cpp` 소스 커밋 `c212d25ad34ff1fdf775793cda07e009560cf66b`의 디렉터리를 전달해 Android ARM64 실행 파일을 만든다. `scripts/build-mobile-apk.ps1`에 JDK 17, Android 35의 `android.jar`, Android Build Tools 35 및 이 `llama-simple` 실행 파일을 전달한다. APK에 실행 파일을 묶고, 모델 가중치는 앱에서 GGUF 파일을 선택해 가져온다. `-Probe` 옵션은 실기 엔진 검증용 계측을 추가한 별도 APK를 만든다.

Windows에서 `llama-server`를 `127.0.0.1:18080`에 열고, `python scripts/pair-mobile-wifi.py <PC의 사설 IPv4> <새 페어링 폴더>`로 PC 인증서와 폰용 `pairing.json`을 생성한다. Windows에 Git만 설치한 경우 `--openssl`로 Git에 포함된 OpenSSL의 경로를 지정할 수 있다. `python runtime/mobile_worker.py --pairing-dir <페어링 폴더>`로 작업자를 시작한다. 앱의 **PC 페어링 파일 가져오기**에서 `pairing.json`을 선택한다. 폰에 보낼 파일은 `pairing.json` 한 개이며 서명용 개인 키는 PC에 보관한다. PC 주소가 바뀌면 새 페어링 파일을 만든다. 앱에서 UTF-8 회의 메모를 선택하면 보내기 전에 대상 PC와 원문을 확인할 수 있다.

`tests/mobile_collaboration.py`는 플립4의 검증용 APK에서 로컬 추론, 저장 후 앱 재시작, Windows 작업 왕복과 결과 저장을 확인하고 JSON을 출력한다. 계측 시험은 합성 문서와 별도의 앱 전용 저장 디렉터리를 쓴다. 실제 화면에서의 승인 동작과 사람이 같은 작업을 하는 시간은 별도로 측정한다.

## 첫 실기 계측

2026년 11월 25일, SM-F721N과 Windows PC 한 대를 USB로 연결했다. 아래 수치는 최종 빌드에서 각 경로를 한 번 계측한 결과다.

| 경로 | 걸린 시간 | 확인한 결과 |
| --- | ---: | --- |
| 폰 단독, 비행기 모드 | 미리 보기까지 1,522 ms, 저장 10 ms | `우유`를 저장하고 앱 프로세스 종료 후 같은 본문과 해시를 복원했다. |
| 폰에서 Windows로 위임 | 왕복 6,610 ms, PC 추론 6,590 ms | 세 문서의 담당자와 기한이 각각 맞는지 확인하고 폰에 초안을 저장했다. |
| 일반 APK 시작 | 348 ms | 실기에서 Android가 보고한 콜드 스타트 시간이다. |

## Wi-Fi와 대형 모델 실기 계측

같은 플립4의 Wi-Fi 주소에서 Windows 작업자가 직접 요청을 받았다. USB 포트 포워딩 없이 HTTPS로 세 문서와 결과를 왕복했고, 결과의 담당자와 기한을 대조했다. 아래 시간은 각각 한 번의 실기 앱 엔진 계측 결과다.

| 경로 | 걸린 시간 |
| --- | ---: |
| 폰 단독, 비행기 모드, Qwen2.5-0.5B-Instruct Q4_K_M | 미리 보기 2,036 ms |
| 폰 단독, 비행기 모드, Qwen2.5-3B-Instruct Q4_K_M | 미리 보기 8,343 ms |
| Wi-Fi로 Windows에 위임, Windows Qwen2.5-3B-Instruct Q4_K_M | 왕복 6,575 ms, PC 추론 6,504 ms |

앱의 경량·대형 모델은 서로 다른 파일로 유지한다. 첫 선택은 경량 모델이다. 대형 모델도 GGUF 파일 선택으로 교체할 수 있으며, 위 시험의 3B 양자화 파일은 약 1.96 GiB다. 실제 손가락 입력, 사람의 비교 작업 시간, 배터리는 아직 계측하지 않았다.

플립4의 슬롯 두 개는 GGUF 메타데이터와 기기 파일 해시를 대조했다. 경량 슬롯은 **Qwen2.5-0.5B-Instruct Q4_K_M** 491,400,032바이트(469 MiB), 대형 슬롯은 **Qwen2.5-3B-Instruct Q4_K_M** 2,104,932,768바이트(1.96 GiB)다. [0.5B 원본](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF) · [3B 원본](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF)

Windows 초안은 담당자와 기한 세 쌍을 정확히 포함했으며, 원문에 근거가 없는 문장도 생성했다. 앱에서 검토한 뒤 저장하는 흐름을 유지한다.

## 플립4 메모 응답 속도 시험

`메모에 우유 추가`와 `메모에 '우유'를 적어줘.`처럼 정해진 구문은 앱이 추가할 내용을 바로 추출한다. 명령을 분류하거나 결과를 만들기 위해 모델을 실행할 필요가 없다. 미리보기 후 저장하며, 그 사이에 메모가 바뀌었으면 변경을 다시 제안한다. `MobileProbe`의 `direct` 모드는 따옴표 안의 여러 단어, 부정·삭제·복합 지시의 직접 경로 제외, 경량 모델로 해석하는 구문, 승인 전 원문 유지, 승인 후 저장 및 오래된 승인 거부를 확인한다. 앱 엔진 내부에서 메모를 읽고 미리보기 내용을 준비하기까지 100회씩 두 번 계측한 중앙값은 **0.26~0.27 ms**, 95백분위수는 **0.41~0.97 ms**였다. 화면이 실제로 그려지는 시간은 계측에서 제외했다.

네이티브 벤치마크는 같은 3B GGUF와 같은 한국어 프롬프트를 사용하고 매 요청마다 `우유`를 추가하는 JSON을 검증한다. 첫 요청에는 모델과 컨텍스트 초기화가 포함된다. 뒤 세 요청은 모델과 컨텍스트를 유지하고 이전 요청의 KV 상태를 지운 뒤 추론한다. 파일 시스템 캐시 또는 기기 온도를 강제로 맞추는 조작은 하지 않았다.

| CPU 스레드 | 첫 요청 | 모델 유지 후 중앙값 |
| --- | ---: | ---: |
| 4, 첫 측정 | 7.66초 | 6.67초 |
| 2 | 13.76초 | 15.56초 |
| 6 | 9.00초 | 9.58초 |
| 8 | 10.51초 | 9.90초 |
| 4, 마지막 재측정 | 11.18초 | 10.51초 |

4스레드로 재사용했을 때 첫 요청보다 0.66~0.99초 짧았다. 벤치마크 프로세스 최대 RSS는 약 2.02 GiB였다. CPU 시험 중 배터리 센서는 28.1°C에서 33.0°C로 변했다. GPU Vulkan 빌드는 Adreno 730을 열었으며, 전체 오프로딩과 8개 레이어 부분 오프로딩 모두 모델을 올리는 중 `SIGSEGV`로 종료됐다.

OpenCL은 Adreno 730에 37개 레이어 전체, 8개, 1개를 각각 오프로딩하고 두 요청을 시험했다. 전체 오프로딩은 첫 요청 29.09초, 재사용 요청 4.42초였고 8개는 각각 34.23초와 15.84초였다. 두 구성의 출력은 메모 추가 계약을 통과하지 못했다. 1개는 두 요청 모두 정확했고 각각 25.82초와 7.74초였다. 일반 APK에는 메모 직접 처리 경로를 적용했다. 모델과 컨텍스트 유지 및 GPU 오프로딩은 별도 계측 APK에서 실행했다.

재현 시 `scripts/build-mobile-model-runner.ps1`로 Android ARM64 모델 실행기를 먼저 빌드한다. Vulkan은 Visual Studio 개발자 PowerShell에서 `-VulkanSdk`와 별도 `-OutDir`을 지정한다. OpenCL은 별도 `-OutDir`과 Khronos [OpenCL-Headers](https://github.com/KhronosGroup/OpenCL-Headers/tree/82f60316cc142e7b21dc1d8983b26de18858fbd9)의 `-OpenCLHeaders`, 시험 폰에서 가져온 `/vendor/lib64/libOpenCL.so`의 `-OpenCLLibrary`를 지정한다.

`scripts/build-mobile-inference-bench.ps1`의 `-ModelBuildDir`에 백엔드를 빌드한 디렉터리를 지정한다. OpenCL 빌드에서는 `-OpenCLLibrary`도 전달한다. 반환된 `mobile-inference-bench`를 `scripts/build-mobile-apk.ps1 -Probe -BenchmarkRunner`에 넘긴다. 계측 APK를 설치한 뒤 `tests/mobile_inference_bench.py`에 `--adb`, `--output`, 선택적으로 `--threads`와 `--gpu-layers`를 넘긴다. OpenCL에는 `--opencl`을 추가한다. 앱 전용 저장소의 대형 슬롯에 3B GGUF가 있어야 한다.

### 터치 입력에서 미리보기 프레임까지

플립4를 실제로 열고 잠금을 푼 상태에서 `메모에 우유 추가`를 사용했다. 계측 화면에 기존 미리보기 흐름을 재현하고 최적화 네 가지를 순서대로 누적했다. 각 구성에 워밍업 4회와 측정 100회를 적용했고, 순서를 돌아가며 바꿨다. 주입한 터치의 손을 떼는 순간부터 미리보기 프레임이 스왑 체인에 제출될 때까지 쟀다. 키보드 입력과 화면 패널의 표시 시간은 계측 범위 밖이다. [Android 프레임 제출 콜백](https://developer.android.com/reference/android/view/ViewTreeObserver#registerFrameCommitCallback(java.lang.Runnable))

| 구성 | 중앙값 | 95백분위수 | 100 ms 이내 |
| --- | ---: | ---: | ---: |
| 기존 흐름 재현 | 50.3 ms | 66.6 ms | 100/100 |
| 1. 입력이 바뀔 때 명령을 해석 | 54.1 ms | 64.5 ms | 100/100 |
| 2. 화면에 표시한 메모의 버전 재사용 | 55.9 ms | 70.9 ms | 100/100 |
| 3. 직접 명령의 백그라운드 스레드 왕복 제거 | 43.0 ms | 57.9 ms | 100/100 |
| 4. 기존 화면 안에 미리보기를 표시 | 22.1 ms | 28.1 ms | 100/100 |

각 미리보기의 내용과 원본 버전을 확인했다. 500회 동안 원문이 유지되고, 승인 시 한 번 저장되며 오래된 버전의 승인은 거부되는 것을 검증했다. 최적화 네 가지는 계측 화면에서 비교했다. `-Probe` APK를 설치한 상태에서 `adb -d shell am instrument -w -e mode memo-latency org.aios.mobile/.MobileProbe`로 실행하고 앱 전용 `files/latency-probe/report.json`에서 결과를 읽는다.

일반 앱에는 같은 화면의 미리보기와 직접 명령의 백그라운드 왕복 제거를 적용했다. 화면에 표시된 메모의 버전을 사용하고 저장할 때 디스크의 버전을 다시 확인한다. 입력이 바뀌면 표시된 미리보기를 닫고 진행 중이던 추론의 결과도 버린다. `production-memo` 계측은 일반 앱의 화면과 처리 코드를 별도의 시험용 메모에서 실행했다. 100회 모두 100 ms 이내였으며, 중앙값 **11.9 ms**, 95백분위수 **21.9 ms**, 최댓값 **22.6 ms**였다. 취소, 지시 변경, 경량 모델 해석, 오래된 버전 저장 거부, 새 버전으로 다시 승인하는 흐름도 통과했다.

대화 화면 적용 후 같은 방식으로 재시험했다. 입력이 대화에 들어가고 입력창이 비워지며, 메모 승인과 취소는 대화 화면에서 수행된다. 100회 모두 100 ms 이내였으며, 중앙값 **17.2 ms**, 95백분위수 **20.2 ms**, 최댓값 **22.4 ms**였다.

변경 후 회귀 시험에서 비행기 모드 경량·대형 모델은 각각 1.72초, 8.66초에 미리보기를 만들었고, 저장 후 프로세스를 종료해도 원문과 버전이 복원됐다. Windows 로컬 모델의 Wi-Fi 보고서 왕복은 6.35초였다.

### 안드로이드 앱에서 예약과 다른 앱 조작

- 시간에 맞춰 알림을 보내고, 사용자가 알림을 누르면 게임을 여는 흐름은 안드로이드 API로 구현할 수 있다. 정확한 알람은 앱의 용도와 특수 접근 권한에 따라 가능하다. [알람 예약](https://developer.android.com/develop/background-work/services/alarms) · [백그라운드 화면 실행](https://developer.android.com/guide/components/activities/secure-bal)
- 잠금 해제 후 화면의 버튼을 누르는 흐름은 사용자가 접근성 서비스를 활성화하고, 게임에서 대상 UI를 식별할 방법과 자동화 허용 조건이 있을 때 구현할 수 있다. 별도 화면 캡처를 사용하는 경우 매 세션 사용자 승인이 필요하다. [접근성 서비스](https://developer.android.com/reference/android/accessibilityservice/AccessibilityService) · [화면 캡처](https://developer.android.com/media/grow/media-projection)
- PIN 등이 걸린 상태에서 일반 앱은 사용자 인증을 대신해 잠금을 풀 수 없다. Google Play는 접근성 API를 사용해 앱이 스스로 행동을 시작·계획·실행하는 방식을 제한하며, 정해진 규칙에 따른 자동화를 별도로 다룬다. [Android 화면 잠금](https://developer.android.com/reference/android/app/KeyguardManager) · [Google Play 접근성 정책](https://support.google.com/googleplay/android-developer/answer/10964491)

#### TLA의 검색과 앱 작업 도구

**대화**에서 하고 싶은 일을 보낸다. 형식이 명확한 요청은 즉시 도구로 연결한다. 그 밖의 요청은 선택한 로컬 GGUF 모델이 앱 열기, 버튼 누르기, Play 스토어에서 앱 찾기, 웹 검색 중 작업을 제안한다. 모델이 뽑은 앱 이름과 버튼 이름은 사용자 지시에 있는 표현을 검증한 뒤 사용한다. 모델이 제안한 동작은 확인 후 진행하며, 정보가 부족하면 대화에서 더 물어본다.

대화에서도 `Chrome 열어줘`, `시험 앱에서 출석 눌러줘`처럼 요청할 수 있다. 앱 이름이 일부만 일치하면 확인을 요청한다. 후보가 여러 개면 앱을 고를 수 있고, 후보를 찾지 못하면 홈 화면에 표시된 앱 이름을 묻는다. 다른 앱의 버튼을 누르는 요청은 대상과 동작을 보여준 뒤 승인받는다. `플레이 스토어에서 마스터 듀얼 설치해 줘`는 승인 후 공식 상품 페이지를 연다. 다른 앱 이름은 Play 스토어 검색 결과를 열며, 실제 설치는 스토어에서 진행한다.

**도구 · 설정 → 수동 앱 작업**에서는 Android 설정에서 **TLA 앱 작업** 접근성 서비스를 켠 뒤 순서를 직접 구성할 수 있다. 앱과 대상 화면 요소를 지정하고, **단계 추가**로 최대 8단계를 모아 **단계 실행**으로 승인한다. **화면 문구 기다리기**는 지정한 문구가 표시되면 다음 단계로 넘어간다. **화면 확인 후 승인**은 문구가 표시된 화면에서 **확인하고 계속**을 누를 때까지 최대 45초 기다린다. 승인할 화면이 바뀌거나 **TLA 중지**를 누르면 후속 실행을 중단한다.

앱 작업은 잠금이 풀린 상태에서 승인한 패키지의 활성 화면만 확인한다. 각 단계 직전에 화면과 대상 요소를 다시 확인해 접근성 클릭 또는 카드 영역 내 스와이프를 전달한다. 다른 앱, 복수 후보, 잠금, 단계당 15초 제한, TLA 화면 복귀 시 멈춘다. 이미 전달된 입력의 결과는 대상 앱에서 확인한다. 화면 요소가 접근성 트리에 없는 게임은 이 경로로 제어할 수 없다. 대상 앱의 허용 정책과 화면을 개별 검증해야 하며 예약 실행은 별도 기능이다. [Android 접근성 서비스](https://developer.android.com/reference/android/accessibilityservice/AccessibilityService)

`-Probe` APK의 `agent-actions` 계측으로 검색 승인과 취소, 안전한 URL 인코딩, 중복 요소와 패키지 불일치 거부, 테스트 출석 버튼 누르기 및 카드 양방향 스와이프를 확인한다. 실제 접근성 서비스 활성화 상태에서도 테스트 화면에서 같은 동작을 수행할 수 있다. 대기 후 중단 검사에는 약 15초가 추가된다.

플립4에서 접근성 서비스를 켠 뒤 TLA와 패키지가 다른 시험 앱을 대상으로 한 번 누르기, 양방향 스와이프, 승인 취소, 대상이 없을 때 중단을 확인했다. 실제 게임과 데이팅 계정의 동작은 시험하지 않았다.

여러 단계 시험에서는 별도 앱의 버튼을 누른 뒤 오른쪽으로 한 번 스와이프했다. 중간 단계에 없는 버튼을 넣었을 때는 앞 단계의 클릭만 남았고, 뒤 단계의 스와이프는 실행되지 않았다. 별도 실행에서 플립4 화면 위의 **중지** 버튼을 누르자 오버레이가 사라지고 뒤 단계의 스와이프는 실행되지 않았다.

플립4의 별도 시험 앱에서 출석 버튼을 한 번 누르고 완료 문구를 확인한 뒤 승인을 기다리는 것도 검증했다. 화면에 **확인하고 계속**이 표시되는 동안 스와이프 횟수는 0이었고, 승인 후 오른쪽으로 한 번 스와이프했다.

대화에서 `시험 앱에서 오늘 출석을 챙겨줘`처럼 목표를 보내면 TLA가 그 앱의 화면을 열고, 실제로 표시된 접근성 버튼 이름을 로컬 모델에 전달한다. 플립4의 별도 시험 앱에서 모델이 설정 버튼과 출석 버튼 중 출석을 골랐고, 화면 위에서 제안한 동작을 승인한 뒤에만 한 번 눌렀다. 이 경로는 화면에서 다음 한 동작을 제안한다.

마스터 듀얼 첫 화면은 플립4에서 게임 창의 접근성 요소 6개를 공개했으며 이름이 붙은 클릭 대상은 0개였다. 타이틀을 직접 터치하니 업데이트된 사용 약관 재동의 안내가 나왔다. 두 화면의 이미지를 별도로 폰의 CPU에서 llama.cpp에 전달한 단일 실행 시험에서 **Qwen3.5-0.8B Q4_K_M + F16**은 두 화면을 모두 타이틀로 분류했다(7.1~8.1초). **Qwen3.5-2B Q4_K_M + F16**은 두 화면을 각각 타이틀과 약관으로 분류했다(27.3~30.2초). 이미지 토큰 상한을 96으로 낮춘 재시험에서도 두 화면을 구분했고 15.5~15.7초가 걸렸다. 이 시험은 두 이미지의 분류이며, Android 앱의 실시간 비전 추론과 게임 출석 자동화는 별도 구현이 필요하다. [llama.cpp 멀티모달 문서](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md)

iOS에서는 단축어의 시간 트리거와 앱이 공개한 App Intents를 조합할 수 있다. 대상 게임이 출석 동작을 공식적으로 노출하면 예약 실행을 시험할 수 있다. 일반 배포 앱용 공개 API로 다른 앱의 임의 버튼을 제어하는 경로는 확인되지 않았다. Xcode의 XCUIAutomation은 테스트 환경에서 앱 UI를 제어할 수 있다. [Apple 단축어 자동화](https://support.apple.com/guide/shortcuts/add-automations-apdfbdbd7123/ios) · [App Intents](https://developer.apple.com/documentation/appintents) · [XCUIAutomation](https://developer.apple.com/documentation/XCUIAutomation/recording-ui-automation-for-testing)

### 비교용 로컬 모델

비교 모델은 개발 PC의 `build/local-models`에 저장한다. 아래는 다운로드 파일 크기다. 실행 중에는 작업 버퍼와 문맥을 유지하는 메모리가 추가로 필요하다. 플립4에서 검증한 기본 모델은 Qwen2.5-0.5B-Instruct Q4_K_M이다. 다른 모델을 앱에 적용하려면 각 모델의 채팅 템플릿으로 한국어 지시와 JSON 응답을 별도로 확인한다.

| 파일 | 용량 | 출처 |
| --- | ---: | --- |
| `Qwen3.5-0.8B-Q4_K_M.gguf` | 0.50 GiB | [Unsloth 변환본](https://huggingface.co/unsloth/Qwen3.5-0.8B-GGUF) |
| `gemma-3-1b-it-Q4_K_M.gguf` | 0.75 GiB | [ggml-org 변환본](https://huggingface.co/ggml-org/gemma-3-1b-it-GGUF) |
| `Qwen3.5-2B-Q4_K_M.gguf` | 1.19 GiB | [Unsloth 변환본](https://huggingface.co/unsloth/Qwen3.5-2B-GGUF) |
| `SmolLM3-Q4_K_M.gguf` | 1.78 GiB | [ggml-org 변환본](https://huggingface.co/ggml-org/SmolLM3-3B-GGUF) |
| `granite-4.0-micro-Q4_K_M.gguf` | 1.96 GiB | [IBM 배포본](https://huggingface.co/ibm-granite/granite-4.0-micro-GGUF) |
| `Qwen3-4B-Instruct-2507-Q4_K_M.gguf` | 2.33 GiB | [Unsloth 변환본](https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF) |
| `Qwen3.5-9B-Q4_K_M.gguf` | 5.29 GiB | [Unsloth 변환본](https://huggingface.co/unsloth/Qwen3.5-9B-GGUF) |
| `gpt-oss-20b-MXFP4.gguf` | 11.28 GiB | [ggml-org 변환본](https://huggingface.co/ggml-org/gpt-oss-20b-GGUF) |

폰이나 메모리가 적은 PC는 경량 0.5B~2B에 먼저 맞춘다. PC에서 빠른 텍스트 작업은 Qwen3-4B-Instruct-2507 Q4_K_M, 12 GiB급 VRAM에서 더 복잡한 요청을 비교할 때는 Qwen3.5-9B Q4_K_M을 후보로 둔다. gpt-oss-20b는 가중치 외 여유 메모리까지 고려해 16 GiB 이상 VRAM을 권장하며 CPU와 GPU에 나눠 올리는 구성도 가능하다. Qwen3.5는 텍스트 GGUF만 다운로드했다. 화면 이해를 적용하려면 해당 모델의 비전 구성 요소와 별도 검증이 필요하다.

Windows RTX 5070 Ti Laptop GPU에서 llama.cpp `b12675`, CUDA, 문맥 2,048토큰으로 두 후보의 전 레이어를 GPU에 올렸다. 한국어 메모 추출 예제 세 건은 두 모델 모두 정확했다. 모델을 띄운 상태에서 첫 출력과 작업 완료의 중앙값은 4B가 각각 **46 ms / 180 ms**, 9B가 **139 ms / 392 ms**였다. 오래 걸리는 문서 종합의 성능과 정확도는 이 시험 범위 밖이다. 8개 GGUF는 총 26,921,589,248바이트(25.07 GiB)이며, 배포 파일의 길이 및 SHA-256을 대조했다.

## 선택형 계정 연결

폰에서는 경량 로컬 모델, Windows 위임에서는 PC 로컬 모델이 기본값이다. 앱에서 ChatGPT 또는 Claude를 선택하면 Windows를 거쳐 해당 서비스로 전달할 문서와 지시를 먼저 보여준다. Google Drive로 내보내려면 폰에 저장한 보고서를 보고 별도로 승인한다. Windows에 계정 연결이 없는 경우 요청이 실패하고 앱에서 이유를 표시한다.

- **ChatGPT**는 Windows에서 Node.js와 PowerShell 7을 사용한다. [공식 DevKit](https://github.com/openai/sign-in-with-chatgpt-devkit)의 `0a36fefeb913055c8c7a1a29b63d82b96b2e841a`를 `build/sdk/sign-in-with-chatgpt-devkit`에 체크아웃하고, 해당 디렉터리에서 `npm ci --ignore-scripts`, `npm run build --workspace @siwc/local`, `npm audit fix --ignore-scripts --omit=dev --workspace @siwc/local`을 차례로 실행한다. 저장소 루트에서 `node runtime/chatgpt_oauth.mjs connect`를 실행한 뒤 브라우저에서 로그인과 플랜 사용을 승인한다. `status`와 `disconnect`도 지원한다. 특정 모델을 사용할 경우 Windows 작업자 환경에 `AIOS_CHATGPT_MODEL`을 지정한다. [OpenAI 연결 안내](https://developers.openai.com/siwc/token-sharing-open-source)
- **Claude**는 Windows에 [공식 Anthropic CLI](https://github.com/anthropics/anthropic-cli/releases)를 설치하고 `ant auth login --profile aios`에서 Claude Console 워크스페이스를 연결한다. Windows 작업자 환경에 `AIOS_CLAUDE_MODEL`을 지정한다. CLI가 PATH에 없으면 `AIOS_ANT_CLI`에 `ant.exe` 경로를 지정한다. 연결을 해제하려면 `ant auth logout --profile aios`를 실행한다. [Claude CLI 인증 안내](https://platform.claude.com/docs/en/cli-sdks-libraries/cli/authentication)
- **Google Drive**로 내보내려면 Windows 작업자의 Python 환경에 `google-auth-oauthlib`를 설치하고 PowerShell 7을 준비한다. Drive API를 사용 설정한 Google Cloud 프로젝트의 데스크톱 OAuth 클라이언트 JSON을 `python runtime/mobile_drive.py connect --client-json <파일>`에 넘긴 뒤 브라우저에서 승인한다. `drive.file` 권한을 사용하며 Windows에서 `status`와 `disconnect`를 지원한다. 기존 문서를 가져올 때는 Android 파일 선택기에 표시되는 Drive를 사용할 수 있다. [Google 데스크톱 OAuth](https://developers.google.com/identity/protocols/oauth2/native-app) · [Drive 업로드](https://developers.google.com/workspace/drive/api/guides/manage-uploads)

ChatGPT와 Drive 인증 정보는 Windows 사용자 계정의 DPAPI로 보호한다. Claude 인증은 공식 CLI의 AIOS 프로필이 관리한다.

Windows에서 세 서비스가 연결되지 않았을 때 안내 응답이 돌아오는 것과 기본 로컬 추론이 계속 작동하는 것을 확인했다. 실계정 승인, 외부 모델 응답, Drive 실제 업로드는 검증 대기 중이다.
