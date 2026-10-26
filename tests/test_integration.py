import http.server
import os
import subprocess
import threading

import pytest

from sandboxes.container import ContainerSandbox
from tools.computer_use import ComputerUse


@pytest.mark.skipif(os.environ.get("AASS_INTEGRATION") != "1", reason="set AASS_INTEGRATION=1")
def test_real_docker_isolation_and_functional_test(tmp_path):
    (tmp_path / ".env").write_text("DO_NOT_EXPORT=yes")
    (tmp_path / "test_isolation.py").write_text("""import os, pathlib, socket, unittest
class Isolation(unittest.TestCase):
 def test_isolation(self):
  self.assertFalse(pathlib.Path('/workspace/.env').exists())
  self.assertFalse(pathlib.Path('/var/run/docker.sock').exists())
  self.assertIsNone(os.environ.get('AASS_JUDGE_API_KEY'))
  with self.assertRaises(OSError): pathlib.Path('/workspace/escape').write_text('no')
  with self.assertRaises(OSError): pathlib.Path('/etc/escape').write_text('no')
  with self.assertRaises(OSError): socket.create_connection(('1.1.1.1',443),timeout=1)
""")
    result = ContainerSandbox(tmp_path).run(["python", "-m", "unittest", "discover", "-v"])
    assert result.returncode == 0, result.stderr
    assert "Ran 1 test" in result.stderr
    assert not (tmp_path / "escape").exists()


@pytest.mark.skipif(os.environ.get("AASS_INTEGRATION") != "1", reason="set AASS_INTEGRATION=1")
def test_real_docker_timeout(tmp_path):
    (tmp_path / "test_hang.py").write_text("import time\ntime.sleep(30)\n")
    result = ContainerSandbox(tmp_path, timeout=2).run(["python", "-m", "unittest", "discover"])
    assert result.timed_out
    assert result.returncode == 124
    containers = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True, check=True
    )
    assert not any(name.startswith("aass-") for name in containers.stdout.splitlines())


@pytest.mark.skipif(os.environ.get("AASS_INTEGRATION") != "1", reason="set AASS_INTEGRATION=1")
def test_real_docker_output_limit(tmp_path):
    (tmp_path / "test_noise.py").write_text('print("x" * 200000)\n')
    result = ContainerSandbox(tmp_path).run(["python", "-m", "unittest", "discover"])
    assert result.output_limited
    assert result.returncode == 125
    assert len(result.stdout.encode()) <= 65536


@pytest.mark.skipif(os.environ.get("AASS_INTEGRATION") != "1", reason="set AASS_INTEGRATION=1")
def test_real_browser_navigation_click_screenshot_and_origin_denial(tmp_path):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(
                b"<title>AASS fixture</title><button onclick=\"this.textContent='clicked'\">go</button>"
            )

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        with ComputerUse([url]) as browser:
            assert browser.navigate(url)["title"] == "AASS fixture"
            browser.click("button")
            assert browser.page.locator("button").inner_text() == "clicked"
            browser.click(x=1, y=1)
            artifact = tmp_path / "screenshot.png"
            browser.screenshot(artifact)
            assert artifact.read_bytes().startswith(b"\x89PNG")
            with pytest.raises(PermissionError):
                browser.navigate("https://example.com")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.skipif(os.environ.get("AASS_INTEGRATION") != "1", reason="set AASS_INTEGRATION=1")
def test_browser_helper_keeps_provider_keys_out_of_sdk_process(tmp_path, monkeypatch):
    from tools.browser_session import BrowserSession

    monkeypatch.setenv("AASS_JUDGE_API_KEY", "private-fixture-not-for-browser")

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(
                b"<title>Isolated browser</title><button onclick=\"this.textContent='clicked'\">go</button>"
            )

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    browser = None
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        browser = BrowserSession([url])
        assert browser.navigate(url)["title"] == "Isolated browser"
        browser.click("button")
        assert "clicked" in browser.text()
        image = tmp_path / "helper.png"
        browser.screenshot(image)
        assert image.read_bytes().startswith(b"\x89PNG")
        with pytest.raises(RuntimeError, match="PermissionError"):
            browser.navigate("https://unlisted.example")
    finally:
        if browser:
            browser.close()
            assert browser.process.poll() == 0
        server.shutdown()
        server.server_close()
        thread.join()
