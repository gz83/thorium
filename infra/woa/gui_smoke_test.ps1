# Copyright (c) 2026 Alex313031 and gz83
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$BrowserPath,

  [Parameter(Mandatory = $true)]
  [string]$ProfileDirectory,

  [Parameter(Mandatory = $true)]
  [string]$ResultsDirectory,

  [Parameter(Mandatory = $true)]
  [string]$LocalTestUrl,

  [ValidateRange(15, 300)]
  [int]$LaunchTimeoutSeconds = 60,

  [ValidateRange(15, 300)]
  [int]$NavigationTimeoutSeconds = 60
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$browser = (Resolve-Path -LiteralPath $BrowserPath).Path
New-Item -ItemType Directory -Path $ResultsDirectory -Force | Out-Null
$resultRoot = (Resolve-Path -LiteralPath $ResultsDirectory).Path
$resultPath = Join-Path $resultRoot 'gui-report.json'
$stdoutPath = Join-Path $resultRoot 'gui-browser.stdout.txt'
$stderrPath = Join-Path $resultRoot 'gui-browser.stderr.txt'
$crashRoot = Join-Path $resultRoot 'crash-dumps'

$result = [ordered]@{
  SchemaVersion = 6
  UserInteractive = [Environment]::UserInteractive
  SessionId = [System.Diagnostics.Process]::GetCurrentProcess().SessionId
  WindowHandle = $null
  WindowClass = $null
  WindowTitle = $null
  WindowBounds = $null
  DevToolsPort = $null
  Startup = $null
  CrashPageErrorCode = $null
  RendererFailureDetected = $false
  CapabilityFailureDetected = $false
  FailureScreenshot = $null
  CrashArtifacts = [System.Collections.Generic.List[string]]::new()
  ObservedTargets = @()
  Local = $null
  Google = $null
  Version = $null
  Capabilities = $null
  Warnings = [System.Collections.Generic.List[string]]::new()
  Success = $false
  Error = $null
}
$failed = $null
$browserProcess = $null
$stdoutTask = $null
$stderrTask = $null
$window = [IntPtr]::Zero
$accessibilityInspectionAvailable = $true

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
if (-not ('Thorium.Woa.NativeWindow' -as [type])) {
  Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;

namespace Thorium.Woa {
  public static class NativeWindow {
    public delegate bool EnumWindowsCallback(IntPtr hwnd, IntPtr parameter);

    [StructLayout(LayoutKind.Sequential)]
    public struct Rect {
      public int Left;
      public int Top;
      public int Right;
      public int Bottom;
    }

    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumWindowsCallback callback,
                                           IntPtr parameter);

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr hwnd,
                                                        out uint processId);

    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hwnd);

    [DllImport("user32.dll")]
    public static extern bool IsHungAppWindow(IntPtr hwnd);

    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hwnd, out Rect rect);

    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hwnd, int command);

    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hwnd);

    [DllImport("user32.dll")]
    public static extern bool PrintWindow(IntPtr hwnd, IntPtr targetDc,
                                          uint flags);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetWindowText(IntPtr hwnd, StringBuilder text,
                                            int maximumCount);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetClassName(IntPtr hwnd, StringBuilder text,
                                           int maximumCount);

    public static IntPtr FindLargestVisibleWindow(uint processId) {
      IntPtr selected = IntPtr.Zero;
      long selectedArea = 0;
      EnumWindows((hwnd, parameter) => {
        uint owner;
        GetWindowThreadProcessId(hwnd, out owner);
        Rect rect;
        if (owner != processId || !IsWindowVisible(hwnd) ||
            !GetWindowRect(hwnd, out rect)) {
          return true;
        }
        long width = Math.Max(0, rect.Right - rect.Left);
        long height = Math.Max(0, rect.Bottom - rect.Top);
        long area = width * height;
        if (area > selectedArea) {
          selected = hwnd;
          selectedArea = area;
        }
        return true;
      }, IntPtr.Zero);
      return selected;
    }

    public static string GetTitle(IntPtr hwnd) {
      StringBuilder text = new StringBuilder(1024);
      GetWindowText(hwnd, text, text.Capacity);
      return text.ToString();
    }

    public static string GetClass(IntPtr hwnd) {
      StringBuilder text = new StringBuilder(256);
      GetClassName(hwnd, text, text.Capacity);
      return text.ToString();
    }
  }
}
'@
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

function Wait-Until {
  param(
    [Parameter(Mandatory = $true)]
    [scriptblock]$Condition,
    [Parameter(Mandatory = $true)]
    [int]$TimeoutSeconds,
    [Parameter(Mandatory = $true)]
    [string]$FailureMessage
  )

  $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
  do {
    $value = & $Condition
    if ($null -ne $value -and $false -ne $value) {
      return $value
    }
    Start-Sleep -Milliseconds 500
  } while ([DateTime]::UtcNow -lt $deadline)
  throw $FailureMessage
}

