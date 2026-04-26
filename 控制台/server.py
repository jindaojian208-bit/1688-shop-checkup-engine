#!/usr/bin/env python3
"""
1688 店铺体检引擎 · 本地后端 v3.0

- 接收网页 POST → 调 claude -p 跑 SOP → SSE 流式回传 Claude 输出
- 0 依赖（只用 Python 标准库）
- 启动命令：python3 server.py
- 浏览器访问：http://localhost:5688/1688体检引擎_控制台.html
"""

import http.server
import json
import os
import socketserver
import subprocess
import sys
import threading
from urllib.parse import urlparse

PORT = 5688
ROOT = os.path.dirname(os.path.abspath(__file__))


class Handler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler · GET 服务静态文件 + POST /run 调 claude -p"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def log_message(self, fmt, *args):
        # 简化日志
        sys.stderr.write(f"[{self.address_string()}] {fmt % args}\n")

    def do_POST(self):
        if self.path != '/run':
            self.send_error(404)
            return

        try:
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length).decode('utf-8'))
            prompt = body.get('prompt', '').strip()
            if not prompt:
                self.send_error(400, 'Missing prompt')
                return

            # 启用 SSE 流式响应
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            self._send_event('status', '🚀 启动 Claude · 接管浏览器执行 SOP')
            self._send_event('status', f'📝 触发词长度：{len(prompt)} 字')

            # 调 claude -p（非交互式，stream 输出）
            try:
                proc = subprocess.Popen(
                    ['claude', '-p', prompt],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    bufsize=1,
                    text=True,
                    cwd=os.path.expanduser('~/projects/_1688店铺体检引擎/'),
                )
            except FileNotFoundError:
                self._send_event('error', '❌ 找不到 claude 命令。确认 Claude Code CLI 已安装并在 PATH。')
                self._send_event('done', '')
                return

            self._send_event('status', f'⏳ Claude 进程启动 · PID {proc.pid}')

            # 流式读取 stdout
            for line in iter(proc.stdout.readline, ''):
                if not line:
                    break
                line = line.rstrip()
                if line:
                    self._send_event('log', line)
                    try:
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        # 网页关闭了
                        proc.kill()
                        return

            return_code = proc.wait()
            if return_code == 0:
                self._send_event('status', '✅ 体检完成 · 检查桌面 PDF + git push 状态')
            else:
                self._send_event('error', f'❌ Claude 进程退出码 {return_code}')

            self._send_event('done', '')

        except Exception as e:
            try:
                self._send_event('error', f'❌ 后端异常：{type(e).__name__}: {e}')
                self._send_event('done', '')
            except Exception:
                pass

    def _send_event(self, event_type: str, data: str):
        """SSE event with type"""
        try:
            payload = {'type': event_type, 'data': data}
            self.wfile.write(f'data: {json.dumps(payload, ensure_ascii=False)}\n\n'.encode('utf-8'))
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """多线程 server · 让一个用户跑体检时另一个能开新页面"""
    daemon_threads = True
    allow_reuse_address = True


def main():
    print(f"\n{'=' * 56}")
    print(f"🎯 1688 店铺体检引擎 · 本地后端 v3.0")
    print(f"{'=' * 56}")
    print(f"📍 控制台 URL：http://localhost:{PORT}/1688体检引擎_控制台.html")
    print(f"📂 工作目录：{ROOT}")
    print(f"🛑 按 Ctrl+C 停止")
    print(f"{'=' * 56}\n")

    try:
        server = ThreadedHTTPServer(('127.0.0.1', PORT), Handler)
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n\n👋 后端已停止')
    except OSError as e:
        if e.errno == 48:  # Address already in use
            print(f"\n❌ 端口 {PORT} 已被占用。可能已有一个 server 在跑。")
            print(f"💡 检查：lsof -i :{PORT}")
            sys.exit(1)
        raise


if __name__ == '__main__':
    main()
