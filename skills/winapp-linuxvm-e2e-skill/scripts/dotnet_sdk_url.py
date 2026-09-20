#!/usr/bin/env python3
"""Print "<url> <sha512>" of the linux-x64 .NET SDK tarball for a channel, from Microsoft's release metadata.

  dotnet_sdk_url.py 8.0
"""
import json, sys, urllib.request

def main():
    channel = sys.argv[1]
    meta = json.load(urllib.request.urlopen(f"https://builds.dotnet.microsoft.com/dotnet/release-metadata/{channel}/releases.json", timeout=60))
    for rel in meta["releases"]:                      # newest first
        for sdk in [rel.get("sdk")] + (rel.get("sdks") or []):
            if not sdk: continue
            for f in sdk.get("files", []):
                if f["rid"] == "linux-x64" and f["name"].endswith(".tar.gz") and f.get("hash"):
                    print(f["url"], f["hash"].lower()); return 0
    print(f"no linux-x64 SDK tarball with a hash in the metadata for channel {channel}", file=sys.stderr); return 1

if __name__ == "__main__":
    sys.exit(main())
