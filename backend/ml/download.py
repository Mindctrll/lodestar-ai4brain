"""Fetch the public datasets the models train on (docs/plan/10). Raw data stays out of the repo,
in `data/` (gitignored). Run with `make ml-data`.

- Lumosity learning data (Steyvers & Schafer 2020), https://osf.io/g9zkf/. The OSF project lists
  no licence; we use it for research and the competition only and never redistribute it.
- NCPT (Jaffe et al. 2022), https://zenodo.org/records/7249732, CC BY 4.0.
"""

import argparse
import sys
from pathlib import Path

import httpx

DATA = Path("data")
NCPT = "https://zenodo.org/api/records/7249732/files"
FILES: dict[str, str] = {
    "lumosity/gameinfo_original.csv": "https://osf.io/download/q7e8d/",
    "lumosity/gamedata_preprocessed.csv": "https://osf.io/download/tbq6s/",  # 2.6 GB
    **{f"ncpt/battery{b}_df.csv": f"{NCPT}/battery{b}_df.csv/content" for b in (17, 32)},
}
ATTEMPTS = 20


def _total(response: httpx.Response) -> int | None:
    if "content-range" in response.headers:
        return int(response.headers["content-range"].rsplit("/", 1)[1])
    length = response.headers.get("content-length")
    return int(length) if length else None


def fetch(path: str, url: str, client: httpx.Client) -> None:
    """Download with resume: large files often drop mid-way, so keep asking for the rest."""
    target = DATA / path
    if target.exists():
        print(f"ok        {path}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    total: int | None = None
    for _ in range(ATTEMPTS):
        have = part.stat().st_size if part.exists() else 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            with client.stream("GET", url, headers=headers, follow_redirects=True) as response:
                if response.status_code == 416:  # nothing left to send
                    break
                response.raise_for_status()
                total = _total(response)
                resumed = have and response.status_code == 206
                print(f"download  {path} from {have / 1e6:.0f} MB of {(total or 0) / 1e6:.0f} MB")
                with part.open("ab" if resumed else "wb") as f:
                    for chunk in response.iter_bytes(1 << 20):
                        f.write(chunk)
        except httpx.HTTPError as exc:
            print(f"retrying  {path}: {type(exc).__name__}")
            continue
        if total is not None and part.stat().st_size >= total:
            break
    else:
        raise RuntimeError(f"{path}: still incomplete after {ATTEMPTS} attempts")
    part.rename(target)
    print(f"done      {path} ({target.stat().st_size / 1e6:.0f} MB)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=["lumosity", "ncpt"], default=None)
    args = parser.parse_args(argv)
    with httpx.Client(timeout=httpx.Timeout(60.0, read=600.0)) as client:
        for path, url in FILES.items():
            if args.only is None or path.startswith(args.only):
                fetch(path, url, client)
    return 0


if __name__ == "__main__":
    sys.exit(main())
