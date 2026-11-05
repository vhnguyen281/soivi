"""Run the review app: uv run python -m review_app"""

import os

import uvicorn

from review_app.app import create_app

if __name__ == "__main__":
    uvicorn.run(
        create_app(),
        host=os.environ.get("REVIEW_HOST", "127.0.0.1"),
        port=int(os.environ.get("REVIEW_PORT", "8001")),
    )