function Get-DevToolsTargets {
  param(
    [Parameter(Mandatory = $true)]
    [int]$Port
  )

  try {
    return @(
      Invoke-RestMethod `
        -Uri "http://127.0.0.1:$Port/json/list" `
        -TimeoutSec 5 `
        -ErrorAction Stop
    )
  } catch {
    return @()
  }
}

function Activate-Target {
  param(
    [Parameter(Mandatory = $true)]
    [int]$Port,
    [Parameter(Mandatory = $true)]
    [string]$TargetId
  )

  Invoke-RestMethod `
    -Uri "http://127.0.0.1:$Port/json/activate/$TargetId" `
    -TimeoutSec 5 `
    -ErrorAction Stop | Out-Null
}

function Invoke-DevToolsCommand {
  param(
    [Parameter(Mandatory = $true)]
    [string]$WebSocketUrl,
    [Parameter(Mandatory = $true)]
    [string]$Method,
    [hashtable]$Parameters = @{},
    [ValidateRange(1, 60)]
    [int]$TimeoutSeconds = 15
  )

  $socket = [System.Net.WebSockets.ClientWebSocket]::new()
  $cancellationSource = [System.Threading.CancellationTokenSource]::new()
  $cancellationSource.CancelAfter(
    [TimeSpan]::FromSeconds($TimeoutSeconds)
  )
  $cancellationToken = $cancellationSource.Token
  try {
    $null = $socket.ConnectAsync(
      [Uri]$WebSocketUrl,
      $cancellationToken
    ).GetAwaiter().GetResult()
    $request = [ordered]@{
      id = 1
      method = $Method
      params = $Parameters
    } | ConvertTo-Json -Compress -Depth 8
    $requestBytes = [System.Text.Encoding]::UTF8.GetBytes($request)
    $null = $socket.SendAsync(
      [ArraySegment[byte]]::new($requestBytes),
      [System.Net.WebSockets.WebSocketMessageType]::Text,
      $true,
      $cancellationToken
    ).GetAwaiter().GetResult()

    $buffer = [byte[]]::new(65536)
    while ($true) {
      $messageStream = [System.IO.MemoryStream]::new()
      try {
        do {
          $receiveResult = $socket.ReceiveAsync(
            [ArraySegment[byte]]::new($buffer),
            $cancellationToken
          ).GetAwaiter().GetResult()
          if ($receiveResult.MessageType -eq
              [System.Net.WebSockets.WebSocketMessageType]::Close) {
            throw "DevTools closed the connection before replying to $Method."
          }
          $messageStream.Write($buffer, 0, $receiveResult.Count)
        } while (-not $receiveResult.EndOfMessage)
        $message = [System.Text.Encoding]::UTF8.GetString(
          $messageStream.ToArray()
        ) | ConvertFrom-Json
      } finally {
        $messageStream.Dispose()
      }
      $idProperty = $message.PSObject.Properties['id']
      if (-not $idProperty -or $idProperty.Value -ne 1) {
        continue
      }
      $errorProperty = $message.PSObject.Properties['error']
      if ($errorProperty) {
        $errorMessageProperty =
            $errorProperty.Value.PSObject.Properties['message']
        $errorMessage = if ($errorMessageProperty) {
          $errorMessageProperty.Value
        } else {
          $errorProperty.Value | ConvertTo-Json -Compress -Depth 8
        }
        throw "DevTools $Method failed: $errorMessage"
      }
      $resultProperty = $message.PSObject.Properties['result']
      if (-not $resultProperty) {
        throw "DevTools $Method returned no result."
      }
      return $resultProperty.Value
    }
  } catch [System.OperationCanceledException] {
    throw "DevTools $Method timed out after $TimeoutSeconds seconds."
  } finally {
    if ($socket.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
      try {
        $null = $socket.CloseAsync(
          [System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure,
          'Thorium WOA smoke-test command completed.',
          [System.Threading.CancellationToken]::None
        ).GetAwaiter().GetResult()
      } catch {
        # The renderer may close its endpoint while reporting a crash.
      }
    }
    $socket.Dispose()
    $cancellationSource.Dispose()
  }
}

function Get-TargetDocumentState {
  param(
    [Parameter(Mandatory = $true)]
    [object]$Target,
    [Parameter(Mandatory = $true)]
    [string]$Context
  )

  $socketProperty =
      $Target.PSObject.Properties['webSocketDebuggerUrl']
  if (-not $socketProperty -or -not $socketProperty.Value) {
    throw "The ${Context} target did not expose a DevTools WebSocket."
  }
  $expression = @'
JSON.stringify({
  readyState: document.readyState,
  url: location.href,
  title: document.title,
  bodyText: document.body ? document.body.innerText : ''
})
'@
  $evaluation = Invoke-DevToolsCommand `
    -WebSocketUrl $socketProperty.Value `
    -Method 'Runtime.evaluate' `
    -Parameters @{
      expression = $expression
      returnByValue = $true
    }
  if ($evaluation.PSObject.Properties['exceptionDetails']) {
    throw "The ${Context} document evaluation raised an exception."
  }
  $remoteObjectProperty = $evaluation.PSObject.Properties['result']
  if (-not $remoteObjectProperty) {
    throw "The ${Context} renderer returned no document state."
  }
  $remoteObject = $remoteObjectProperty.Value
  $typeProperty = $remoteObject.PSObject.Properties['type']
  $valueProperty = $remoteObject.PSObject.Properties['value']
  if (-not $typeProperty -or $typeProperty.Value -ne 'string' -or
      -not $valueProperty) {
    throw "The ${Context} renderer returned no document state."
  }
  return $valueProperty.Value | ConvertFrom-Json
}

function Invoke-RendererCapabilityChecks {
  param(
    [Parameter(Mandatory = $true)]
    [object]$Target
  )

  $socketProperty = $Target.PSObject.Properties['webSocketDebuggerUrl']
  if (-not $socketProperty -or -not $socketProperty.Value) {
    throw 'The local target did not expose a DevTools WebSocket for capability checks.'
  }
  $expression = @'
(async () => {
  const canvas = document.createElement('canvas');
  canvas.width = 2;
  canvas.height = 2;
  const gl = canvas.getContext('webgl');
  if (!gl) {
    throw new Error('WebGL context creation failed');
  }
  const compileShader = (type, source) => {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      throw new Error(`WebGL shader compilation failed: ${gl.getShaderInfoLog(shader)}`);
    }
    return shader;
  };
  const program = gl.createProgram();
  gl.attachShader(program, compileShader(
    gl.VERTEX_SHADER,
    'attribute vec2 position; void main() { gl_Position = vec4(position, 0.0, 1.0); }'
  ));
  gl.attachShader(program, compileShader(
    gl.FRAGMENT_SHADER,
    'precision mediump float; void main() { gl_FragColor = vec4(0.25, 0.5, 0.75, 1.0); }'
  ));
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    throw new Error(`WebGL program link failed: ${gl.getProgramInfoLog(program)}`);
  }
  gl.useProgram(program);
  const position = gl.getAttribLocation(program, 'position');
  const vertices = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, vertices);
  gl.bufferData(
    gl.ARRAY_BUFFER,
    new Float32Array([-1, -1, 3, -1, -1, 3]),
    gl.STATIC_DRAW
  );
  gl.enableVertexAttribArray(position);
  gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
  gl.viewport(0, 0, 2, 2);
  gl.drawArrays(gl.TRIANGLES, 0, 3);
  const pixel = new Uint8Array(4);
  gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);
  const expectedPixel = [64, 128, 191, 255];
  if (pixel.some((value, index) => Math.abs(value - expectedPixel[index]) > 2)) {
    throw new Error(`WebGL readback mismatch: ${Array.from(pixel).join(',')}`);
  }
  const rendererExtension = gl.getExtension('WEBGL_debug_renderer_info');
  const renderer = rendererExtension ?
    gl.getParameter(rendererExtension.UNMASKED_RENDERER_WEBGL) :
    gl.getParameter(gl.RENDERER);

  const frameCount = 4096;
  const audioContext = new OfflineAudioContext(1, frameCount, 48000);
  const oscillator = audioContext.createOscillator();
  const gain = audioContext.createGain();
  oscillator.frequency.value = 440;
  gain.gain.value = 0.25;
  oscillator.connect(gain).connect(audioContext.destination);
  oscillator.start(0);
  oscillator.stop(frameCount / audioContext.sampleRate);
  const renderedAudio = await audioContext.startRendering();
  const samples = renderedAudio.getChannelData(0);
  let peak = 0;
  let energy = 0;
  for (const sample of samples) {
    const magnitude = Math.abs(sample);
    peak = Math.max(peak, magnitude);
    energy += sample * sample;
  }
  const rms = Math.sqrt(energy / samples.length);
  if (!Number.isFinite(peak) || !Number.isFinite(rms) ||
      peak < 0.20 || rms < 0.10) {
    throw new Error(`OfflineAudioContext output was invalid: peak=${peak}, rms=${rms}`);
  }

  return {
    webgl: {
      version: gl.getParameter(gl.VERSION),
      renderer,
      pixel: Array.from(pixel),
    },
    offlineAudio: {
      channels: renderedAudio.numberOfChannels,
      frames: renderedAudio.length,
      sampleRate: renderedAudio.sampleRate,
      peak,
      rms,
    },
  };
})()
'@
  $evaluation = Invoke-DevToolsCommand `
    -WebSocketUrl $socketProperty.Value `
    -Method 'Runtime.evaluate' `
    -Parameters @{
      expression = $expression
      awaitPromise = $true
      returnByValue = $true
    } `
    -TimeoutSeconds 30
  if ($evaluation.PSObject.Properties['exceptionDetails']) {
    $details = $evaluation.exceptionDetails |
      ConvertTo-Json -Compress -Depth 8
    throw "Renderer capability checks failed: $details"
  }
  $remoteObjectProperty = $evaluation.PSObject.Properties['result']
  if (-not $remoteObjectProperty) {
    throw 'Renderer capability checks returned no result.'
  }
  $valueProperty = $remoteObjectProperty.Value.PSObject.Properties['value']
  if (-not $valueProperty) {
    throw 'Renderer capability checks returned no value.'
  }
  return $valueProperty.Value
}

function Assert-DocumentState {
  param(
    [Parameter(Mandatory = $true)]
    [object]$State,
    [Parameter(Mandatory = $true)]
    [string]$Context,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedUrlPattern,
    [string]$ExpectedText = ''
  )

  if ($State.bodyText -match '\b(STATUS_[A-Z0-9_]+)\b') {
    $result.CrashPageErrorCode = $Matches[1]
    $result.RendererFailureDetected = $true
    throw "The ${Context} renderer displayed crash page $($Matches[1])."
  }
  if ($State.url -notmatch $ExpectedUrlPattern) {
    throw "The ${Context} renderer reported unexpected URL '$($State.url)'."
  }
  if ($State.readyState -ne 'complete') {
    throw "The ${Context} document remained in readyState '$($State.readyState)'."
  }
  if ($ExpectedText -and -not $State.bodyText.Contains($ExpectedText)) {
    throw "The ${Context} document did not contain its expected marker."
  }
  if (-not $ExpectedText -and [string]::IsNullOrWhiteSpace($State.bodyText)) {
    throw "The ${Context} document body was empty."
  }
}

function Get-DocumentSummary {
  param(
    [Parameter(Mandatory = $true)]
    [object]$State
  )

  return [ordered]@{
    ReadyState = $State.readyState
    Url = $State.url
    Title = $State.title
    BodyTextLength = ([string]$State.bodyText).Length
  }
}

function Get-CrashPageErrorCode {
  param(
    [Parameter(Mandatory = $true)]
    [IntPtr]$Window
  )

  if (-not $script:accessibilityInspectionAvailable) {
    return $null
  }
  try {
    $root = [System.Windows.Automation.AutomationElement]::FromHandle($Window)
    if (-not $root) {
      return $null
    }
    $elements = $root.FindAll(
      [System.Windows.Automation.TreeScope]::Descendants,
      [System.Windows.Automation.Condition]::TrueCondition
    )
    foreach ($element in $elements) {
      $name = $element.Current.Name
      if ($name -match '\b(STATUS_[A-Z0-9_]+)\b') {
        return $Matches[1]
      }
    }
  } catch {
    $script:accessibilityInspectionAvailable = $false
    $result.Warnings.Add(
      "Could not inspect the browser accessibility tree: $($_.Exception.Message)"
    )
  }
  return $null
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

function Test-CrashDumpExists {
  if (-not (Test-Path -LiteralPath $crashRoot -PathType Container)) {
    return $false
  }
  return @(
    Get-ChildItem -LiteralPath $crashRoot -Filter '*.dmp' `
      -File -Recurse -ErrorAction SilentlyContinue
  ).Count -ne 0
}

function Assert-RendererHealthy {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Context,
    [Parameter(Mandatory = $true)]
    [IntPtr]$Window
  )

  if ($browserProcess.HasExited) {
    $result.RendererFailureDetected = $true
    throw "The GUI browser exited while validating ${Context} with code $($browserProcess.ExitCode)."
  }
  if ([Thorium.Woa.NativeWindow]::IsHungAppWindow($Window)) {
    $result.RendererFailureDetected = $true
    throw "The Thorium browser window stopped responding while validating ${Context}."
  }
  $crashCode = Get-CrashPageErrorCode -Window $Window
  if ($crashCode) {
    $result.CrashPageErrorCode = $crashCode
    $result.RendererFailureDetected = $true
    throw "The ${Context} renderer crashed with $crashCode."
  }
  if (Test-CrashDumpExists) {
    $result.RendererFailureDetected = $true
    throw "The ${Context} renderer generated a Crashpad dump."
  }
}

function Test-BitmapContent {
  param(
    [Parameter(Mandatory = $true)]
    [System.Drawing.Bitmap]$Bitmap
  )

  $colors = [System.Collections.Generic.HashSet[int]]::new()
  $stepX = [Math]::Max(1, [int]($Bitmap.Width / 32))
  $stepY = [Math]::Max(1, [int]($Bitmap.Height / 24))
  for ($x = 0; $x -lt $Bitmap.Width; $x += $stepX) {
    for ($y = 0; $y -lt $Bitmap.Height; $y += $stepY) {
      $null = $colors.Add($Bitmap.GetPixel($x, $y).ToArgb())
      if ($colors.Count -ge 8) {
        return $true
      }
    }
  }
  return $false
}

function Save-WindowCapture {
  param(
    [Parameter(Mandatory = $true)]
    [IntPtr]$Window,
    [Parameter(Mandatory = $true)]
    [string]$Name
  )

  $rect = [Thorium.Woa.NativeWindow+Rect]::new()
  if (-not [Thorium.Woa.NativeWindow]::GetWindowRect($Window, [ref]$rect)) {
    throw 'GetWindowRect failed for the Thorium browser window.'
  }
  $width = $rect.Right - $rect.Left
  $height = $rect.Bottom - $rect.Top
  if ($width -lt 640 -or $height -lt 480) {
    throw "The Thorium window is unexpectedly small: ${width}x${height}."
  }

  $printPath = Join-Path $resultRoot "$Name-window.png"
  $fallbackPath = Join-Path $resultRoot "$Name-desktop-fallback.png"
  $printSucceeded = $false
  $printHasContent = $false
  $fallbackSucceeded = $false
  $fallbackHasContent = $false

  $bitmap = [System.Drawing.Bitmap]::new(
    $width,
    $height,
    [System.Drawing.Imaging.PixelFormat]::Format32bppArgb
  )
  try {
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
      $deviceContext = $graphics.GetHdc()
      try {
        $printSucceeded = [Thorium.Woa.NativeWindow]::PrintWindow(
          $Window,
          $deviceContext,
          2
        )
      } finally {
        $graphics.ReleaseHdc($deviceContext)
      }
    } finally {
      $graphics.Dispose()
    }
    $bitmap.Save($printPath, [System.Drawing.Imaging.ImageFormat]::Png)
    $printHasContent = Test-BitmapContent -Bitmap $bitmap
  } finally {
    $bitmap.Dispose()
  }

  if (-not $printSucceeded -or -not $printHasContent) {
    try {
      $fallback = [System.Drawing.Bitmap]::new(
        $width,
        $height,
        [System.Drawing.Imaging.PixelFormat]::Format32bppArgb
      )
      try {
        $graphics = [System.Drawing.Graphics]::FromImage($fallback)
        try {
          $graphics.CopyFromScreen(
            $rect.Left,
            $rect.Top,
            0,
            0,
            [System.Drawing.Size]::new($width, $height),
            [System.Drawing.CopyPixelOperation]::SourceCopy
          )
        } finally {
          $graphics.Dispose()
        }
        $fallback.Save(
          $fallbackPath,
          [System.Drawing.Imaging.ImageFormat]::Png
        )
        $fallbackSucceeded = $true
        $fallbackHasContent = Test-BitmapContent -Bitmap $fallback
      } finally {
        $fallback.Dispose()
      }
    } catch {
      $result.Warnings.Add("Desktop screenshot fallback failed: $($_.Exception.Message)")
    }
  }

  if (-not $printHasContent -and -not $fallbackHasContent) {
    throw 'The runner created a browser window but could not capture a nonblank GUI image.'
  }

  return [ordered]@{
    Width = $width
    Height = $height
    PrintWindowPath = Split-Path -Leaf $printPath
    PrintWindowSucceeded = $printSucceeded
    PrintWindowHasContent = $printHasContent
    DesktopFallbackPath = if ($fallbackSucceeded) {
      Split-Path -Leaf $fallbackPath
    } else {
      $null
    }
    DesktopFallbackSucceeded = $fallbackSucceeded
    DesktopFallbackHasContent = $fallbackHasContent
  }
}

