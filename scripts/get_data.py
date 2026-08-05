"""Download and unpack the MAY input data.

Runs on Windows, macOS and Linux using only the standard library.

    python scripts/get_data.py            # fetch into ./data
    python scripts/get_data.py --force    # overwrite an existing ./data
"""

import argparse
import base64
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

DATA_RELEASE = "data_may.zip"
BASE_URL = "https://june.phyip3.dur.ac.uk/downloads/"
USERNAME = "access"
PASSWORD = "d0wn10@d$"

REPO_ROOT = Path(__file__).resolve().parent.parent


def _human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def download(url, dest):
    """Stream the archive to dest, reporting progress on one rewritten line."""
    credentials = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
    request = urllib.request.Request(
        url, headers={"Authorization": f"Basic {credentials}"}
    )

    with urllib.request.urlopen(request, timeout=60) as response:
        total = int(response.headers.get("Content-Length", 0))
        print(f"Downloading {url}" + (f" ({_human(total)})" if total else ""))

        done = 0
        with open(dest, "wb") as handle:
            while chunk := response.read(1 << 20):
                handle.write(chunk)
                done += len(chunk)
                if total:
                    pct = done * 100 / total
                    print(f"\r  {_human(done)} / {_human(total)}  ({pct:.0f}%)",
                          end="", flush=True)
                else:
                    print(f"\r  {_human(done)}", end="", flush=True)
        print()

    if total and done != total:
        raise RuntimeError(
            f"Download truncated: got {done} bytes, expected {total}. "
            "Re-run to try again."
        )


def extract(archive, target_root):
    """Unpack the archive, refusing any member that escapes target_root."""
    with zipfile.ZipFile(archive) as zf:
        for member in zf.namelist():
            resolved = (target_root / member).resolve()
            if not resolved.is_relative_to(target_root):
                raise RuntimeError(f"Refusing to extract outside the repo: {member}")
        print(f"Extracting {len(zf.namelist())} entries into {target_root}")
        zf.extractall(target_root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing data/ directory",
    )
    args = parser.parse_args()

    data_dir = REPO_ROOT / "data"
    if data_dir.exists() and any(data_dir.iterdir()) and not args.force:
        print(
            f"{data_dir} already exists and is not empty.\n"
            "Re-run with --force to overwrite it, or move it aside first.",
            file=sys.stderr,
        )
        return 1

    free = shutil.disk_usage(REPO_ROOT).free
    if free < 2 * 1024**3:
        print(f"Warning: only {_human(free)} free on this disk.", file=sys.stderr)

    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / DATA_RELEASE
        try:
            download(BASE_URL + DATA_RELEASE, archive)
        except urllib.error.HTTPError as exc:
            print(f"\nServer returned {exc.code} {exc.reason}.", file=sys.stderr)
            return 1
        except urllib.error.URLError as exc:
            print(f"\nCould not reach the data server: {exc.reason}", file=sys.stderr)
            return 1

        extract(archive, REPO_ROOT)

    if not data_dir.is_dir():
        print(
            "The archive unpacked, but no data/ directory appeared. "
            "Check the archive layout.",
            file=sys.stderr,
        )
        return 1

    print(f"Done. {data_dir} is ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
