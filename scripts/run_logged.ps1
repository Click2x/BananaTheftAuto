<#
.SYNOPSIS
  Run gta6rt.exe with a time limit and write logs that are easy to read.

.DESCRIPTION
  Starts the game runtime, captures everything it prints, stops it after -TimeoutSec if it is still running,
  and writes a short summary.txt next to the raw output. Nothing is installed or changed except an `overlay`
  folder for the game's own writes.

  Logs go to <LogRoot>\run-<time>\ :
    summary.txt   what happened, in about 40 lines (read this first)
    raw.txt       everything the runtime printed (stdout, then stderr)
    trace.json    the runtime's own --trace file (JSON lines)

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\run_logged.ps1 -TimeoutSec 60
  powershell -ExecutionPolicy Bypass -File scripts\run_logged.ps1 -SkipInt3 -TimeoutSec 90
#>
param(
    [string]$Port = 'D:\GTAVI\BTA',                      # the folder with gta6rt.exe, game_path.txt and shader_path.txt
    [string]$GameExe = '',                               # default: game_scarlett_master.exe inside game_path.txt's folder
    [string]$Overlay = '',                               # default: <Port>\overlay (keeps writes out of the game folder)
    [string]$LogRoot = 'D:\Leonida-work\runlogs',
    [int]$TimeoutSec = 60,
    [switch]$SkipInt3,                                   # LEONIDA_SKIP_INT3=1: step over int3 asserts (diagnostic only)
    [switch]$NoVulkan,                                   # leave the backend at its default instead of Vulkan
    [switch]$Experiments,                                # turn on every off-by-default LEONIDA_XS_* / LEONIDA_A8_* experiment
                                                         # below and open a window for PresentX (implies -SkipInt3)
    [switch]$TitleWindow,                                # with -Experiments: present into the title's own window ("Americas",
                                                         # class sgaWindowClass) instead of opening a second one
    [switch]$NoD3D12Trace,                               # leave out --trace-d3d12 (one log line per D3D12 call): faster runs
    [string[]]$ExtraArgs = @()
)

$ErrorActionPreference = 'Stop'
$rt = Join-Path $Port 'gta6rt.exe'
if (-not (Test-Path $rt)) { throw "gta6rt.exe not found in $Port (build with Leonida.bat first)" }
if (-not $GameExe) {
    $gd = (Get-Content (Join-Path $Port 'game_path.txt') -Raw).Trim()
    $GameExe = Join-Path $gd 'game_scarlett_master.exe'
}
if (-not (Test-Path $GameExe)) { throw "game executable not found: $GameExe" }
if (-not $Overlay) { $Overlay = Join-Path $Port 'overlay' }

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$dir = Join-Path $LogRoot "run-$stamp"
New-Item -ItemType Directory -Force $dir | Out-Null
$raw = Join-Path $dir 'raw.txt'; $rawOut = Join-Path $dir 'stdout.tmp'; $rawErr = Join-Path $dir 'stderr.tmp'
$trace = Join-Path $dir 'trace.json'; $summary = Join-Path $dir 'summary.txt'

# What the run uses (restored when this script ends, since it runs in its own PowerShell process)
if (-not $NoVulkan) { $env:LEONIDA_D3D12 = 'vulkan' }
$env:DISABLE_VULKAN_OBS_CAPTURE = '1'     # upstream's advice when OBS is installed
$env:DISABLE_RTSS_LAYER = '1'             # and for MSI Afterburner / RTSS
if ($SkipInt3 -or $Experiments) { $env:LEONIDA_SKIP_INT3 = '1' }
if ($Experiments) {
    # Each of these is off by default in the runtime; what each one does is explained where it is read, in
    # runtime/shims (d3d12_xs_device.cpp, d3d12_xs.cpp, d3d12_vulkan_device.cpp). Diagnostic experiments: not fixes.
    foreach ($name in 'LEONIDA_XS_SLOT61_STUB', 'LEONIDA_XS_SLOT108_GRI', 'LEONIDA_XS_CMDSIG105', 'LEONIDA_XS_CMDSIG_MESH',
                      'LEONIDA_XS_QUEUE35_EXEC', 'LEONIDA_XS_PAGEPOOL', 'LEONIDA_XS_QUEUE_NEWER', 'LEONIDA_A8_ANYFLAGS',
                      'LEONIDA_XS_FENCE12_CELL', 'LEONIDA_XS_LIST139_RESET', 'LEONIDA_XS_WINDOW') {
        Set-Item -Path "Env:$name" -Value '1'
    }
    if ($TitleWindow) { $env:LEONIDA_XS_WINDOW = 'title' }
}

$argList = @('--run', "`"$GameExe`"") + $(if ($NoD3D12Trace) { @() } else { @('--trace-d3d12') }) +
           @('--trace', "`"$trace`"", '--overlay', "`"$Overlay`"") + $ExtraArgs
$started = Get-Date
$p = Start-Process -FilePath $rt -ArgumentList $argList -PassThru -RedirectStandardOutput $rawOut -RedirectStandardError $rawErr -WindowStyle Minimized
$null = $p.Handle    # keeps the exit code readable after the process ends (a known .NET quirk with redirected output)

