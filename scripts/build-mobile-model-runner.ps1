param(
    [Parameter(Mandatory)][string]$Ndk,
    [Parameter(Mandatory)][string]$Ninja,
    [Parameter(Mandatory)][string]$Source,
    [string]$OutDir = 'build/mobile-model-runner'
)
$ErrorActionPreference = 'Stop'
$ndkPath = (Resolve-Path -LiteralPath $Ndk).Path
$ninjaPath = (Resolve-Path -LiteralPath $Ninja).Path
$sourcePath = (Resolve-Path -LiteralPath $Source).Path
$toolchain = Join-Path $ndkPath 'build/cmake/android.toolchain.cmake'
$out = (New-Item -ItemType Directory -Force $OutDir).FullName
cmake -S $sourcePath -B $out -G Ninja "-DCMAKE_MAKE_PROGRAM=$ninjaPath" `
    "-DCMAKE_TOOLCHAIN_FILE=$toolchain" -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-33 `
    -DANDROID_STL=c++_static -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF `
    -DGGML_NATIVE=OFF -DGGML_OPENMP=OFF -DGGML_BLAS=OFF -DLLAMA_BUILD_EXAMPLES=ON `
    -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_TOOLS=OFF -DLLAMA_BUILD_SERVER=OFF
if ($LASTEXITCODE) { exit $LASTEXITCODE }
cmake --build $out --target llama-simple --parallel 6
if ($LASTEXITCODE) { exit $LASTEXITCODE }
$runner = Join-Path $out 'bin/llama-simple'
& (Join-Path $ndkPath 'toolchains/llvm/prebuilt/windows-x86_64/bin/llvm-strip.exe') --strip-unneeded $runner
if ($LASTEXITCODE) { exit $LASTEXITCODE }
Get-Item $runner | Select-Object FullName,Length
