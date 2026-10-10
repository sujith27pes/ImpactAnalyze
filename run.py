"""Start the local API and worker without a PowerShell script or policy change."""
import argparse
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def stop_worker(process):
    if process.poll() is not None:
        return
    if os.name == 'nt':
        # Only the worker tree created by this launcher; venv Python may use a child.
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--check', action='store_true', help='Check dependencies without starting services')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    if sys.version_info < (3, 12):
        parser.error('Python 3.12 or later is required')
    os.chdir(ROOT)
    try:
        import uvicorn
        import fastapi
        import sqlalchemy
        import httpx
        import tree_sitter
        import tree_sitter_java
    except ImportError:
        print('Dependencies are missing. Install requirements.txt with this Python interpreter.', file=sys.stderr)
        return 1
    from studio.config import settings
    from studio.engine import identity
    if identity()['status'] != 'READY':
        print('The pinned parser is unavailable. Install requirements.txt with this Python interpreter.', file=sys.stderr)
        return 1
    if args.check:
        print('Python dependencies and pinned parser ready. No services started.')
        return 0
    try:
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', args.port))
    except OSError:
        print(f'Port {args.port} is already in use. Stop the existing app or choose --port 8081.', file=sys.stderr)
        return 1
    # Initialize schema in the API process before its worker starts.
    from studio.api import app
    if os.name == 'nt':
        # Both console interrupt keys must unwind finally, including Uvicorn's
        # re-raised Ctrl+Break after its graceful shutdown.
        signal.signal(signal.SIGBREAK, signal.default_int_handler)
        import ctypes
        ctypes.windll.kernel32.SetConsoleCtrlHandler(None, False)
    (ROOT / 'data').mkdir(exist_ok=True)
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    with (ROOT / 'data/worker.log').open('ab') as output, (ROOT / 'data/worker.err.log').open('ab') as errors:
        worker = subprocess.Popen([sys.executable, '-m', 'studio.worker'], cwd=ROOT,
                                  stdout=output, stderr=errors, creationflags=flags)
        print(f'Impact Studio: http://127.0.0.1:{args.port} | worker PID: {worker.pid}', flush=True)
        print('Press Ctrl+C to stop the API and worker. Configure credentials through environment variables or a private backend .env.', flush=True)
        try:
            uvicorn.run(app, host='127.0.0.1', port=args.port)
        except KeyboardInterrupt:
            pass
        finally:
            stop_worker(worker)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
