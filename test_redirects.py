"""Loopback-only HTTP/TLS regression tests; no real credentials or external APIs.

Run with python3 -I test_redirects.py. OpenSSL generates a disposable test cert.
"""

import contextlib
import http.server
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
import urllib.request


TOKEN = "synthetic-redirect-test-token"
CODES = (301, 302, 303, 307, 308)


def load_script(name):
    path = str(Path(__file__).resolve().parent / name)
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.received.append((self.path, self.headers.get("Authorization")))
        if self.path in self.server.redirects:
            code, location = self.server.redirects[self.path]
            self.send_response(code)
            self.send_header("Location", location)
            body = b'{"redirect": true}'
        else:
            self.send_response(200)
            body = b'{"ok": true}'
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class RedirectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resources = contextlib.ExitStack()
        cls.addClassCleanup(cls.resources.close)
        tmp = Path(cls.resources.enter_context(tempfile.TemporaryDirectory()))
        cert, key = tmp / "cert.pem", tmp / "key.pem"
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(key), "-out", str(cert), "-days", "1",
            "-subj", "/CN=localhost",
            "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(str(cert), str(key))
        trust = ssl.create_default_context(cafile=str(cert))
        cls.resources.enter_context(mock.patch(
            "ssl._create_default_https_context", return_value=trust))
        cls.resources.enter_context(mock.patch.dict(os.environ, {}, clear=True))
        cls.resources.enter_context(mock.patch.object(urllib.request, "_opener", None))
        cls.source = cls.start_server(tls)
        cls.other = cls.start_server(tls)
        cls.plain = cls.start_server()
        cls.claude = load_script("claude-usage")
        cls.agent = load_script("agent-usage")

    @classmethod
    def start_server(cls, tls=None):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.resources.callback(server.server_close)
        server.received = []
        server.redirects = {}
        if tls is not None:
            server.socket = tls.wrap_socket(server.socket, server_side=True)
        server.url = "%s://localhost:%d" % (
            "https" if tls is not None else "http", server.server_port)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        cls.resources.callback(thread.join)
        cls.resources.callback(server.shutdown)
        return server

    def reset_servers(self):
        for server in (self.source, self.other, self.plain):
            server.received.clear()
            server.redirects.clear()

    def fetch(self, script, path):
        url = self.source.url + path
        if script == "claude-usage":
            return self.claude.api_get(url, TOKEN)
        with mock.patch.object(self.agent, "CURSOR_USAGE_URL", url):
            return self.agent.fetch_cursor_usage(TOKEN)

    def test_direct_request_sends_bearer(self):
        for script in ("claude-usage", "agent-usage"):
            with self.subTest(script=script):
                self.reset_servers()
                self.assertEqual(self.fetch(script, "/ok"), (200, {"ok": True}))
                self.assertEqual(self.source.received, [("/ok", "Bearer " + TOKEN)])

    def test_installed_scripts_find_shared_module(self):
        root = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as tmp:
            for mode in ("copy", "symlink"):
                dest = Path(tmp) / mode
                dest.mkdir()
                for script in ("claude-usage", "agent-usage"):
                    if mode == "copy":
                        shutil.copyfile(root / script, dest / script)
                    else:
                        (dest / script).symlink_to(root / script)
                if mode == "copy":
                    shutil.copyfile(root / "usage_http.py", dest / "usage_http.py")
                for script in ("claude-usage", "agent-usage"):
                    with self.subTest(mode=mode, script=script):
                        result = subprocess.run(
                            [sys.executable, "-I", str(dest / script), "--help"],
                            cwd=tmp, capture_output=True, text=True, check=True,
                        )
                        self.assertIn("usage:", result.stdout)

    def test_same_origin_redirect_keeps_bearer(self):
        for script in ("claude-usage", "agent-usage"):
            for code in CODES:
                for location in ("/ok", self.source.url + "/ok"):
                    with self.subTest(script=script, code=code, location=location):
                        self.reset_servers()
                        self.source.redirects["/start"] = (code, location)
                        self.assertEqual(self.fetch(script, "/start"), (200, {"ok": True}))
                        self.assertEqual(self.source.received, [
                            ("/start", "Bearer " + TOKEN), ("/ok", "Bearer " + TOKEN)])

    def test_other_origin_and_downgrade_are_blocked(self):
        targets = {
            "port": self.other.url + "/stolen",
            "host": self.source.url.replace("localhost", "127.0.0.1") + "/stolen",
            "scheme_relative": self.other.url[len("https:"):] + "/stolen",
            "downgrade": self.plain.url + "/stolen",
        }
        for script in ("claude-usage", "agent-usage"):
            for code in CODES:
                for kind, location in targets.items():
                    with self.subTest(script=script, code=code, target=kind):
                        self.reset_servers()
                        # Exercise both hops: the first redirect is allowed.
                        self.source.redirects["/start"] = (code, "/next")
                        self.source.redirects["/next"] = (code, location)
                        status, body = self.fetch(script, "/start")
                        stolen = [r for s in (self.source, self.other, self.plain)
                                  for r in s.received if r[0] == "/stolen"]
                        self.assertEqual(stolen, [], "redirect destination was contacted")
                        self.assertEqual(self.source.received, [
                            ("/start", "Bearer " + TOKEN), ("/next", "Bearer " + TOKEN)])
                        self.assertEqual((status, body), (code, {"redirect": True}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
