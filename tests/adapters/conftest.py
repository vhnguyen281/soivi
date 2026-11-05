from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def fixture_bytes(bank: str, name: str) -> bytes:
    return (FIXTURES / bank / name).read_bytes()
