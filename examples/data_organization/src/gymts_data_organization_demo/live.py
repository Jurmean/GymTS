"""A genuine owned Prometheus process scraping a local exporter."""
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import subprocess
import threading
import time
from urllib.request import urlopen

EXPECTED_VALUE = 42.0


class Exporter(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"# TYPE gymts_demo_value gauge\ngymts_demo_value 42\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


@contextmanager
def owned_prometheus(binary, output):
    output = Path(output)
    output.mkdir()
    exporter = ThreadingHTTPServer(("127.0.0.1", 0), Exporter)
    threading.Thread(target=exporter.serve_forever, daemon=True).start()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    endpoint = "http://127.0.0.1:" + str(port)
    config = output / "prometheus.yml"
    config.write_text('global:\n  scrape_interval: 100ms\n  scrape_timeout: 90ms\n'
        'scrape_configs:\n  - job_name: gymts-four-source-example\n    static_configs:\n      - targets: ["127.0.0.1:' + str(exporter.server_port) + '"]\n')
    process = None
    with (output / "prometheus.log").open("xb") as log:
        try:
            process = subprocess.Popen([str(Path(binary).resolve()), "--config.file=" + str(config),
                "--storage.tsdb.path=" + str(output / "tsdb"), "--web.listen-address=127.0.0.1:" + str(port)],
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            for _ in range(200):
                try:
                    with urlopen(endpoint + "/api/v1/query?query=gymts_demo_value", timeout=.5) as response:
                        ready = bool(json.load(response).get("data", {}).get("result"))
                    if ready:
                        break
                except OSError:
                    pass
                time.sleep(.05)
            else:
                raise RuntimeError("Owned native Prometheus did not scrape the exporter; inspect its log")
            version = subprocess.run([str(Path(binary).resolve()), "--version"], capture_output=True, text=True, check=True)
            yield endpoint, {"version": version.stdout.splitlines()[0],
                "binary_sha256": hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
                "query": "gymts_demo_value", "ownership": "example-owned native service; adapter attaches read-only"}
        finally:
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            exporter.shutdown()
            exporter.server_close()
