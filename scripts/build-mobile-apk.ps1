param(
    [Parameter(Mandatory)][string]$Jdk,
    [Parameter(Mandatory)][string]$BuildTools,
    [Parameter(Mandatory)][string]$AndroidJar,
    [Parameter(Mandatory)][string]$ModelRunner,
    [string]$OutDir = 'build/mobile-apk',
    [switch]$Probe,
    [string]$BenchmarkRunner
)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$root = Split-Path $PSScriptRoot
$Jdk = (Resolve-Path -LiteralPath $Jdk).Path
$BuildTools = (Resolve-Path -LiteralPath $BuildTools).Path
$AndroidJar = (Resolve-Path -LiteralPath $AndroidJar).Path
$ModelRunner = (Resolve-Path -LiteralPath $ModelRunner).Path
if ($BenchmarkRunner) {
    if (!$Probe) { throw 'BenchmarkRunner requires a probe APK' }
    $BenchmarkRunner = (Resolve-Path -LiteralPath $BenchmarkRunner).Path
}
$env:JAVA_HOME = $Jdk
$javaBin = Join-Path $Jdk 'bin'
$env:Path = "$javaBin;$env:Path"
$out = (New-Item -ItemType Directory -Force $OutDir).FullName
$stage = (New-Item -ItemType Directory -Path (Join-Path $out ([guid]::NewGuid()))).FullName
$classes = (New-Item -ItemType Directory -Path (Join-Path $stage 'classes')).FullName
$android = Join-Path $root 'android'
$sources = @(Get-ChildItem -Recurse -File (Join-Path $android 'src') -Filter '*.java' | ForEach-Object FullName)
$manifest = Join-Path $android 'AndroidManifest.xml'
if ($Probe) {
    $sources += @(Get-ChildItem -Recurse -File (Join-Path $android 'probe') -Filter '*.java' | ForEach-Object FullName)
    $body = Get-Content -Raw -LiteralPath $manifest
    $activityTag = '<activity android:name=".MemoLatencyActivity" android:exported="false" android:screenOrientation="portrait" />'
    $activityTag += '<activity android:name=".ProductionMemoProbe" android:exported="false" android:screenOrientation="portrait" />'
    $instrumentationTag = '<instrumentation android:name=".MobileProbe" android:targetPackage="org.aios.mobile" />'
    $probeManifest = $body.Replace('</application>', "$activityTag</application>").Replace('</manifest>', "$instrumentationTag</manifest>")
    $probeManifest | Set-Content -LiteralPath "$stage/AndroidManifest.xml" -Encoding utf8
    $manifest = "$stage/AndroidManifest.xml"
}
& (Join-Path $javaBin 'javac.exe') --release 11 -encoding UTF-8 -classpath $AndroidJar -d $classes @sources
if ($LASTEXITCODE) { exit $LASTEXITCODE }
& (Join-Path $javaBin 'jar.exe') --create --file "$stage/classes.jar" -C $classes .
if ($LASTEXITCODE) { exit $LASTEXITCODE }
& (Join-Path $BuildTools 'd8.bat') --min-api 33 --lib $AndroidJar --output $stage "$stage/classes.jar"
if ($LASTEXITCODE) { exit $LASTEXITCODE }
$aapt = Join-Path $BuildTools 'aapt2.exe'
& $aapt compile --dir (Join-Path $android 'res') -o "$stage/res.zip"
if ($LASTEXITCODE) { exit $LASTEXITCODE }
& $aapt link --debug-mode -I $AndroidJar --manifest $manifest -o "$stage/unsigned.apk" "$stage/res.zip"
if ($LASTEXITCODE) { exit $LASTEXITCODE }
@'
import pathlib, struct, sys, zipfile

stage, runner = map(pathlib.Path, sys.argv[1:3])

def android_arm64(path):
    binary = path.read_bytes()
    if binary[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", binary, 18)[0] != 183:
        raise SystemExit("Expected an ARM64 ELF model runner")
    program_offset = struct.unpack_from("<Q", binary, 32)[0]
    entry_size, entry_count = struct.unpack_from("<HH", binary, 54)
    interpreters = []
    for index in range(entry_count):
        kind, _, offset, _, _, size = struct.unpack_from("<IIQQQQ", binary, program_offset + index * entry_size)
        if kind == 3:
            interpreters.append(binary[offset:offset + size])
    if interpreters != [b"/system/bin/linker64\0"]:
        raise SystemExit("Expected the Android NDK runner, linked for /system/bin/linker64")
    return binary

with zipfile.ZipFile(stage / "unsigned.apk", "a", compression=zipfile.ZIP_DEFLATED) as apk:
    apk.write(stage / "classes.dex", "classes.dex")
    apk.writestr("lib/arm64-v8a/libllama-runner.so", android_arm64(runner))
    if len(sys.argv) > 3 and sys.argv[3]:
        apk.writestr("lib/arm64-v8a/libllama-bench.so", android_arm64(pathlib.Path(sys.argv[3])))
'@ | python - $stage $ModelRunner $BenchmarkRunner
if ($LASTEXITCODE) { exit $LASTEXITCODE }
& (Join-Path $BuildTools 'zipalign.exe') -f 4 "$stage/unsigned.apk" "$stage/aligned.apk"
if ($LASTEXITCODE) { exit $LASTEXITCODE }
$key = Join-Path $out 'debug.keystore'
if (!(Test-Path -LiteralPath $key)) {
    & (Join-Path $javaBin 'keytool.exe') -genkeypair -keystore $key -storepass android -keypass android `
        -alias aiosdebug -dname 'CN=AIOS Local Development' -keyalg RSA -keysize 2048 -validity 10000
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
}
$apk = Join-Path $out $(if ($Probe) { 'aios-probe.apk' } else { 'aios-debug.apk' })
& (Join-Path $BuildTools 'apksigner.bat') sign --ks $key --ks-key-alias aiosdebug --ks-pass pass:android --out $apk "$stage/aligned.apk"
if ($LASTEXITCODE) { exit $LASTEXITCODE }
& (Join-Path $BuildTools 'apksigner.bat') verify --verbose $apk
if ($LASTEXITCODE) { exit $LASTEXITCODE }
Get-Item -LiteralPath $apk | Select-Object FullName,Length
