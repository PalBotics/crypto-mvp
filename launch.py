import os
import subprocess
import sys
import time
import urllib.request

BACKEND_URL = "http://127.0.0.1:8000"
HEALTH_URL = f"{BACKEND_URL}/api/health"
WINDOW_TITLE = "crypto-mvp"
WINDOW_WIDTH = 1440
WINDOW_HEIGHT = 900


def wait_for_backend(retries=30, delay=0.5) -> bool:
    for _ in range(retries):
        try:
            urllib.request.urlopen(HEALTH_URL, timeout=1)
            return True
        except Exception:
            time.sleep(delay)
    return False


def start_backend() -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable,
            "-m", "uvicorn",
            "apps.dashboard.main:app",
            "--host", "127.0.0.1",
            "--port", "8000",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main():
    print("Starting backend...")
    proc = start_backend()

    print("Waiting for backend to be ready...")
    if not wait_for_backend():
        print("ERROR: Backend did not start in time.")
        proc.terminate()
        sys.exit(1)

    print("Backend ready. Opening window...")

    from PySide6.QtWidgets import QApplication
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtCore import QUrl, Qt

    app = QApplication(sys.argv)
    app.setApplicationName(WINDOW_TITLE)

    window = QWebEngineView()
    window.setWindowTitle(WINDOW_TITLE)
    window.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
    window.load(QUrl(BACKEND_URL))
    window.show()

    def on_app_exit():
        print("Window closed. Terminating backend...")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    app.aboutToQuit.connect(on_app_exit)
    exit_code = app.exec()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
