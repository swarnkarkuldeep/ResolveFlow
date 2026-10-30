"""Guards for deployment config the runtime tests can't see (found in the M0 review)."""

import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]


def test_published_ports_bind_loopback_only() -> None:
    for name, svc in SERVICES.items():
        for port in svc.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), f"{name} publishes {port} on all interfaces"


def test_long_running_services_restart_unless_stopped() -> None:
    for name in ("db", "redis", "mailpit", "api", "worker", "beat", "web"):
        assert SERVICES[name].get("restart") == "unless-stopped", name


def test_third_party_images_are_pinned() -> None:
    for name in ("db", "redis", "mailpit"):
        image = SERVICES[name]["image"]
        assert ":" in image and not image.endswith(":latest"), f"{name} image {image} unpinned"


def test_nginx_re_resolves_api_after_container_recreate() -> None:
    conf = (ROOT / "frontend" / "nginx.conf").read_text(encoding="utf-8")
    assert "resolver 127.0.0.11" in conf
    assert not re.search(r"proxy_pass\s+http://api:8000", conf), "static upstream is cached"


def test_start_bat_pauses_before_every_failure_exit() -> None:
    lines = (ROOT / "start.bat").read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if "exit /b 1" in line:
            assert "pause" in lines[i - 1].lower() or "goto fail" in line.lower(), i + 1


def test_backend_dependencies_have_upper_bounds() -> None:
    project = tomllib.loads((ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8"))
    for dep in project["project"]["dependencies"]:
        assert "<" in dep, f"no upper bound: {dep}"
