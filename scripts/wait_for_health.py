"""Usage: wait_for_health.py <url> <timeout_s>. Exit 0 once the URL returns HTTP 200."""

import sys
import time
import urllib.request


def main() -> int:
    url, timeout = sys.argv[1], float(sys.argv[2])
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:  # noqa: S310
                if resp.status == 200:
                    return 0
        except Exception:  # noqa: BLE001 - any failure means "not ready yet"
            pass
        time.sleep(1)
    print(f"timed out after {timeout:.0f}s waiting for {url}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