try {
  if (Test-Path -LiteralPath $ProfileDirectory) {
    Remove-Item -LiteralPath $ProfileDirectory -Recurse -Force
  }
  New-Item -ItemType Directory -Path $ProfileDirectory -Force | Out-Null

  $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
  $startInfo.FileName = $browser
  $startInfo.UseShellExecute = $false
  $startInfo.RedirectStandardOutput = $true
  $startInfo.RedirectStandardError = $true
  New-Item -ItemType Directory -Path $crashRoot -Force | Out-Null
  $startInfo.Environment['BREAKPAD_DUMP_LOCATION'] = $crashRoot
  $startInfo.ArgumentList.Add("--user-data-dir=$ProfileDirectory")
  $startInfo.ArgumentList.Add('--no-first-run')
  $startInfo.ArgumentList.Add('--no-default-browser-check')
  $startInfo.ArgumentList.Add('--enable-logging=stderr')
  $startInfo.ArgumentList.Add('--remote-debugging-port=0')
  $startInfo.ArgumentList.Add($LocalTestUrl)

  $browserProcess = [System.Diagnostics.Process]::new()
  $browserProcess.StartInfo = $startInfo
  if (-not $browserProcess.Start()) {
    throw "Failed to start the GUI browser: $browser"
  }
  $stdoutTask = $browserProcess.StandardOutput.ReadToEndAsync()
  $stderrTask = $browserProcess.StandardError.ReadToEndAsync()

  $devToolsFile = Join-Path $ProfileDirectory 'DevToolsActivePort'
  $port = Wait-Until `
    -TimeoutSeconds $LaunchTimeoutSeconds `
    -FailureMessage 'Thorium did not publish a DevToolsActivePort for the GUI session.' `
    -Condition {
      if ($browserProcess.HasExited) {
        $result.RendererFailureDetected = $true
        throw "The GUI browser exited early with code $($browserProcess.ExitCode)."
      }
      if (-not (Test-Path -LiteralPath $devToolsFile -PathType Leaf)) {
        return $null
      }
      $line = Get-Content -LiteralPath $devToolsFile -TotalCount 1
      $parsedPort = 0
      if ([int]::TryParse($line, [ref]$parsedPort)) {
        return $parsedPort
      }
      return $null
    }
  $result.DevToolsPort = $port

  $window = Wait-Until `
    -TimeoutSeconds $LaunchTimeoutSeconds `
    -FailureMessage 'Thorium did not create a visible top-level browser window.' `
    -Condition {
      if ($browserProcess.HasExited) {
        $result.RendererFailureDetected = $true
        throw "The GUI browser exited early with code $($browserProcess.ExitCode)."
      }
      $candidate = [Thorium.Woa.NativeWindow]::FindLargestVisibleWindow(
        [uint32]$browserProcess.Id
      )
      if ($candidate -eq [IntPtr]::Zero) { return $null }
      return $candidate
    }
  $result.WindowHandle = ('0x{0:X}' -f $window.ToInt64())
  $result.WindowClass = [Thorium.Woa.NativeWindow]::GetClass($window)
  $result.WindowTitle = [Thorium.Woa.NativeWindow]::GetTitle($window)
  if ([Thorium.Woa.NativeWindow]::IsHungAppWindow($window)) {
    $result.RendererFailureDetected = $true
    throw 'The Thorium browser window is not responding.'
  }

  $rect = [Thorium.Woa.NativeWindow+Rect]::new()
  if (-not [Thorium.Woa.NativeWindow]::GetWindowRect($window, [ref]$rect)) {
    throw 'Could not read the Thorium browser window bounds.'
  }
  $result.WindowBounds = [ordered]@{
    Left = $rect.Left
    Top = $rect.Top
    Width = $rect.Right - $rect.Left
    Height = $rect.Bottom - $rect.Top
  }
  $null = [Thorium.Woa.NativeWindow]::ShowWindow($window, 9)
  $null = [Thorium.Woa.NativeWindow]::SetForegroundWindow($window)
  Start-Sleep -Seconds 2
  try {
    $result.Startup = [ordered]@{
      Screenshot = Save-WindowCapture -Window $window -Name 'startup'
    }
  } catch {
    $result.Warnings.Add("Startup-window capture failed: $($_.Exception.Message)")
  }

  $crashCode = Get-CrashPageErrorCode -Window $window
  if ($crashCode) {
    $result.CrashPageErrorCode = $crashCode
    $result.RendererFailureDetected = $true
    if ($result.Startup) {
      $result.FailureScreenshot = $result.Startup.Screenshot
    }
    throw "The local page renderer crashed with $crashCode."
  }
  if (Test-CrashDumpExists) {
    $result.RendererFailureDetected = $true
    throw 'The local page renderer generated a Crashpad dump before loading completed.'
  }

  $localTarget = Wait-Until `
    -TimeoutSeconds $NavigationTimeoutSeconds `
    -FailureMessage 'The local test page did not finish loading in the GUI browser.' `
    -Condition {
      $targets = Get-DevToolsTargets -Port $port
      $result.ObservedTargets = @(
        $targets | ForEach-Object {
          [ordered]@{
            Id = $_.id
            Type = $_.type
            Url = $_.url
            Title = $_.title
          }
        }
      )
      $crashCode = Get-CrashPageErrorCode -Window $window
      if ($crashCode) {
        $result.CrashPageErrorCode = $crashCode
        $result.RendererFailureDetected = $true
        throw "The local page renderer crashed with $crashCode."
      }
      if (Test-CrashDumpExists) {
        $result.RendererFailureDetected = $true
        throw 'The local page renderer generated a Crashpad dump before loading completed.'
      }
      return $targets | Where-Object {
        $_.type -eq 'page' -and
        $_.url -eq $LocalTestUrl -and
        $_.title -eq 'Thorium WOA smoke test'
      } | Select-Object -First 1
    }
  Activate-Target -Port $port -TargetId $localTarget.id
  $null = [Thorium.Woa.NativeWindow]::ShowWindow($window, 9)
  $null = [Thorium.Woa.NativeWindow]::SetForegroundWindow($window)
  Start-Sleep -Seconds 2
  $result.Local = [ordered]@{
    Url = $localTarget.url
    Title = $localTarget.title
    Document = $null
    Screenshot = $null
  }
  Assert-RendererHealthy -Context 'local page' -Window $window
  $localState = Get-TargetDocumentState `
    -Target $localTarget `
    -Context 'local page'
  Assert-DocumentState `
    -State $localState `
    -Context 'local page' `
    -ExpectedUrlPattern ('^' + [regex]::Escape($LocalTestUrl) + '$') `
    -ExpectedText 'THORIUM_WOA_SMOKE_OK'
  try {
    $result.Capabilities =
        Invoke-RendererCapabilityChecks -Target $localTarget
  } catch {
    $result.CapabilityFailureDetected = $true
    throw
  }
  $result.Local.Document = Get-DocumentSummary -State $localState
  $result.Local.Screenshot = Save-WindowCapture -Window $window -Name 'local'
  Assert-RendererHealthy -Context 'local page' -Window $window
  Write-Host 'PASS: The local test page, WebGL, and OfflineAudioContext passed in the GUI browser.'

  $encodedVersionUrl = [Uri]::EscapeDataString('chrome://version/')
  $versionTarget = Invoke-RestMethod `
    -Method Put `
    -Uri "http://127.0.0.1:$port/json/new?$encodedVersionUrl" `
    -TimeoutSec 10 `
    -ErrorAction Stop
  $versionTargetId = $versionTarget.id
  $versionTarget = Wait-Until `
    -TimeoutSeconds $NavigationTimeoutSeconds `
    -FailureMessage 'chrome://version did not finish loading in the GUI browser.' `
    -Condition {
      $targets = Get-DevToolsTargets -Port $port
      $result.ObservedTargets = @(
        $targets | ForEach-Object {
          [ordered]@{
            Id = $_.id
            Type = $_.type
            Url = $_.url
            Title = $_.title
          }
        }
      )
      return $targets | Where-Object {
        $_.id -eq $versionTargetId -and
        $_.url -eq 'chrome://version/' -and
        [bool]$_.title
      } | Select-Object -First 1
    }
  Activate-Target -Port $port -TargetId $versionTarget.id
  $null = [Thorium.Woa.NativeWindow]::ShowWindow($window, 9)
  $null = [Thorium.Woa.NativeWindow]::SetForegroundWindow($window)
  Start-Sleep -Seconds 2
  $result.Version = [ordered]@{
    Url = $versionTarget.url
    Title = $versionTarget.title
    Document = $null
    Screenshot = $null
  }
  Assert-RendererHealthy -Context 'chrome://version page' -Window $window
  $versionState = Get-TargetDocumentState `
    -Target $versionTarget `
    -Context 'chrome://version page'
  Assert-DocumentState `
    -State $versionState `
    -Context 'chrome://version page' `
    -ExpectedUrlPattern '^chrome://version/$'
  if (-not $versionState.bodyText.Contains('(arm64)')) {
    throw 'The chrome://version page did not identify the build as ARM64.'
  }
  $result.Version.Document = Get-DocumentSummary -State $versionState
  $result.Version.Screenshot = Save-WindowCapture -Window $window -Name 'version'
  Assert-RendererHealthy -Context 'chrome://version page' -Window $window
  Write-Host 'PASS: chrome://version loaded in the GUI browser.'

  $encodedGoogleUrl = [Uri]::EscapeDataString('https://www.google.com/')
  $googleTarget = Invoke-RestMethod `
    -Method Put `
    -Uri "http://127.0.0.1:$port/json/new?$encodedGoogleUrl" `
    -TimeoutSec 10 `
    -ErrorAction Stop
  $googleTargetId = $googleTarget.id
  $googleTarget = Wait-Until `
    -TimeoutSeconds $NavigationTimeoutSeconds `
    -FailureMessage 'Google did not finish loading in the GUI browser.' `
    -Condition {
      $targets = Get-DevToolsTargets -Port $port
      $result.ObservedTargets = @(
        $targets | ForEach-Object {
          [ordered]@{
            Id = $_.id
            Type = $_.type
            Url = $_.url
            Title = $_.title
          }
        }
      )
      $target = $targets | Where-Object {
        if ($_.id -ne $googleTargetId -or $_.type -ne 'page' -or
            $_.url -notmatch '^https://([^.]+\.)*google\.com/') {
          return $false
        }
        $targetHost = ([Uri]$_.url).Host
        return $_.title -match 'Google' -and $_.title -ne $targetHost
      } | Select-Object -First 1
      return $target
    }
  Activate-Target -Port $port -TargetId $googleTarget.id
  $null = [Thorium.Woa.NativeWindow]::ShowWindow($window, 9)
  $null = [Thorium.Woa.NativeWindow]::SetForegroundWindow($window)
  Start-Sleep -Seconds 2
  $result.Google = [ordered]@{
    Url = $googleTarget.url
    Title = $googleTarget.title
    Document = $null
    Screenshot = $null
  }
  Assert-RendererHealthy -Context 'Google page' -Window $window
  $googleState = Get-TargetDocumentState `
    -Target $googleTarget `
    -Context 'Google page'
  Assert-DocumentState `
    -State $googleState `
    -Context 'Google page' `
    -ExpectedUrlPattern '^https://([^.]+\.)*google\.com/'
  $result.Google.Document = Get-DocumentSummary -State $googleState
  $result.Google.Screenshot = Save-WindowCapture -Window $window -Name 'google'
  Assert-RendererHealthy -Context 'Google page' -Window $window
  Write-Host "PASS: Google loaded at $($googleTarget.url)"
  $result.Success = $true
} catch {
  $failed = $_
  $result.Error = $_.Exception.ToString()
  if ($window -and $window -ne [IntPtr]::Zero) {
    if ($browserProcess -and $browserProcess.HasExited) {
      $result.RendererFailureDetected = $true
    } else {
      $crashCode = Get-CrashPageErrorCode -Window $window
      if ($crashCode) {
        $result.CrashPageErrorCode = $crashCode
        $result.RendererFailureDetected = $true
      }
    }
    if (Test-CrashDumpExists) {
      $result.RendererFailureDetected = $true
    }
    try {
      $result.FailureScreenshot = Save-WindowCapture `
        -Window $window `
        -Name 'failure'
    } catch {
      $result.Warnings.Add("Failure-window capture failed: $($_.Exception.Message)")
    }
  }
} finally {
  if ($browserProcess) {
    try {
      if (-not $browserProcess.HasExited) {
        $null = $browserProcess.CloseMainWindow()
        if (-not $browserProcess.WaitForExit(15000)) {
          $browserProcess.Kill($true)
          $browserProcess.WaitForExit()
        }
      }
      if ($stdoutTask) {
        Write-Utf8File `
          -Path $stdoutPath `
          -Contents $stdoutTask.GetAwaiter().GetResult()
      }
      if ($stderrTask) {
        Write-Utf8File `
          -Path $stderrPath `
          -Contents $stderrTask.GetAwaiter().GetResult()
      }
    } catch {
      $result.Warnings.Add("Could not stop the GUI browser cleanly: $($_.Exception.Message)")
      if (-not $failed) {
        $failed = $_
        $result.Error = $_.Exception.ToString()
        $result.Success = $false
      }
    } finally {
      $browserProcess.Dispose()
    }
  }
  try {
    Record-CrashArtifacts
  } catch {
    $result.Warnings.Add("Could not enumerate preserved GUI crash dumps: $($_.Exception.Message)")
  }
  if (Test-Path -LiteralPath $ProfileDirectory) {
    try {
      Remove-Item -LiteralPath $ProfileDirectory -Recurse -Force
    } catch {
      $result.Warnings.Add("Could not remove the GUI profile: $($_.Exception.Message)")
    }
  }
  Write-Utf8File -Path $resultPath -Contents ($result | ConvertTo-Json -Depth 8)
}

if ($failed) {
  throw $failed
}
