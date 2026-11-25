param(
    [Parameter(Mandatory)][string]$Ndk,
    [Parameter(Mandatory)][string]$Ninja,
    [Parameter(Mandatory)][string]$Source,
    [string]$OutDir = 'build/mobile-model-runner',
    [string]$VulkanSdk,
    [string]$OpenCLHeaders,
    [string]$OpenCLLibrary,
    [switch]$Vision
)
$ErrorActionPreference = 'Stop'
$ndkPath = (Resolve-Path -LiteralPath $Ndk).Path
$ninjaPath = (Resolve-Path -LiteralPath $Ninja).Path
$sourcePath = (Resolve-Path -LiteralPath $Source).Path
$toolchain = Join-Path $ndkPath 'build/cmake/android.toolchain.cmake'
$out = (New-Item -ItemType Directory -Force $OutDir).FullName
$backend = @('-DGGML_VULKAN=OFF', '-DGGML_OPENCL=OFF')
if ($OpenCLHeaders -or $OpenCLLibrary) {
    if ($VulkanSdk -or !$OpenCLHeaders -or !$OpenCLLibrary) { throw 'Provide both OpenCL paths for an OpenCL-only build' }
    $headers = (Resolve-Path -LiteralPath $OpenCLHeaders).Path
    $library = (Resolve-Path -LiteralPath $OpenCLLibrary).Path
    $backend = @('-DGGML_VULKAN=OFF', '-DGGML_OPENCL=ON', '-DGGML_OPENCL_USE_ADRENO_KERNELS=ON',
        '-DGGML_OPENCL_EMBED_KERNELS=ON', "-DOpenCL_INCLUDE_DIR=$headers", "-DOpenCL_LIBRARY=$library")
}
if ($VulkanSdk) {
    $sdkPath = (Resolve-Path -LiteralPath $VulkanSdk).Path
    $ndkLibraries = "$ndkPath/toolchains/llvm/prebuilt/windows-x86_64/sysroot/usr/lib/aarch64-linux-android/33"
    $backend = @('-DGGML_VULKAN=ON', '-DGGML_OPENCL=OFF', '-DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=BOTH',
        "-DVulkan_INCLUDE_DIR=$sdkPath/Include", "-DVulkan_LIBRARY=$ndkLibraries/libvulkan.so",
        "-DVulkan_GLSLC_EXECUTABLE=$sdkPath/Bin/glslc.exe", "-DSPIRV-Headers_DIR=$sdkPath/Lib/cmake/SPIRV-Headers",
        "-DGGML_VULKAN_SPIRV_INCLUDE_DIR=$sdkPath/Include/spirv-headers")
}
cmake -S $sourcePath -B $out -G Ninja "-DCMAKE_MAKE_PROGRAM=$ninjaPath" `
    "-DCMAKE_TOOLCHAIN_FILE=$toolchain" -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-33 `
    -DANDROID_STL=c++_static -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF `
    -DGGML_NATIVE=OFF -DGGML_OPENMP=OFF -DGGML_BLAS=OFF -DLLAMA_BUILD_EXAMPLES=ON `
    -DLLAMA_BUILD_TESTS=OFF "-DLLAMA_BUILD_TOOLS=$([int]$Vision.IsPresent)" -DLLAMA_CURL=OFF -DLLAMA_BUILD_SERVER=OFF @backend
if ($LASTEXITCODE) { exit $LASTEXITCODE }
$targets = @('llama-simple')
if ($Vision) { $targets += 'llama-mtmd-cli' }
cmake --build $out --target @targets --parallel 6
if ($LASTEXITCODE) { exit $LASTEXITCODE }
foreach ($target in $targets) {
    $runner = Join-Path $out "bin/$target"
    & (Join-Path $ndkPath 'toolchains/llvm/prebuilt/windows-x86_64/bin/llvm-strip.exe') --strip-unneeded $runner
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
    Get-Item $runner | Select-Object FullName,Length
}
