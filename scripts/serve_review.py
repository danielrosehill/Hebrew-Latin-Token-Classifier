#!/usr/bin/env python3
"""Serve review/ over HTTP so the reviewer can fetch queue.json.

Browsers block fetch() from file:// URLs, so opening review/index.html directly
will not load the queue. Run this instead.

Usage: python3 scripts/serve_review.py [port]
"""
import functools
import http.server
import pathlib
import socketserver
import sys
import webbrowser

ROOT = pathlib.Path(__file__).resolve().parent.parent / "review"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765

handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
with socketserver.TCPServer(("127.0.0.1", PORT), handler) as httpd:
    url = f"http://127.0.0.1:{PORT}/index.html"
    print(f"review UI: {url}\nctrl-c to stop")
    webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print()
