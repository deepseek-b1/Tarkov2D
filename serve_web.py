# -*- coding: utf-8 -*-
"""本地起网页版服务器(带 COOP/COEP 头,pygbag 多线程运行时才跑得快)。

用法: python serve_web.py [端口]
手机连同一个 Wi-Fi,浏览器打开 http://<电脑IP>:端口 即可玩。
"""
import http.server
import os
import socket
import socketserver
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(ROOT, "webapp", "build", "web")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=WEB, **kw)

    def end_headers(self):
        # 跨源隔离头:SharedArrayBuffer 可用 -> pygbag 走多线程,速度更快
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "cross-origin")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main():
    if not os.path.exists(os.path.join(WEB, "index.html")):
        print("还没有生成网页版,先跑:python build_web.py")
        return 1
    try:
        ips = socket.gethostbyname_ex(socket.gethostname())[2]
    except Exception:
        ips = []
    print(f"网页版目录:{WEB}")
    print(f"电脑上打开: http://localhost:{PORT}")
    for ip in ips:
        print(f"手机上打开: http://{ip}:{PORT}   (需同一 Wi-Fi)")
    print("按 Ctrl+C 停止\n")
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("0.0.0.0", PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main())
