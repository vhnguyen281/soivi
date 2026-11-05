"""MinioStore against the MinIO from `make up`. Skipped if MinIO is not reachable."""

import uuid

import pytest

from pipeline.fetch.storage import MinioStore

pytestmark = pytest.mark.integration


@pytest.fixture
def store() -> MinioStore:
    s = MinioStore()
    try:
        if not s.client.bucket_exists(s.bucket):
            pytest.skip(f"bucket {s.bucket!r} missing; run `make up`")
    except Exception as exc:
        pytest.skip(f"MinIO not reachable ({type(exc).__name__}); run `make up`")
    return s


def test_put_get_exists(store: MinioStore) -> None:
    key = f"_tests/{uuid.uuid4()}.html"
    assert not store.exists(key)
    store.put(key, "Lãi suất".encode(), "text/html")
    assert store.exists(key)
    assert store.get(key) == "Lãi suất".encode()
    stat = store.client.stat_object(store.bucket, key)
    assert stat.content_type == "text/html"
