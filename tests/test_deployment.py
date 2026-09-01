from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_render_disk_is_made_writable_before_the_api_starts() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "USER root" in dockerfile
    assert "chown -R pwuser:pwuser /var/data" in dockerfile
    assert "runuser --preserve-environment -u pwuser -- uvicorn" in dockerfile
    assert dockerfile.index("chown -R pwuser:pwuser /var/data") < dockerfile.index(
        "runuser --preserve-environment -u pwuser -- uvicorn"
    )
