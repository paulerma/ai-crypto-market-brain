import socket
import subprocess
import sys


def free_port(start=8510, end=8525):
    for port in range(start, end + 1):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                pass
    raise RuntimeError("No hay un puerto local libre entre 8510 y 8525.")


port = free_port()
print(f"AI Crypto Market Brain se abrirá en http://localhost:{port}")
subprocess.run([
    sys.executable, "-m", "streamlit", "run", "app.py",
    "--server.port", str(port),
    "--browser.gatherUsageStats", "false",
], check=False)
