#!/usr/bin/env python3
"""Verify a downloaded release asset against every checksum source that is available, and require them to agree.

  verify_download.py FILE --name ASSET [--pin SHA256] [--github OWNER/REPO TAG] [--sums-url URL]

Sources:  pin                  SHA-256 recorded in setup.sh
          github-release-page  digest GitHub computed when the asset was uploaded (release page "expanded assets" HTML; no API rate limit)
          upstream-sha256sums  the maintainer's own sha256sums.txt (Kron4ek/Wine-Builds publishes one)
Exit codes: 0 verified (>=1 source, all agree, file matches) | 1 mismatch or sources disagree | 3 no source available (unverified)
"""
import argparse, hashlib, re, sys, urllib.parse, urllib.request

UA = {"User-Agent": "winapp-linuxvm-e2e-skill-setup"}

def fetch(url, timeout=30):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def github_page_digest(repo, tag, name):
    html = fetch(f"https://github.com/{repo}/releases/expanded_assets/{tag}")
    for item in re.split(r"(?=<li\b)", html):
        m = re.search(r'href="[^"]*/releases/download/[^"]*/([^"/]+)"', item)
        if m and urllib.parse.unquote(m.group(1)) == name:
            d = re.findall(r"sha256:([0-9a-f]{64})", item)
            return d[0] if d else None
    return None

def sums_digest(url, name):
    import os.path
    for line in fetch(url).splitlines():
        m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", line)
        if m and os.path.basename(m.group(2)) == os.path.basename(name):
            return m.group(1).lower()
    return None

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("file"); ap.add_argument("--name", required=True)
    ap.add_argument("--pin"); ap.add_argument("--github", nargs=2, metavar=("OWNER/REPO", "TAG")); ap.add_argument("--sums-url")
    a = ap.parse_args()
    sources = {}
    if a.pin: sources["pin"] = a.pin.lower()
    if a.github:
        try:
            d = github_page_digest(a.github[0], a.github[1], a.name)
            if d: sources["github-release-page"] = d
            else: print(f"note: GitHub release page shows no digest for {a.name}", file=sys.stderr)
        except Exception as ex:
            print(f"note: GitHub release page unavailable ({ex})", file=sys.stderr)
    if a.sums_url:
        try:
            d = sums_digest(a.sums_url, a.name)
            if d: sources["upstream-sha256sums"] = d
            else: print(f"note: {a.sums_url} has no entry for {a.name}", file=sys.stderr)
        except Exception as ex:
            print(f"note: upstream sha256sums unavailable ({ex})", file=sys.stderr)
    if not sources:
        print(f"NO CHECKSUM SOURCE for {a.name} - download is UNVERIFIED", file=sys.stderr); return 3
    if len(set(sources.values())) > 1:
        print(f"checksum sources DISAGREE for {a.name}: {sources}", file=sys.stderr); return 1
    expected = next(iter(sources.values())); actual = sha256_file(a.file)
    if actual != expected:
        print(f"SHA-256 MISMATCH for {a.name}: file {actual}, sources ({', '.join(sources)}) {expected}", file=sys.stderr); return 1
    print(f"sha256 ok: {a.name} (sources: {', '.join(sources)})"); return 0

if __name__ == "__main__":
    sys.exit(main())
