#!/usr/bin/env bash
# package_releases.sh — Mac 侧 driver: 同步源码到 lanPC → 批量打包 → 拉回汇总
# 用法: scripts/package_releases.sh [版本...]   例: scripts/package_releases.sh 5.6 5.7
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE=lanpc
REMOTE_SRC="C:/temp/prt-src"
REMOTE_OUT="E:/PluginReleases"
LOCAL_OUT="$REPO_ROOT/releases"

VERSIONS=("$@")

echo "== 1/4 同步源码到 $REMOTE:$REMOTE_SRC (tar over ssh, lanPC 无 rsync) =="
ssh "$REMOTE" "powershell -Command \"Remove-Item -Recurse -Force $REMOTE_SRC -ErrorAction SilentlyContinue; New-Item -ItemType Directory -Force -Path $REMOTE_SRC | Out-Null\""
COPYFILE_DISABLE=1 tar -czf - -C "$REPO_ROOT" \
  --exclude='__pycache__' --exclude='.DS_Store' --exclude='._*' \
  PostRenderTool.uplugin README.md Source Content docs scripts/build_all_versions.ps1 |
  ssh "$REMOTE" "tar -xzf - -C $REMOTE_SRC"

echo "== 2/4 远程批量打包 =="
VER_ARG=""
if [ ${#VERSIONS[@]} -gt 0 ]; then
  VER_ARG="-Versions $(IFS=,; echo "${VERSIONS[*]}")"
fi
ssh "$REMOTE" "powershell -ExecutionPolicy Bypass -File $REMOTE_SRC/scripts/build_all_versions.ps1 -SourceDir $REMOTE_SRC -OutDir $REMOTE_OUT $VER_ARG" || BUILD_RC=$?

echo "== 3/4 拉回汇总与日志 =="
mkdir -p "$LOCAL_OUT"
scp "$REMOTE:$REMOTE_OUT/build_summary_*.md" "$LOCAL_OUT/" 2>/dev/null || true
scp "$REMOTE:$REMOTE_OUT/build_*.log" "$LOCAL_OUT/" 2>/dev/null || true

echo "== 4/4 最新汇总 =="
ls -t "$LOCAL_OUT"/build_summary_*.md 2>/dev/null | head -1 | xargs cat 2>/dev/null || echo "(无汇总文件)"
echo "zip 产物在 lanPC: $REMOTE_OUT (体积大, 不自动拉回; 需要时 scp)"
exit "${BUILD_RC:-0}"
