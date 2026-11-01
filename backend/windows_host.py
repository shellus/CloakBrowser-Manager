"""Loopback-only service entry with graceful Windows shutdown via Manager API."""
import argparse

import uvicorn

from .main import app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=18081)
    args = parser.parse_args()
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=args.port))
    app.state.uvicorn_server = server
    server.run()


if __name__ == '__main__':
    main()
