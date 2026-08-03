# Copyright (c) 2026 Alex313031 and gz83
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$ArtifactDirectory,

  [string]$InstallerPattern = 'thorium_ARM64_installer.exe',

  [Parameter(Mandatory = $true)]
  [string]$ResultsDirectory,

  [string]$ExpectedSha256 = '',

  [switch]$RequireGui,

  [ValidateRange(30, 1800)]
  [int]$InstallerTimeoutSeconds = 600,

  [ValidateRange(15, 600)]
  [int]$BrowserTimeoutSeconds = 120
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$artifactRoot = (Resolve-Path -LiteralPath $ArtifactDirectory).Path
New-Item -ItemType Directory -Path $ResultsDirectory -Force | Out-Null
$resultRoot = (Resolve-Path -LiteralPath $ResultsDirectory).Path
$transcriptPath = Join-Path $resultRoot 'smoke-test.log'
$resultPath = Join-Path $resultRoot 'smoke-test.json'
$installerStdout = Join-Path $resultRoot 'installer.stdout.txt'
$installerStderr = Join-Path $resultRoot 'installer.stderr.txt'
$browserStdout = Join-Path $resultRoot 'browser.stdout.txt'
$browserStderr = Join-Path $resultRoot 'browser.stderr.txt'
$noSandboxStdout = Join-Path $resultRoot 'browser-no-sandbox.stdout.txt'
$noSandboxStderr = Join-Path $resultRoot 'browser-no-sandbox.stderr.txt'
$noExtensionsStdout = Join-Path $resultRoot 'browser-no-extensions.stdout.txt'
$noExtensionsStderr = Join-Path $resultRoot 'browser-no-extensions.stderr.txt'
$werStdout = Join-Path $resultRoot 'browser-wer.stdout.txt'
$werStderr = Join-Path $resultRoot 'browser-wer.stderr.txt'
$crashRoot = Join-Path $resultRoot 'crash-dumps'
$werDumpDirectory = Join-Path $crashRoot 'wer'
$uninstallerStdout = Join-Path $resultRoot 'uninstaller.stdout.txt'
$uninstallerStderr = Join-Path $resultRoot 'uninstaller.stderr.txt'
$cleanupUninstallerStdout =
    Join-Path $resultRoot 'cleanup-uninstaller.stdout.txt'
$cleanupUninstallerStderr =
    Join-Path $resultRoot 'cleanup-uninstaller.stderr.txt'

$result = [ordered]@{
  SchemaVersion = 6
  RunnerArchitecture = $env:PROCESSOR_ARCHITECTURE
  Installer = $null
  InstallerSha256 = $null
  InstalledBinaryCount = 0
  InstalledNonArm64Tools = [System.Collections.Generic.List[object]]::new()
  HeadlessDiagnostic = $null
  HeadlessError = $null
  HeadlessNoSandboxDiagnostic = $null
  HeadlessNoExtensionsDiagnostic = $null
  HeadlessWerDiagnostic = $null
  WindowsCrashEvents = @()
  CrashArtifacts = [System.Collections.Generic.List[string]]::new()
  GuiRequired = [bool]$RequireGui
  GuiSuccess = $false
  GuiProductFailure = $false
  GuiError = $null
  Checks = [System.Collections.Generic.List[object]]::new()
  CleanupWarnings = [System.Collections.Generic.List[string]]::new()
  Success = $false
  Error = $null
}
$script:result = $result
$failed = $null
$transcriptStarted = $false
$installRoot = Join-Path $env:LOCALAPPDATA 'Thorium\Application'
$browser = Join-Path $installRoot 'thorium.exe'
$testPage = Join-Path $env:RUNNER_TEMP 'thorium-woa-smoke.html'
$profile = Join-Path $env:RUNNER_TEMP 'thorium-woa-smoke-profile'
$noSandboxProfile = Join-Path $env:RUNNER_TEMP 'thorium-woa-no-sandbox-profile'
$noExtensionsProfile = Join-Path $env:RUNNER_TEMP 'thorium-woa-no-extensions-profile'
$werProfile = Join-Path $env:RUNNER_TEMP 'thorium-woa-wer-profile'
$werRegistryRoot =
    'HKCU:\Software\Microsoft\Windows\Windows Error Reporting\LocalDumps'
$werRegistryPath = Join-Path $werRegistryRoot 'thorium.exe'
$werConfigurationCreated = $false
$werRegistryRootCreated = $false
$uninstaller = $null
$uninstallCompleted = $false
$headlessError = $null
$browserProbeStartUtc = $null

function Add-Check {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Name,
    [Parameter(Mandatory = $true)]
    [string]$Detail
  )

  $script:result.Checks.Add([ordered]@{
    Name = $Name
    Detail = $Detail
  })
  Write-Host "PASS: ${Name}: $Detail"
}

