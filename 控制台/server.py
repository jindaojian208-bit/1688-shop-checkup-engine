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

            # 调 claude -p（非交互式 + 跳权限 + 流式 JSON）
            cmd = [
                'claude', '-p', prompt,
                '--dangerously-skip-permissions',  # 跳过所有权限确认（owner 自己机器，授权范围）
                '--output-format', 'stream-json',  # 流式 JSON 输出
                '--include-partial-messages',       # 实时 token
                '--verbose',                        # 必须配 stream-json
            ]
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=1,
                    text=True,
                    cwd=os.path.expanduser('~/projects/_1688店铺体检引擎/'),
                )
            except FileNotFoundError:
                self._send_event('error', '❌ 找不到 claude 命令。确认 Claude Code CLI 已安装并在 PATH。')
                self._send_event('done', '')
                return

            self._send_event('status', f'⏳ Claude 进程启动 · PID {proc.pid} · 跳权限 + 流式 JSON 模式')

            # 流式读取 stdout（每行一个 JSON）
            for line in iter(proc.stdout.readline, ''):
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    self._handle_claude_event(obj)
                except json.JSONDecodeError:
                    # 不是 JSON 就当普通 log
                    self._send_event('log', line)
                try:
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    proc.kill()
                    return

            # 收尾：读 stderr（如果有错）
            stderr_output = proc.stderr.read() if proc.stderr else ''
            return_code = proc.wait()
            if return_code == 0:
                self._send_event('status', '✅ 体检完成 · 检查桌面 PDF + git push 状态')
            else:
                self._send_event('error', f'❌ Claude 进程退出码 {return_code}')
                if stderr_output:
                    self._send_event('error', f'stderr: {stderr_output[:1000]}')

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

    def _handle_claude_event(self, obj: dict):
        """解析 Claude stream-json 输出 · 把关键事件转发给前端"""
        evt_type = obj.get('type', '')

        if evt_type == 'system':
            sub = obj.get('subtype', '')
            if sub == 'init':
                self._send_event('status', f'🔧 Claude 会话初始化 · session={obj.get("session_id", "?")[:8]}')
            elif sub.startswith('hook_'):
                # hook 事件太多，不展示给前端避免刷屏
                pass
            else:
                self._send_event('status', f'🔧 system: {sub}')

        elif evt_type == 'assistant':
            # Claude 助手输出
            msg = obj.get('message', {})
            for block in msg.get('content', []) or []:
                btype = block.get('type', '')
                if btype == 'text':
                    text = block.get('text', '').strip()
                    if text:
                        self._send_event('log', f'💬 {text}')
                elif btype == 'tool_use':
                    tool_name = block.get('name', '')
                    tool_input = block.get('input', {})
                    # 简化展示
                    summary = self._summarize_tool_call(tool_name, tool_input)
                    self._send_event('log', f'🔨 {tool_name}: {summary}')
                elif btype == 'thinking':
                    # 不展示思考过程（太长）
                    pass

        elif evt_type == 'user':
            # 用户消息（包含 tool_result）
            msg = obj.get('message', {})
            for block in msg.get('content', []) or []:
                btype = block.get('type', '')
                if btype == 'tool_result':
                    is_error = block.get('is_error', False)
                    if is_error:
                        content = block.get('content', '')
                        if isinstance(content, list):
                            content = ' '.join(c.get('text', '') for c in content if isinstance(c, dict))
                        self._send_event('error', f'⚠️ 工具错误: {str(content)[:200]}')

        elif evt_type == 'result':
            sub = obj.get('subtype', '')
            cost = obj.get('total_cost_usd', 0)
            duration = obj.get('duration_ms', 0)
            num_turns = obj.get('num_turns', 0)
            if sub == 'success':
                self._send_event('status', f'🎉 体检完成 · {num_turns} 轮 · ${cost:.3f} · {duration/1000:.1f}s')
            else:
                self._send_event('error', f'❌ 失败 · subtype={sub}')

        elif evt_type == 'stream_event':
            # 实时 token，太碎不展示，避免刷屏
            pass

    def _summarize_tool_call(self, name: str, inp: dict) -> str:
        """简化展示工具调用"""
        if name == 'Bash':
            cmd = inp.get('command', '')[:80]
            desc = inp.get('description', '')
            return f'{desc or cmd}'
        if name == 'Read':
            return inp.get('file_path', '')
        if name == 'Write':
            return f"写入 {inp.get('file_path', '')}"
        if name == 'Edit':
            return f"编辑 {inp.get('file_path', '')}"
        if 'mcp__plugin_superpowers-chrome' in name:
            action = inp.get('action', '')
            payload = (inp.get('payload', '') or '')[:60]
            return f'browser.{action}: {payload}'
        if name == 'TodoWrite' or 'Task' in name:
            return f'<{name}>'
        return str(inp)[:120]


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
