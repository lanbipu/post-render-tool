# build_all_versions.ps1 — 在 lanPC 上批量打包 PostRenderTool 插件 (UE 5.1-5.8)
# 用法: powershell -ExecutionPolicy Bypass -File build_all_versions.ps1 [-Versions 5.6,5.7] [-SourceDir C:\temp\prt-src] [-OutDir E:\PluginReleases]
param(
    [string[]]$Versions = @("5.1","5.2","5.3","5.4","5.5","5.6","5.7","5.8"),
    [string]$SourceDir = "C:\temp\prt-src",
    [string]$OutDir = "E:\PluginReleases",
    [string]$EngineRoot = "D:\Program Files\Epic Games"
)

$ErrorActionPreference = "Stop"
# powershell -File 模式下 "5.1,5.2" 会作为单个字符串传入, 统一拆分
$Versions = @($Versions | ForEach-Object { $_ -split ',' } | Where-Object { $_ })
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$workRoot = "C:\temp\prt-build"
New-Item -ItemType Directory -Force -Path $OutDir, $workRoot | Out-Null
$summary = @()

# 白名单: 只打包插件本体
$whitelist = @("PostRenderTool.uplugin", "Source", "Content", "docs", "README.md")

foreach ($ver in $Versions) {
    $uat = Join-Path $EngineRoot "UE_$ver\Engine\Build\BatchFiles\RunUAT.bat"
    $logFile = Join-Path $OutDir "build_$($ver)_$stamp.log"
    if (-not (Test-Path -LiteralPath $uat)) {
        Write-Host "[$ver] SKIP — engine not found: $uat"
        $summary += [pscustomobject]@{Version=$ver; Result="ENGINE_MISSING"; Log=""}
        continue
    }

    # 1. 白名单复制源码到 temp
    $tmpSrc = Join-Path $workRoot "src_$ver"
    $pkgDir = Join-Path $workRoot "pkg_$ver"
    Remove-Item -Recurse -Force $tmpSrc, $pkgDir -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $tmpSrc | Out-Null
    foreach ($item in $whitelist) {
        $src = Join-Path $SourceDir $item
        if (Test-Path -LiteralPath $src) {
            Copy-Item -Recurse -Force -LiteralPath $src -Destination (Join-Path $tmpSrc $item)
        }
    }
    Get-ChildItem $tmpSrc -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
    Get-ChildItem $tmpSrc -Recurse -Force -Filter ".DS_Store" | Remove-Item -Force

    # 2. 改写 EngineVersion
    $upluginPath = Join-Path $tmpSrc "PostRenderTool.uplugin"
    (Get-Content $upluginPath -Raw) -replace '"EngineVersion"\s*:\s*"[^"]*"', "`"EngineVersion`": `"$ver.0`"" |
        Set-Content $upluginPath -Encoding UTF8

    # 3. <=5.6 剔除 5.7 保存的 .uasset (老引擎打不开, 由 rebuild_from_spec + run_build 现场生成)
    if ([version]"$ver.0" -le [version]"5.6.0") {
        # 5.7 保存的全部 .uasset(BP / Material / UI 贴图)老引擎都打不开, 一律剔除
        Get-ChildItem (Join-Path $tmpSrc "Content") -Recurse -Filter "*.uasset" | Remove-Item -Force
        $installMd = @(
            "# PostRenderTool $ver 安装说明",
            "",
            "本包不含 Blueprint/Material 资产 (UE 5.7 保存的 .uasset 无法被 $ver 打开)。",
            "安装后在 UE Python console 依次执行以下命令现场生成:",
            "",
            "    from post_render_tool import build_distortion_material",
            "    build_distortion_material.run_build()",
            "    from post_render_tool.widget_builder import rebuild_from_spec",
            "    rebuild_from_spec()",
            "",
            "之后 import init_post_render_tool 即可打开工具。"
        )
        $installMd | Set-Content (Join-Path $tmpSrc "INSTALL.md") -Encoding UTF8
    }

    # 3.5 老引擎不认新 MSVC 14.44, 通过 BuildConfiguration.xml 按版本 pin 工具链
    #     5.1 → 14.33 (VS2022 17.3), 5.2–5.4 → 14.34 (VS2022 17.4), ≥5.5 → 默认
    $buildCfgDir = Join-Path $env:APPDATA "Unreal Engine\UnrealBuildTool"
    $buildCfg = Join-Path $buildCfgDir "BuildConfiguration.xml"
    New-Item -ItemType Directory -Force -Path $buildCfgDir | Out-Null
    $pinned = $null
    if ($ver -eq "5.1") { $pinned = "14.33.31629" }
    elseif (@("5.2","5.3","5.4") -contains $ver) { $pinned = "14.34.31933" }
    if ($pinned) {
        @(
            '<?xml version="1.0" encoding="utf-8" ?>',
            '<Configuration xmlns="https://www.unrealengine.com/BuildConfiguration">',
            '  <WindowsPlatform>',
            "    <CompilerVersion>$pinned</CompilerVersion>",
            '  </WindowsPlatform>',
            '</Configuration>'
        ) | Set-Content $buildCfg -Encoding UTF8
    } else {
        Remove-Item -Force $buildCfg -ErrorAction SilentlyContinue
    }

    # 4. BuildPlugin
    Write-Host "[$ver] building..."
    & $uat BuildPlugin -Plugin="$upluginPath" -Package="$pkgDir" -TargetPlatforms=Win64 -Rocket *> $logFile
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[$ver] FAILED — log: $logFile"
        $summary += [pscustomobject]@{Version=$ver; Result="BUILD_FAILED"; Log=$logFile}
        continue
    }

    # 5. zip (BuildPlugin 不拷贝非标准文件, INSTALL.md 需在打包前补进产物目录)
    $tmpInstall = Join-Path $tmpSrc "INSTALL.md"
    if (Test-Path $tmpInstall) { Copy-Item -Force $tmpInstall (Join-Path $pkgDir "INSTALL.md") }
    $zipPath = Join-Path $OutDir "PostRenderTool_$($ver)_Win64.zip"
    Remove-Item -Force $zipPath -ErrorAction SilentlyContinue
    Compress-Archive -Path "$pkgDir\*" -DestinationPath $zipPath
    Write-Host "[$ver] OK — $zipPath"
    $summary += [pscustomobject]@{Version=$ver; Result="OK"; Log=$logFile}
}

# 汇总
$summaryPath = Join-Path $OutDir "build_summary_$stamp.md"
$lines = @("# PostRenderTool build summary $stamp", "", "| Version | Result | Log |", "|---|---|---|")
$lines += $summary | ForEach-Object { "| $($_.Version) | $($_.Result) | $($_.Log) |" }
$lines | Set-Content $summaryPath -Encoding UTF8
Write-Host "`n==== SUMMARY ===="
$summary | Format-Table -AutoSize | Out-String | Write-Host
if ($summary | Where-Object { $_.Result -eq "BUILD_FAILED" }) { exit 1 }