function Get-PeMachine {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  $stream = [System.IO.File]::Open(
    $Path,
    [System.IO.FileMode]::Open,
    [System.IO.FileAccess]::Read,
    [System.IO.FileShare]::Read
  )
  try {
    if ($stream.Length -lt 64) {
      throw "PE file is too short: $Path"
    }
    $reader = [System.IO.BinaryReader]::new($stream)
    if ($reader.ReadUInt16() -ne 0x5A4D) {
      throw "PE file has no MZ signature: $Path"
    }
    $stream.Position = 0x3C
    $peOffset = $reader.ReadInt32()
    if ($peOffset -lt 0 -or $peOffset -gt $stream.Length - 6) {
      throw "PE header offset is invalid: $Path"
    }
    $stream.Position = $peOffset
    if ($reader.ReadUInt32() -ne 0x00004550) {
      throw "PE file has no PE signature: $Path"
    }
    return $reader.ReadUInt16()
  } finally {
    $stream.Dispose()
  }
}

function Assert-Arm64Pe {
  param(
    [Parameter(Mandatory = $true)]
    [System.IO.FileInfo[]]$Files,
    [Parameter(Mandatory = $true)]
    [string]$CheckName,
    [string]$RelativeRoot = '',
    [hashtable]$AllowedNonArm64Tools = @{}
  )

  $violations = [System.Collections.Generic.List[string]]::new()
  $allowed = [System.Collections.Generic.List[object]]::new()
  $seenAllowedPaths = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::OrdinalIgnoreCase
  )
  foreach ($file in $Files) {
    $machine = Get-PeMachine -Path $file.FullName
    $relativePath = ''
    if ($RelativeRoot) {
      $relativePath = [System.IO.Path]::GetRelativePath(
        $RelativeRoot,
        $file.FullName
      ).Replace('\', '/')
    }
    if ($AllowedNonArm64Tools.ContainsKey($relativePath)) {
      $allowedMachine = $AllowedNonArm64Tools[$relativePath]
      $null = $seenAllowedPaths.Add($relativePath)
      if ($machine -eq $allowedMachine) {
        $allowed.Add([ordered]@{
          Path = $relativePath
          Machine = ('0x{0:X4}' -f $machine)
        })
      } else {
        $violations.Add((
          '{0}: expected 0x{1:X4}, got 0x{2:X4}' -f
            $file.FullName, $allowedMachine, $machine
        ))
      }
    } elseif ($machine -ne 0xAA64) {
      $violations.Add(('{0}: unexpected machine 0x{1:X4}' -f
          $file.FullName, $machine))
    }
  }
  foreach ($expectedPath in $AllowedNonArm64Tools.Keys) {
    if (-not $seenAllowedPaths.Contains($expectedPath)) {
      $violations.Add("Missing architecture-specific packaging tool: $expectedPath")
    }
  }
  if ($violations.Count -ne 0) {
    throw "Installed PE architecture validation failed:`n$($violations -join "`n")"
  }
  $arm64Count = $Files.Count - $allowed.Count
  $detail = "$arm64Count runtime PE file(s) use machine 0xAA64."
  if ($allowed.Count -ne 0) {
    $detail += " $($allowed.Count) architecture-specific packaging tool(s) were accepted."
  }
  Add-Check -Name $CheckName -Detail $detail
  return $allowed
}

function Write-Utf8File {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [AllowEmptyString()]
    [string]$Contents
  )

  [System.IO.File]::WriteAllText(
    $Path,
    $Contents,
    [System.Text.UTF8Encoding]::new($false)
  )
}

function Record-CrashArtifacts {
  if (-not (Test-Path -LiteralPath $crashRoot -PathType Container)) {
    return
  }
  foreach ($dump in Get-ChildItem -LiteralPath $crashRoot -Filter '*.dmp' `
      -File -Recurse -ErrorAction SilentlyContinue) {
    $result.CrashArtifacts.Add(
      [System.IO.Path]::GetRelativePath(
        $resultRoot,
        $dump.FullName
      ).Replace('\', '/')
    )
  }
}

function Get-WindowsCrashEvents {
  param(
    [Parameter(Mandatory = $true)]
    [DateTime]$StartTime
  )

  $events = @(
    Get-WinEvent -FilterHashtable @{
      LogName = 'Application'
      ProviderName = @('Application Error', 'Windows Error Reporting')
      StartTime = $StartTime
    } -ErrorAction SilentlyContinue |
      Where-Object {
        $_.Message -and $_.Message -match '(?i)\bthorium\.exe\b'
      } |
      Sort-Object -Property TimeCreated |
      Select-Object -Last 20
  )
  return @(
    $events | ForEach-Object {
      [ordered]@{
        TimeCreatedUtc = $_.TimeCreated.ToUniversalTime().ToString('o')
        Provider = $_.ProviderName
        Id = $_.Id
        Message = $_.Message
      }
    }
  )
}

function Wait-ForCrashDumps {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Directory,
    [ValidateRange(1, 60)]
    [int]$TimeoutSeconds = 15
  )

  $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
  $lastSignature = ''
  $stablePolls = 0
  while ([DateTime]::UtcNow -lt $deadline) {
    $dumps = @(
      Get-ChildItem -LiteralPath $Directory -Filter '*.dmp' -File -Recurse `
        -ErrorAction SilentlyContinue |
        Sort-Object -Property FullName
    )
    if ($dumps.Count -ne 0 -and
        @($dumps | Where-Object { $_.Length -eq 0 }).Count -eq 0) {
      $signature = ($dumps | ForEach-Object {
        '{0}:{1}' -f $_.FullName, $_.Length
      }) -join '|'
      if ($signature -eq $lastSignature) {
        ++$stablePolls
        if ($stablePolls -ge 2) {
          return $true
        }
      } else {
        $lastSignature = $signature
        $stablePolls = 0
      }
    }
    Start-Sleep -Milliseconds 500
  }
  return $false
}

function Enable-WerLocalDumps {
  if (Test-Path -LiteralPath $werRegistryPath) {
    throw "Refusing to overwrite an existing WER LocalDumps configuration: $werRegistryPath"
  }
  if (-not (Test-Path -LiteralPath $werRegistryRoot)) {
    New-Item -Path $werRegistryRoot -Force | Out-Null
    $script:werRegistryRootCreated = $true
  }
  New-Item -Path $werRegistryPath -Force | Out-Null
  $script:werConfigurationCreated = $true
  New-ItemProperty `
    -Path $werRegistryPath `
    -Name DumpFolder `
    -PropertyType ExpandString `
    -Value $werDumpDirectory `
    -Force | Out-Null
  New-ItemProperty `
    -Path $werRegistryPath `
    -Name DumpType `
    -PropertyType DWord `
    -Value 1 `
    -Force | Out-Null
  New-ItemProperty `
    -Path $werRegistryPath `
    -Name DumpCount `
    -PropertyType DWord `
    -Value 10 `
    -Force | Out-Null
}

function Disable-WerLocalDumps {
  if ($script:werConfigurationCreated -and
      (Test-Path -LiteralPath $werRegistryPath)) {
    Remove-Item -LiteralPath $werRegistryPath -Recurse -Force
  }
  $script:werConfigurationCreated = $false
  if ($script:werRegistryRootCreated -and
      (Test-Path -LiteralPath $werRegistryRoot)) {
    $rootKey = Get-Item -LiteralPath $werRegistryRoot
    try {
      $hasValues = @($rootKey.GetValueNames()).Count -ne 0
    } finally {
      $rootKey.Dispose()
    }
    $hasSubkeys = @(
      Get-ChildItem -LiteralPath $werRegistryRoot -ErrorAction Stop
    ).Count -ne 0
    if (-not $hasSubkeys -and -not $hasValues) {
      Remove-Item -LiteralPath $werRegistryRoot -Force
    }
  }
  $script:werRegistryRootCreated = $false
}

function Invoke-CapturedProcess {
  param(
    [Parameter(Mandatory = $true)]
    [string]$FilePath,
    [string[]]$Arguments = @(),
    [Parameter(Mandatory = $true)]
    [int]$TimeoutSeconds,
    [Parameter(Mandatory = $true)]
    [string]$StandardOutputPath,
    [Parameter(Mandatory = $true)]
    [string]$StandardErrorPath,
    [string]$CrashDumpDirectory = ''
  )

  $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
  $startInfo.FileName = $FilePath
  $startInfo.UseShellExecute = $false
  $startInfo.CreateNoWindow = $true
  $startInfo.RedirectStandardOutput = $true
  $startInfo.RedirectStandardError = $true
  if ($CrashDumpDirectory) {
    New-Item -ItemType Directory -Path $CrashDumpDirectory -Force | Out-Null
    $startInfo.Environment['BREAKPAD_DUMP_LOCATION'] = $CrashDumpDirectory
  }
  foreach ($argument in $Arguments) {
    $startInfo.ArgumentList.Add($argument)
  }

  $process = [System.Diagnostics.Process]::new()
  $process.StartInfo = $startInfo
  try {
    Write-Host "Running: $FilePath $($Arguments -join ' ')"
    if (-not $process.Start()) {
      throw "Failed to start: $FilePath"
    }
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $crashDetected = $false
    $crashDumpReady = $false
    while (-not $process.WaitForExit(500)) {
      if ($CrashDumpDirectory -and
          @(Get-ChildItem -LiteralPath $CrashDumpDirectory -Filter '*.dmp' `
              -File -Recurse -ErrorAction SilentlyContinue).Count -ne 0) {
        $crashDetected = $true
        $crashDumpReady = Wait-ForCrashDumps -Directory $CrashDumpDirectory
        break
      }
      if ([DateTime]::UtcNow -ge $deadline) {
        break
      }
    }
    if (-not $crashDetected -and $CrashDumpDirectory -and
        @(Get-ChildItem -LiteralPath $CrashDumpDirectory -Filter '*.dmp' `
            -File -Recurse -ErrorAction SilentlyContinue).Count -ne 0) {
      $crashDetected = $true
      $crashDumpReady = Wait-ForCrashDumps -Directory $CrashDumpDirectory
    }
    $timedOut = -not $process.HasExited -and -not $crashDetected
    if (-not $process.HasExited) {
      $process.Kill($true)
      $process.WaitForExit()
    }
    $stdout = $stdoutTask.GetAwaiter().GetResult()
    $stderr = $stderrTask.GetAwaiter().GetResult()
    $rendererTerminationDetected =
        $stderr.Contains('Abnormal renderer termination.')
    $rendererExitCode = $null
    $probableRendererNtStatus = $null
    if ($stderr -match
        '(?ms)Histogram: CrashExitCodes\.Renderer.*?\r?\n[ \t]*(-?\d+)') {
      $rendererExitCode = [int64]$Matches[1]
      if ($rendererExitCode -gt 0 -and
          $rendererExitCode -le [int64][int32]::MaxValue) {
        $probableRendererNtStatus = '0x{0:X8}' -f
            ([uint32]([int64]4294967296 - $rendererExitCode))
      }
    }
    Write-Utf8File -Path $StandardOutputPath -Contents $stdout
    Write-Utf8File -Path $StandardErrorPath -Contents $stderr
    return [pscustomobject]@{
      ExitCode = $process.ExitCode
      TimedOut = $timedOut
      CrashDetected = $crashDetected
      CrashDumpReady = $crashDumpReady
      RendererTerminationDetected = $rendererTerminationDetected
      RendererExitCode = $rendererExitCode
      ProbableRendererNtStatus = $probableRendererNtStatus
    }
  } finally {
    $process.Dispose()
  }
}

function Invoke-HeadlessProbe {
  param(
    [Parameter(Mandatory = $true)]
    [string]$BrowserPath,
    [Parameter(Mandatory = $true)]
    [string]$ProfileDirectory,
    [Parameter(Mandatory = $true)]
    [string]$TestUrl,
    [Parameter(Mandatory = $true)]
    [string[]]$CommonArguments,
    [string[]]$AdditionalArguments = @(),
    [Parameter(Mandatory = $true)]
    [int]$TimeoutSeconds,
    [Parameter(Mandatory = $true)]
    [string]$StandardOutputPath,
    [Parameter(Mandatory = $true)]
    [string]$StandardErrorPath,
    [Parameter(Mandatory = $true)]
    [string]$CrashDumpDirectory
  )

  if (Test-Path -LiteralPath $ProfileDirectory) {
    Remove-Item -LiteralPath $ProfileDirectory -Recurse -Force
  }
  $arguments = @(
    $CommonArguments
    $AdditionalArguments
    "--user-data-dir=$ProfileDirectory"
    '--dump-dom'
    $TestUrl
  )
  $processResult = Invoke-CapturedProcess `
    -FilePath $BrowserPath `
    -Arguments $arguments `
    -TimeoutSeconds $TimeoutSeconds `
    -StandardOutputPath $StandardOutputPath `
    -StandardErrorPath $StandardErrorPath `
    -CrashDumpDirectory $CrashDumpDirectory
  $rendered = [System.IO.File]::ReadAllText(
    $StandardOutputPath
  ).Contains('THORIUM_WOA_SMOKE_OK')
  return [pscustomobject]@{
    Process = $processResult
    Rendered = $rendered
    Diagnostic = [ordered]@{
      Rendered = $rendered
      TimedOut = $processResult.TimedOut
      ExitCode = $processResult.ExitCode
      CrashDetected = $processResult.CrashDetected
      CrashDumpReady = $processResult.CrashDumpReady
      RendererTerminationDetected =
          $processResult.RendererTerminationDetected
      RendererExitCode = $processResult.RendererExitCode
      ProbableRendererNtStatus = $processResult.ProbableRendererNtStatus
    }
  }
}

function Remove-TemporaryPath {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [Parameter(Mandatory = $true)]
    [string]$Description
  )

  if (-not (Test-Path -LiteralPath $Path)) {
    return
  }
  try {
    Remove-Item -LiteralPath $Path -Recurse -Force
  } catch {
    $script:result.CleanupWarnings.Add(
      "Could not remove ${Description}: $($_.Exception.Message)"
    )
  }
}

try {
  Start-Transcript -Path $transcriptPath -Force | Out-Null
  $transcriptStarted = $true
  if ($env:PROCESSOR_ARCHITECTURE -ne 'ARM64') {
    throw "The smoke test must run natively on Windows ARM64; got $env:PROCESSOR_ARCHITECTURE."
  }
  Add-Check -Name 'Runner architecture' -Detail 'The runner reports ARM64.'

  $installers = @(
    Get-ChildItem -LiteralPath $artifactRoot -File -Recurse |
      Where-Object { $_.Name -like $InstallerPattern }
  )
  if ($installers.Count -ne 1) {
    throw "Expected exactly one installer matching '$InstallerPattern' under '$artifactRoot'; found $($installers.Count)."
  }
  $installer = $installers[0]
  $result.Installer = [System.IO.Path]::GetRelativePath(
    $artifactRoot,
    $installer.FullName
  ).Replace('\', '/')
  $null = Assert-Arm64Pe `
    -Files @($installer) `
    -CheckName 'Installer architecture'

  $installerHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $installer.FullName).Hash.ToLowerInvariant()
  $result.InstallerSha256 = $installerHash
  if ($ExpectedSha256) {
    $normalizedExpectedHash = $ExpectedSha256.Trim().ToLowerInvariant()
    if ($normalizedExpectedHash -notmatch '^[0-9a-f]{64}$') {
      throw 'ExpectedSha256 must contain exactly 64 hexadecimal characters.'
    }
    if ($installerHash -ne $normalizedExpectedHash) {
      throw "Installer SHA-256 mismatch: expected $normalizedExpectedHash, got $installerHash."
    }
    Add-Check -Name 'Installer digest' -Detail 'The installer SHA-256 matches the expected value.'
  } else {
    Add-Check -Name 'Installer digest' -Detail "SHA-256: $installerHash"
  }

  if (Test-Path -LiteralPath $installRoot) {
    throw "Refusing to overwrite a pre-existing Thorium installation: $installRoot"
  }

  $installProcess = Invoke-CapturedProcess `
    -FilePath $installer.FullName `
    -Arguments @('--silent', '--do-not-launch-chrome') `
    -TimeoutSeconds $InstallerTimeoutSeconds `
    -StandardOutputPath $installerStdout `
    -StandardErrorPath $installerStderr
  if ($installProcess.TimedOut) {
    throw "The mini installer timed out after $InstallerTimeoutSeconds seconds."
  }
  if ($installProcess.ExitCode -ne 0) {
    throw "The mini installer exited with code $($installProcess.ExitCode)."
  }
  if (-not (Test-Path -LiteralPath $browser -PathType Leaf)) {
    throw "The installer succeeded but did not create $browser."
  }
  Add-Check -Name 'Per-user installation' -Detail "The silent installer created $browser."

  $installedBinaries = @(
    Get-ChildItem -LiteralPath $installRoot -File -Recurse |
      Where-Object { $_.Extension -in @('.exe', '.dll') }
  )
  if ($installedBinaries.Count -eq 0) {
    throw "No installed EXE or DLL files were found under $installRoot."
  }
  $versionDirectories = @(
    Get-ChildItem -LiteralPath $installRoot -Directory |
      Where-Object { $_.Name -match '^\d+(\.\d+){3}$' }
  )
  if ($versionDirectories.Count -ne 1) {
    throw "Expected exactly one installed version directory; found $($versionDirectories.Count)."
  }
  $versionName = $versionDirectories[0].Name
  $allowedNonArm64Tools = @{
    "$versionName/pak_mingw32.exe" = 0x014C
    "$versionName/pak_mingw64.exe" = 0x8664
  }
  $acceptedTools = Assert-Arm64Pe `
    -Files $installedBinaries `
    -CheckName 'Installed payload architecture' `
    -RelativeRoot $installRoot `
    -AllowedNonArm64Tools $allowedNonArm64Tools
  foreach ($tool in $acceptedTools) {
    $result.InstalledNonArm64Tools.Add($tool)
  }
  $result.InstalledBinaryCount = $installedBinaries.Count

  $uninstallers = @(
    Get-ChildItem -LiteralPath $installRoot -Filter 'setup.exe' -File -Recurse |
      Where-Object { $_.Directory.Name -eq 'Installer' } |
      Sort-Object -Property LastWriteTimeUtc -Descending
  )
  if ($uninstallers.Count -eq 0) {
    throw "No installed setup.exe was found under $installRoot."
  }
  $uninstaller = $uninstallers[0].FullName

  $testPageContents = @'
<!doctype html>
<meta charset="utf-8">
<title>Thorium WOA smoke test</title>
<main id="result">THORIUM_WOA_SMOKE_PENDING</main>
<script>
  (() => {
    const typedValues = new Uint32Array([3, 5, 8, 13]);
    if (typedValues.reduce((sum, value) => sum + value, 0) !== 29) {
      throw new Error('TypedArray validation failed');
    }
    if (2n ** 64n !== 18446744073709551616n) {
      throw new Error('BigInt validation failed');
    }
    if (!/^Thorium\s+WOA$/u.test('Thorium WOA')) {
      throw new Error('RegExp validation failed');
    }
    const wasmBytes = new Uint8Array([
      0x00, 0x61, 0x73, 0x6d, 0x01, 0x00, 0x00, 0x00,
      0x01, 0x05, 0x01, 0x60, 0x00, 0x01, 0x7f,
      0x03, 0x02, 0x01, 0x00,
      0x07, 0x0a, 0x01, 0x06, 0x61, 0x6e, 0x73, 0x77, 0x65, 0x72,
      0x00, 0x00,
      0x0a, 0x06, 0x01, 0x04, 0x00, 0x41, 0x2a, 0x0b,
    ]);
    const wasmInstance = new WebAssembly.Instance(
      new WebAssembly.Module(wasmBytes)
    );
    if (wasmInstance.exports.answer() !== 42) {
      throw new Error('WebAssembly validation failed');
    }
    document.querySelector('#result').textContent =
      'THORIUM_WOA_SMOKE_OK TYPED_ARRAY BIGINT REGEXP WASM_42';
  })();
</script>
'@
  Write-Utf8File -Path $testPage -Contents $testPageContents
  $testUrl = ([System.Uri]$testPage).AbsoluteUri
  $browserProbeStartUtc = [DateTime]::UtcNow
  $commonHeadlessArguments = @(
    '--headless=new',
    '--no-first-run',
    '--no-default-browser-check',
    '--enable-logging=stderr'
  )
  $headlessProbe = Invoke-HeadlessProbe `
    -BrowserPath $browser `
    -ProfileDirectory $profile `
    -TestUrl $testUrl `
    -CommonArguments $commonHeadlessArguments `
    -TimeoutSeconds $BrowserTimeoutSeconds `
    -StandardOutputPath $browserStdout `
    -StandardErrorPath $browserStderr `
    -CrashDumpDirectory (Join-Path $crashRoot 'headless')
  $browserProcess = $headlessProbe.Process
  $browserRendered = $headlessProbe.Rendered
  $result.HeadlessDiagnostic = $headlessProbe.Diagnostic
  if (-not $browserRendered) {
    $noExtensionsProbe = Invoke-HeadlessProbe `
      -BrowserPath $browser `
      -ProfileDirectory $noExtensionsProfile `
      -TestUrl $testUrl `
      -CommonArguments $commonHeadlessArguments `
      -AdditionalArguments @('--disable-extensions') `
      -TimeoutSeconds $BrowserTimeoutSeconds `
      -StandardOutputPath $noExtensionsStdout `
      -StandardErrorPath $noExtensionsStderr `
      -CrashDumpDirectory (Join-Path $crashRoot 'no-extensions')
    $noExtensionsProcess = $noExtensionsProbe.Process
    $noExtensionsRendered = $noExtensionsProbe.Rendered
    $result.HeadlessNoExtensionsDiagnostic = $noExtensionsProbe.Diagnostic

    $noSandboxProbe = Invoke-HeadlessProbe `
      -BrowserPath $browser `
      -ProfileDirectory $noSandboxProfile `
      -TestUrl $testUrl `
      -CommonArguments $commonHeadlessArguments `
      -AdditionalArguments @('--no-sandbox') `
      -TimeoutSeconds $BrowserTimeoutSeconds `
      -StandardOutputPath $noSandboxStdout `
      -StandardErrorPath $noSandboxStderr `
      -CrashDumpDirectory (Join-Path $crashRoot 'no-sandbox')
    $noSandboxProcess = $noSandboxProbe.Process
    $noSandboxRendered = $noSandboxProbe.Rendered
    $result.HeadlessNoSandboxDiagnostic = $noSandboxProbe.Diagnostic

    if (-not $noSandboxRendered -and -not $noExtensionsRendered -and
        -not $browserProcess.CrashDetected -and
        -not $noSandboxProcess.CrashDetected -and
        -not $noExtensionsProcess.CrashDetected) {
      try {
        if (Test-Path -LiteralPath $werProfile) {
          Remove-Item -LiteralPath $werProfile -Recurse -Force
        }
        New-Item -ItemType Directory -Path $werDumpDirectory -Force |
          Out-Null
        Enable-WerLocalDumps
        $werProcess = Invoke-CapturedProcess `
          -FilePath $browser `
          -Arguments @(
            $commonHeadlessArguments
            '--disable-breakpad'
            "--user-data-dir=$werProfile"
            '--dump-dom'
            $testUrl
          ) `
          -TimeoutSeconds $BrowserTimeoutSeconds `
          -StandardOutputPath $werStdout `
          -StandardErrorPath $werStderr
        $werDumpReady = Wait-ForCrashDumps `
          -Directory $werDumpDirectory `
          -TimeoutSeconds 15
        $werDumps = @(
          Get-ChildItem -LiteralPath $werDumpDirectory -Filter '*.dmp' `
            -File -Recurse -ErrorAction SilentlyContinue
        )
        $result.HeadlessWerDiagnostic = [ordered]@{
          TimedOut = $werProcess.TimedOut
          ExitCode = $werProcess.ExitCode
          DumpCount = $werDumps.Count
          DumpReady = $werDumpReady
          RendererTerminationDetected =
              $werProcess.RendererTerminationDetected
          RendererExitCode = $werProcess.RendererExitCode
          ProbableRendererNtStatus = $werProcess.ProbableRendererNtStatus
        }
      } catch {
        $result.CleanupWarnings.Add(
          "WER renderer-dump diagnostic failed: $($_.Exception.Message)"
        )
      } finally {
        try {
          Disable-WerLocalDumps
        } catch {
          $result.CleanupWarnings.Add(
            "Could not remove the temporary WER configuration: $($_.Exception.Message)"
          )
        }
      }
    }
    if ($noSandboxRendered -and $noExtensionsRendered) {
      $headlessError = 'Thorium rendered only in both diagnostic configurations: --disable-extensions and --no-sandbox. The default artifact still fails, and the two causes must be isolated independently.'
    } elseif ($noSandboxRendered) {
      $headlessError = 'Sandboxed Thorium did not render the local page, while the diagnostic --no-sandbox run did. The artifact failed the release test because its sandboxed renderer path is not functional.'
    } elseif ($noExtensionsRendered) {
      $headlessError = 'Thorium did not render the local page through its normal extension-enabled startup path, while the diagnostic --disable-extensions run succeeded. The extension-enabled startup path is breaking the renderer.'
    } elseif ($browserProcess.CrashDetected) {
      $headlessError = 'Thorium generated a Crashpad dump before rendering the local page; the --disable-extensions and --no-sandbox diagnostics also failed. The artifact has a broader renderer or child-process crash.'
    } elseif ($browserProcess.RendererTerminationDetected) {
      $exitDetail = if ($null -ne $browserProcess.RendererExitCode) {
        $ntStatusDetail = if ($browserProcess.ProbableRendererNtStatus) {
          ", probable NTSTATUS=$($browserProcess.ProbableRendererNtStatus)"
        } else {
          ''
        }
        " (CrashExitCodes.Renderer=$($browserProcess.RendererExitCode)$ntStatusDetail)"
      } else {
        ''
      }
      $headlessError = "Thorium reported an abnormal renderer termination$exitDetail before rendering the local page; the --disable-extensions and --no-sandbox diagnostics also failed."
    } elseif ($browserProcess.TimedOut) {
      $headlessError = "Thorium headless timed out after $BrowserTimeoutSeconds seconds without rendering the local page; the diagnostic --disable-extensions and --no-sandbox runs also failed."
    } else {
      $headlessError = "Thorium headless exited with code $($browserProcess.ExitCode) without rendering the local page; the diagnostic --disable-extensions and --no-sandbox runs also failed."
    }
    $result.HeadlessError = $headlessError
  } else {
    if (-not $browserProcess.TimedOut -and $browserProcess.ExitCode -ne 0) {
      throw "Thorium headless rendered the page but exited with code $($browserProcess.ExitCode)."
    }
    if ($browserProcess.TimedOut) {
      $timeoutWarning = "Thorium rendered the local page, but --dump-dom did not exit within $BrowserTimeoutSeconds seconds and the process tree was terminated."
      $result.CleanupWarnings.Add($timeoutWarning)
      Write-Warning $timeoutWarning
      Add-Check -Name 'Native browser launch' -Detail 'Thorium rendered a local page in headless mode; the non-terminating process tree was stopped by the harness.'
    } else {
      Add-Check -Name 'Native browser launch' -Detail 'Thorium rendered a local page and exited successfully in headless mode.'
    }
  }

  $guiResults = Join-Path $resultRoot 'gui'
  $guiProfile = Join-Path $env:RUNNER_TEMP 'thorium-woa-gui-profile'
  try {
    & (Join-Path $PSScriptRoot 'gui_smoke_test.ps1') `
      -BrowserPath $browser `
      -ProfileDirectory $guiProfile `
      -ResultsDirectory $guiResults `
      -LocalTestUrl $testUrl
    $result.GuiSuccess = $true
    Add-Check -Name 'GUI navigation and capture' -Detail 'WebGL and OfflineAudioContext passed; Google and chrome://version opened in a native browser window and screenshots were captured.'
  } catch {
    $result.GuiError = $_.Exception.ToString()
    $guiReportPath = Join-Path $guiResults 'gui-report.json'
    if (Test-Path -LiteralPath $guiReportPath -PathType Leaf) {
      $guiReport = Get-Content -LiteralPath $guiReportPath -Raw |
        ConvertFrom-Json
      $rendererFailureProperty =
          $guiReport.PSObject.Properties['RendererFailureDetected']
      $capabilityFailureProperty =
          $guiReport.PSObject.Properties['CapabilityFailureDetected']
      $result.GuiProductFailure =
          ($rendererFailureProperty -and
           [bool]$rendererFailureProperty.Value) -or
          ($capabilityFailureProperty -and
           [bool]$capabilityFailureProperty.Value) -or
          [bool]$guiReport.CrashPageErrorCode -or
          @($guiReport.CrashArtifacts).Count -ne 0
    }
    if ($result.GuiProductFailure) {
      throw "A required normal-window GUI product check failed: $($_.Exception.Message)"
    }
    if ($RequireGui) {
      throw
    }
    $result.CleanupWarnings.Add("Optional GUI smoke test was unavailable: $($_.Exception.Message)")
    Write-Warning "Optional GUI smoke test was unavailable: $($_.Exception.Message)"
  }

  if ($headlessError) {
    throw $headlessError
  }

  $uninstallProcess = Invoke-CapturedProcess `
    -FilePath $uninstaller `
    -Arguments @('--uninstall', '--force-uninstall', '--verbose-logging') `
    -TimeoutSeconds $InstallerTimeoutSeconds `
    -StandardOutputPath $uninstallerStdout `
    -StandardErrorPath $uninstallerStderr
  if ($uninstallProcess.TimedOut) {
    throw "The uninstaller timed out after $InstallerTimeoutSeconds seconds."
  }
  if ($uninstallProcess.ExitCode -ne 19) {
    throw "The uninstaller exited with code $($uninstallProcess.ExitCode) instead of UNINSTALL_SUCCESSFUL (19)."
  }
  $uninstallCompleted = $true
  $removalDeadline = [DateTime]::UtcNow.AddSeconds(30)
  while ((Test-Path -LiteralPath $browser -PathType Leaf) -and
         [DateTime]::UtcNow -lt $removalDeadline) {
    Start-Sleep -Milliseconds 500
  }
  if (Test-Path -LiteralPath $browser -PathType Leaf) {
    throw "The uninstaller left the browser executable behind: $browser"
  }
  Add-Check -Name 'Uninstall' -Detail 'The installed setup removed the browser executable.'

  $result.Success = $true
} catch {
  $failed = $_
  $result.Error = $_.Exception.ToString()
} finally {
  try {
    Record-CrashArtifacts
  } catch {
    $result.CleanupWarnings.Add(
      "Could not enumerate preserved headless crash dumps: $($_.Exception.Message)"
    )
  }
  if ($browserProbeStartUtc) {
    try {
      $result.WindowsCrashEvents = @(
        Get-WindowsCrashEvents -StartTime $browserProbeStartUtc
      )
    } catch {
      $result.CleanupWarnings.Add(
        "Could not read Windows crash events: $($_.Exception.Message)"
      )
    }
  }
  if (-not $uninstallCompleted -and $uninstaller -and
      (Test-Path -LiteralPath $uninstaller -PathType Leaf)) {
    try {
      $cleanupProcess = Invoke-CapturedProcess `
        -FilePath $uninstaller `
        -Arguments @('--uninstall', '--force-uninstall', '--verbose-logging') `
        -TimeoutSeconds $InstallerTimeoutSeconds `
        -StandardOutputPath $cleanupUninstallerStdout `
        -StandardErrorPath $cleanupUninstallerStderr
      if ($cleanupProcess.TimedOut) {
        $result.CleanupWarnings.Add("Best-effort uninstall timed out after $InstallerTimeoutSeconds seconds.")
      } elseif ($cleanupProcess.ExitCode -ne 19) {
        $result.CleanupWarnings.Add("Best-effort uninstall exited with code $($cleanupProcess.ExitCode) instead of 19.")
      }
    } catch {
      $result.CleanupWarnings.Add("Best-effort uninstall failed: $($_.Exception.Message)")
    }
  }
  Remove-TemporaryPath `
    -Path $testPage `
    -Description 'the temporary test page'
  Remove-TemporaryPath `
    -Path $profile `
    -Description 'the temporary profile'
  Remove-TemporaryPath `
    -Path $noExtensionsProfile `
    -Description 'the no-extensions diagnostic profile'
  Remove-TemporaryPath `
    -Path $noSandboxProfile `
    -Description 'the no-sandbox diagnostic profile'
  Remove-TemporaryPath `
    -Path $werProfile `
    -Description 'the WER diagnostic profile'
  if ($werConfigurationCreated -or $werRegistryRootCreated) {
    try {
      Disable-WerLocalDumps
    } catch {
      $result.CleanupWarnings.Add(
        "Could not remove the temporary WER configuration during cleanup: $($_.Exception.Message)"
      )
    }
  }
  if ($transcriptStarted) {
    try {
      Stop-Transcript | Out-Null
    } catch {
      $result.CleanupWarnings.Add(
        "Could not stop the transcript cleanly: $($_.Exception.Message)"
      )
      Write-Warning "Could not stop the transcript cleanly: $($_.Exception.Message)"
    }
    $transcriptStarted = $false
  }
  try {
    Write-Utf8File `
      -Path $resultPath `
      -Contents ($result | ConvertTo-Json -Depth 6)
  } catch {
    if (-not $failed) {
      $failed = $_
    } else {
      Write-Warning "Could not write the smoke-test report: $($_.Exception.Message)"
    }
  }
}

if ($failed) {
  throw $failed
}
