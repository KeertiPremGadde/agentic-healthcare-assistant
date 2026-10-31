"""Download the latest MedlinePlus Health Topics XML into data/raw/medlineplus/ (git-ignored).

    uv run python scripts/fetch_medlineplus.py

Polite by design: one page + one file, identifying User-Agent, skipped if already downloaded.
Content is a US federal work (public domain); NLM asks that MedlinePlus is acknowledged.
"""

import io
import re
import urllib.request
import zipfile
from pathlib import Path

INDEX_URL = "https://medlineplus.gov/xml.html"
BASE_URL = "https://medlineplus.gov/"
USER_AGENT = (
    "MedAgent-portfolio/0.2 (+https://github.com/KeertiPremGadde/agentic-healthcare-assistant)"
)
DEST = Path("data/raw/medlineplus")


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        data: bytes = response.read()
    return data


def main() -> None:
    index = _get(INDEX_URL).decode()
    links = sorted(set(re.findall(r"xml/mplus_topics_compressed_\d{4}-\d{2}-\d{2}\.zip", index)))
    if not links:
        raise SystemExit("Could not find a topics file on the MedlinePlus XML page.")
    latest = links[-1]
    xml_name = latest.split("/")[-1].replace("_compressed", "").replace(".zip", ".xml")
    target = DEST / xml_name
    if target.exists():
        print(f"Already downloaded: {target}")
        return
    DEST.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {latest} ...")
    with zipfile.ZipFile(io.BytesIO(_get(BASE_URL + latest))) as archive:
        archive.extractall(DEST)
    print(f"Saved {target}")


if __name__ == "__main__":
    main()
