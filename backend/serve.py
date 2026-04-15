"""
serve.py  –  Production entry point (Waitress WSGI server, Windows-compatible).
Run this file directly to start the server:
    python serve.py
Or let NSSM run it as a Windows Service.
"""

from waitress import serve
from app import app

HOST = '127.0.0.1'   # IIS reverse proxy talks to localhost only
PORT = 5000

if __name__ == '__main__':
    print(f'Travel Map Tool running on http://{HOST}:{PORT}')
    serve(app, host=HOST, port=PORT, threads=4)
