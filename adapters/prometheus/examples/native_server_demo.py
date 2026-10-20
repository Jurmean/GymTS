"""Real Prometheus scrapes a localhost exporter; this fixture makes no production-quality claim."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import subprocess
import threading
import time
from urllib.request import urlopen

from gymts_prometheus.demo import run_demo


class Exporter(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"# TYPE gymts_demo_value gauge\ngymts_demo_value 42\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--prometheus-binary", required=True)
    args = parser.parse_args()
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    exporter = ThreadingHTTPServer(("127.0.0.1", 0), Exporter)
    threading.Thread(target=exporter.serve_forever, daemon=True).start()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config = root / "prometheus.yml"
    config.write_text('global:\n  scrape_interval: 100ms\n  scrape_timeout: 90ms\n'
        'scrape_configs:\n  - job_name: gymts-local-testbed\n    static_configs:\n      - targets: ["127.0.0.1:'
        + str(exporter.server_port) + '"]\n')
    endpoint = "http://127.0.0.1:" + str(port)
    with (root / "prometheus.log").open("wb") as log:
        process = subprocess.Popen([str(Path(args.prometheus_binary).resolve()), "--config.file=" + str(config),
            "--storage.tsdb.path=" + str(root / "tsdb"), "--web.listen-address=127.0.0.1:" + str(port)], stdout=log, stderr=log)
        try:
            ready = False
            for _ in range(100):
                try:
                    with urlopen(endpoint + "/-/ready", timeout=.5) as response:
                        ready = response.status == 200
                    if ready:
                        break
                except OSError:
                    time.sleep(.05)
            if not ready:
                raise RuntimeError("Native Prometheus was not ready; inspect preserved log")
            # Readiness of HTTP does not imply discovery has produced a scrape.
            metric_ready = False
            for _ in range(200):
                with urlopen(endpoint + "/api/v1/query?query=gymts_demo_value", timeout=1) as response:
                    current = json.load(response)
                if current.get("data", {}).get("result"):
                    metric_ready = True
                    break
                time.sleep(.05)
            if not metric_ready:
                raise RuntimeError("Native exporter has no scraped sample; inspect Prometheus targets/log")
            result = run_demo(root / "records", endpoint, expected_value=42, seconds=3)
            with urlopen(endpoint + "/-/ready", timeout=1) as response:
                assert response.status == 200
            result.update(status="passed", scope="real local Prometheus/testbed integration fixture; no production validation",
                server_alive_after_gym_close=True, fixture_gauge=42,
                binary_sha256=hashlib.sha256(Path(args.prometheus_binary).read_bytes()).hexdigest(), endpoint=endpoint)
            assert result["final_report"]["verdict"] == "pass", result["final_report"]
            (root / "result.json").write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps({"status": "passed", "run_ids": result["run_ids"],
                "task_decisions": result["task_decisions"], "result": str(root / "result.json")}))
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            exporter.shutdown()
            exporter.server_close()


if __name__ == "__main__":
    main()
