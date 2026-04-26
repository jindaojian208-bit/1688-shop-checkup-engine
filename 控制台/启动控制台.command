#!/bin/bash
# 1688 店铺体检引擎 · 一键启动器 v3.0
# 双击桌面副本即可：自动启动后端 + 弹出浏览器

set -e

# 用绝对路径定位引擎目录（双击 .command 时 cwd 不一定在引擎目录）
cd ~/projects/_1688店铺体检引擎/控制台

PORT=5688
URL="http://localhost:${PORT}/1688体检引擎_控制台.html"

# 检查端口是否已占用（之前的 server 可能没退）
if lsof -ti:${PORT} > /dev/null 2>&1; then
  echo "🟡 端口 ${PORT} 已占用，可能已有 server 在跑"
  echo "💡 直接打开浏览器："
  open "$URL"
  exit 0
fi

# 启动后端
echo "🎯 1688 店铺体检引擎 · 启动中..."
echo "📍 控制台 URL：$URL"
echo "🛑 关闭本终端窗口即停止后端"
echo ""

# 后台启动浏览器（等 server 起来）
(
  sleep 1.5
  open "$URL"
) &

# 前台跑 server（这个 Terminal 关闭 = server 关闭）
exec python3 server.py
