"""Run the public API: uv run python -m api (port from API_PORT, default 8002)."""

import os

import uvicorn

from api.app import create_app

if __name__ == "__main__":
    uvicorn.run(
        create_app(),
        host=os.environ.get("API_HOST", "127.0.0.1"),
        port=int(os.environ.get("API_PORT", "8002")),
    )
