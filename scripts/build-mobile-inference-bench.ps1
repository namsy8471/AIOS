param(
    [Parameter(Mandatory)][string]$Ndk,
    [Parameter(Mandatory)][string]$Source,
    [string]$ModelBuildDir = 'build/mobile-model-runner',
    [string]$OpenCLLibrary
)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$ndkBin = Join-Path (Resolve-Path -LiteralPath $Ndk).Path 'toolchains/llvm/prebuilt/windows-x86_64/bin'
$sourcePath = (Resolve-Path -LiteralPath $Source).Path
$build = (Resolve-Path -LiteralPath $ModelBuildDir).Path
$benchSource = Join-Path (Split-Path $PSScriptRoot) 'tests/mobile_inference_bench.cpp'
$runner = Join-Path $build 'bin/mobile-inference-bench'
$libraries = @(
    "$build/src/libllama.a",
    "$build/ggml/src/libggml.a",
    "$build/ggml/src/libggml-cpu.a"
)
$vulkan = "$build/ggml/src/ggml-vulkan/libggml-vulkan.a"
$hasVulkan = Test-Path -LiteralPath $vulkan
if ($hasVulkan) { $libraries += $vulkan }
if ($OpenCLLibrary) { $libraries += "$build/ggml/src/ggml-opencl/libggml-opencl.a" }
$libraries += "$build/ggml/src/libggml-base.a"
if ($hasVulkan) { $libraries += '-lvulkan' }
if ($OpenCLLibrary) { $libraries += (Resolve-Path -LiteralPath $OpenCLLibrary).Path }
$compile = @('--target=aarch64-none-linux-android33', '-O3', '-std=c++17', '-static-libstdc++',
    "-I$sourcePath/include", "-I$sourcePath/ggml/include", $benchSource)
& (Join-Path $ndkBin 'clang++.exe') @compile @libraries -lm -ldl -pthread -latomic -o $runner
& (Join-Path $ndkBin 'llvm-strip.exe') --strip-unneeded $runner
Get-Item -LiteralPath $runner | Select-Object FullName,Length
