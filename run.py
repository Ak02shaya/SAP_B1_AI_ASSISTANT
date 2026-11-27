import subprocess
import sys
import webbrowser
import time
import threading

print("=" * 60)
print("🚀 Starting Vantage AI for SAP Business One (FastAPI + Modern Web UI)...")
print("👉 Open your browser at: http://localhost:8000")
print("=" * 60)

# Launch FastAPI which directly serves both the API and the modern Web UI
backend = subprocess.Popen([sys.executable, "-m", "uvicorn", "middleware:app", "--reload", "--port", "8000"])

# Open the browser automatically
def open_browser():
    time.sleep(1.5)
    try:
        webbrowser.open("http://localhost:8000")
    except Exception:
        pass

threading.Thread(target=open_browser, daemon=True).start()

try:
    backend.wait()
except KeyboardInterrupt:
    print("\nShutting down server...")
    backend.terminate()
    print("Server stopped.")