$timedOut = $false
if (-not $p.WaitForExit($TimeoutSec * 1000)) {
    $timedOut = $true
    try { Stop-Process -Id $p.Id -Force -ErrorAction Stop } catch { }
    Start-Sleep -Milliseconds 500
}
$p.WaitForExit()
$ended = Get-Date
$exit = if ($timedOut) { $null } else { $p.ExitCode }

# One raw file: stdout, then stderr
Get-Content $rawOut -ErrorAction SilentlyContinue | Set-Content $raw -Encoding UTF8
if ((Get-Item $rawErr -ErrorAction SilentlyContinue).Length -gt 0) {
    Add-Content $raw '--- stderr ---' -Encoding UTF8
    Get-Content $rawErr | Add-Content $raw -Encoding UTF8
}
Remove-Item $rawOut, $rawErr -ErrorAction SilentlyContinue

$lines = @(Get-Content $raw -ErrorAction SilentlyContinue)
$traceLines = @(Get-Content $trace -ErrorAction SilentlyContinue)

function Short($s, $n = 170) { if ($s.Length -gt $n) { $s.Substring(0, $n) + '...' } else { $s } }

$out = New-Object System.Collections.Generic.List[string]
$out.Add(("run: {0}   timeout: {1}s   ran: {2:N1}s" -f $stamp, $TimeoutSec, ($ended - $started).TotalSeconds))
$out.Add("game: $GameExe")
$out.Add("flags: vulkan=$(-not $NoVulkan) skip_int3=$($SkipInt3.IsPresent -or $Experiments.IsPresent) experiments=$($Experiments.IsPresent) overlay=$Overlay")
if ($timedOut) { $out.Add("RESULT: still running at the time limit, so it was stopped (no crash seen in this window)") }
else { $out.Add(("RESULT: exited with code {0} (0x{0:X})" -f $exit)) }

# Windows crash events during the run
$ev = @(Get-WinEvent -FilterHashtable @{ LogName = 'Application'; ProviderName = 'Application Error'; StartTime = $started.AddSeconds(-2) } -ErrorAction SilentlyContinue |
        Where-Object { $_.Message -match 'gta6rt' })
foreach ($e in $ev | Select-Object -First 2) {
    $m = $e.Message -split "`r?`n"
    $mod = [string]($m | Where-Object { $_ -match 'Faulting module name' } | Select-Object -First 1)
    $code = [string]($m | Where-Object { $_ -match 'Exception code' } | Select-Object -First 1)
    $out.Add("WINDOWS CRASH EVENT " + $e.TimeCreated.ToString('HH:mm:ss') + ": " + $mod.Trim() + " | " + $code.Trim())
}

# The runtime's own exception records
$exc = @($traceLines | Where-Object { $_ -match '"kind":"exception"' } | Select-Object -First 3)
foreach ($l in $exc) {
    try {
        $j = $l | ConvertFrom-Json
        $out.Add(("EXCEPTION {0} at {1} (t={2:N1}s)" -f $j.code, $j.at, [double]$j.t))
        $out.Add("  stack: " + (($j.stack | Select-Object -First 8) -join ' <- '))
    } catch { $out.Add("EXCEPTION (unparsed): " + (Short $l)) }
}
$skipped = @($traceLines | Where-Object { $_ -match '"kind":"int3_skipped"' })
if ($skipped.Count) { $out.Add("int3 steps skipped: $($skipped.Count) (first: " + (Short $skipped[0] 140) + ")") }
$openFail = @($traceLines | Where-Object { $_ -match '"kind":"file_open_failed"' })
if ($openFail.Count) { $out.Add("guest file opens that failed: $($openFail.Count) (first: " + (Short $openFail[0] 140) + ")") }

# Counts and the last D3D12 call
$d3 = @($lines | Where-Object { $_ -match '^\[d3d12-trace\] #(\d+)' })
if ($d3.Count) { $out.Add("d3d12 calls traced: $($d3.Count); last: " + (Short $d3[-1])) }
$kinds = $traceLines | ForEach-Object { if ($_ -match '"kind":"([a-z0-9_]+)"') { $Matches[1] } } | Group-Object | Sort-Object Count -Descending | Select-Object -First 8
if ($kinds) { $out.Add("trace events: " + (($kinds | ForEach-Object { "$($_.Name)=$($_.Count)" }) -join ', ')) }

# Lines worth reading (not the per-call spam)
$spam = '^\[d3d12-trace\]|first call|^\s+shim\s|^\s+host\s'
$notable = @($lines | Where-Object { $_ -notmatch $spam -and $_ -notmatch 'base=0x?[0-9a-fA-F]+ .*size=' -and $_ -match '\[rt\]|error|fail|unimplemented|unknown|warn|not supported|exception|abort' } | Select-Object -First 25)
if ($notable.Count) { $out.Add(''); $out.Add('notable runtime lines (first 25):'); $notable | ForEach-Object { $out.Add('  ' + (Short $_)) } }

$out.Add(''); $out.Add('last 15 raw lines:')
$lines | Select-Object -Last 15 | ForEach-Object { $out.Add('  ' + (Short $_)) }
$out.Add(''); $out.Add("files: $raw"); $out.Add("       $trace")

$out | Set-Content $summary -Encoding UTF8
Write-Host ($out -join "`n")
Write-Host ""
Write-Host "SUMMARY FILE: $summary"
