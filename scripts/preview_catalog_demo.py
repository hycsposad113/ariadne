from __future__ import annotations

import argparse
import os
import socket
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from urban_design.morphology.preview_api import create_preview_router


def create_demo_app(root: Path | None, manifest_sha256: str | None) -> FastAPI:
    app = FastAPI(
        title="Isolated morphology preview demo",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^http://(?:127\.0\.0\.1|localhost):\d+$",
        allow_methods=["GET"],
        allow_headers=["Accept"],
        expose_headers=["ETag"],
    )
    app.include_router(create_preview_router(root=root, manifest_sha256=manifest_sha256))
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a loopback-only, read-only morphology preview API.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(os.environ["MORPHOLOGY_PREVIEW_ROOT"]) if os.environ.get("MORPHOLOGY_PREVIEW_ROOT") else None,
        help="bundle directory (or set MORPHOLOGY_PREVIEW_ROOT)",
    )
    parser.add_argument(
        "--manifest-sha256",
        default=os.environ.get("MORPHOLOGY_PREVIEW_MANIFEST_SHA256"),
        help="pinned artifact manifest SHA-256 (or set MORPHOLOGY_PREVIEW_MANIFEST_SHA256)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="Use 0 to request an OS-assigned free port.")
    args = parser.parse_args()

    if args.host not in {"127.0.0.1", "localhost"}:
        parser.error("the preview demo may bind to loopback only")
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    if args.root is None or args.manifest_sha256 is None:
        parser.error("set --root and --manifest-sha256 or provide both preview environment variables")

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((args.host, args.port))
    listener.listen(128)
    listener.setblocking(False)
    host, port = listener.getsockname()[:2]

    app = create_demo_app(args.root, args.manifest_sha256)
    print("PREVIEW_API_URL=http://" + str(host) + ":" + str(port), flush=True)
    print("PREVIEW_ROOT=" + str(args.root), flush=True)
    print("PREVIEW_MANIFEST_SHA256=" + args.manifest_sha256, flush=True)
    server = uvicorn.Server(uvicorn.Config(app, host=str(host), port=port, log_level="info"))
    try:
        server.run(sockets=[listener])
    finally:
        listener.close()


if __name__ == "__main__":
    main()
