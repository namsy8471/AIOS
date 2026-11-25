# 플립4와 Windows 협업 MVP

Android 앱이 한국어 지시를 받고, Windows PC는 더 긴 문서 작업을 맡는다. 첫 시연의 기준 기기는 갤럭시 Z 플립4 SM-F721N이다. Android 앱과 Windows 작업자는 같은 요청 형식을 사용하므로 이후 PC 작업자를 네이티브 애플리케이션이나 AIOS 가상 머신으로 옮길 수 있다.

| 단계 | 결과 | 검증 |
| --- | --- | --- |
| 1 | 플립4에 설치 가능한 APK | 실기에서 앱이 시작되고 메모와 PC 작업 화면이 열린다. |
| 2 | 휴대폰 단독 메모 작업 | 비행기 모드에서 한국어 지시를 로컬 모델로 해석하고, 미리 보기에서 승인하면 저장한다. 앱을 종료하고 다시 열어 본문을 비교한다. |
| 3 | Windows 협업 | 폰에서 선택한 세 문서의 이름과 보낼 내용을 확인한다. 승인 후 Windows 로컬 모델이 회의 보고서 초안을 생성하고 폰이 결과를 받아 검토와 저장을 제공한다. |
| 4 | 같은 작업 비교 | 고정 입력의 예상 결과를 확인하고 직접 실행과 AIOS 사용의 완료 시간과 사용자 개입 횟수를 기록한다. 앱이 열린 상태와 처음 시작한 상태를 구분한다. |

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
| 폰 단독, 비행기 모드, Qwen2.5-0.5B | 미리 보기 2,036 ms |
| 폰 단독, 비행기 모드, Qwen2.5-3B | 미리 보기 8,343 ms |
| Wi-Fi로 Windows에 위임, Windows Qwen2.5-3B | 왕복 6,575 ms, PC 추론 6,504 ms |

앱의 경량·대형 모델은 서로 다른 파일로 유지한다. 첫 선택은 경량 모델이다. 대형 모델도 GGUF 파일 선택으로 교체할 수 있으며, 위 시험의 3B 양자화 파일은 약 1.96 GiB다. 실제 손가락 입력, 사람의 비교 작업 시간, 배터리는 아직 계측하지 않았다.

Windows 초안은 담당자와 기한 세 쌍을 정확히 포함했으며, 원문에 근거가 없는 문장도 생성했다. 앱에서 검토한 뒤 저장하는 흐름을 유지한다.

## 선택형 계정 연결

폰에서는 경량 로컬 모델, Windows 위임에서는 PC 로컬 모델이 기본값이다. 앱에서 ChatGPT 또는 Claude를 선택하면 Windows를 거쳐 해당 서비스로 전달할 문서와 지시를 먼저 보여준다. Google Drive로 내보내려면 폰에 저장한 보고서를 보고 별도로 승인한다. Windows에 계정 연결이 없는 경우 요청이 실패하고 앱에서 이유를 표시한다.

- **ChatGPT**는 Windows에서 Node.js와 PowerShell 7을 사용한다. [공식 DevKit](https://github.com/openai/sign-in-with-chatgpt-devkit)의 `0a36fefeb913055c8c7a1a29b63d82b96b2e841a`를 `build/sdk/sign-in-with-chatgpt-devkit`에 체크아웃하고, 해당 디렉터리에서 `npm ci --ignore-scripts`, `npm run build --workspace @siwc/local`, `npm audit fix --ignore-scripts --omit=dev --workspace @siwc/local`을 차례로 실행한다. 저장소 루트에서 `node runtime/chatgpt_oauth.mjs connect`를 실행한 뒤 브라우저에서 로그인과 플랜 사용을 승인한다. `status`와 `disconnect`도 지원한다. 특정 모델을 사용할 경우 Windows 작업자 환경에 `AIOS_CHATGPT_MODEL`을 지정한다. [OpenAI 연결 안내](https://developers.openai.com/siwc/token-sharing-open-source)
- **Claude**는 Windows에 [공식 Anthropic CLI](https://github.com/anthropics/anthropic-cli/releases)를 설치하고 `ant auth login --profile aios`에서 Claude Console 워크스페이스를 연결한다. Windows 작업자 환경에 `AIOS_CLAUDE_MODEL`을 지정한다. CLI가 PATH에 없으면 `AIOS_ANT_CLI`에 `ant.exe` 경로를 지정한다. 연결을 해제하려면 `ant auth logout --profile aios`를 실행한다. [Claude CLI 인증 안내](https://platform.claude.com/docs/en/cli-sdks-libraries/cli/authentication)
- **Google Drive**로 내보내려면 Windows 작업자의 Python 환경에 `google-auth-oauthlib`를 설치하고 PowerShell 7을 준비한다. Drive API를 사용 설정한 Google Cloud 프로젝트의 데스크톱 OAuth 클라이언트 JSON을 `python runtime/mobile_drive.py connect --client-json <파일>`에 넘긴 뒤 브라우저에서 승인한다. `drive.file` 권한을 사용하며 Windows에서 `status`와 `disconnect`를 지원한다. 기존 문서를 가져올 때는 Android 파일 선택기에 표시되는 Drive를 사용할 수 있다. [Google 데스크톱 OAuth](https://developers.google.com/identity/protocols/oauth2/native-app) · [Drive 업로드](https://developers.google.com/workspace/drive/api/guides/manage-uploads)

ChatGPT와 Drive 인증 정보는 Windows 사용자 계정의 DPAPI로 보호한다. Claude 인증은 공식 CLI의 AIOS 프로필이 관리한다.

Windows에서 세 서비스가 연결되지 않았을 때 안내 응답이 돌아오는 것과 기본 로컬 추론이 계속 작동하는 것을 확인했다. 실계정 승인, 외부 모델 응답, Drive 실제 업로드는 검증 대기 중이다.
