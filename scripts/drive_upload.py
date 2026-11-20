"""Uploads a big file to a Google Drive (or YouTube) resumable upload link, in pieces, with resume.

usage: python drive_upload.py FILE UPLOAD_URL OUT_JSON
  - sends 64 MB pieces; after each piece Google answers 308 + "Range: bytes=0-N" (how much it has)
  - if a piece fails (network blip, 5xx, rate limit), it asks Google how much arrived and carries on from there
  - writes Google's final answer (the file info, with "id") to OUT_JSON
exit 0 on success; 1 with Google's reason printed if it really cannot upload (e.g. the Drive is full).
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

CHUNK = 64 * 1024 * 1024  # must be a multiple of 256 KB


def put(url, data, headers, timeout=600):
    req = urllib.request.Request(url, data=data, method="PUT", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read()


def received(headers):
    rng = {k.lower(): v for k, v in headers.items()}.get("range", "")
    if rng.startswith("bytes=") and "-" in rng:
        return int(rng.split("-")[-1]) + 1
    return 0


def main():
    path, url, out = sys.argv[1:4]
    size = os.path.getsize(path)
    off, fails = 0, 0
    with open(path, "rb") as f:
        while True:
            if off >= size:
                break
            f.seek(off)
            data = f.read(CHUNK)
            end = off + len(data)
            try:
                code, hdr, body = put(url, data, {"Content-Type": "video/mp4", "Content-Length": str(len(data)),
                                                  "Content-Range": f"bytes {off}-{end - 1}/{size}"})
            except Exception as e:  # noqa: BLE001 - network blip: ask Google what it has
                code, hdr, body = 0, {}, str(e).encode()
            if code in (200, 201):
                open(out, "wb").write(body)
                print(f"Uploaded all {size / 1048576:.0f} MB")
                return
            if code == 308:
                off = received(hdr)
                fails = 0
                print(f"  uploaded {off / 1048576:.0f} of {size / 1048576:.0f} MB")
                continue
            fails += 1
            reason = body[:600].decode("utf-8", "replace")
            print(f"Drive answered {code}: {reason}")
            if code in (400, 401, 403, 404) and "rateLimit" not in reason and "userRateLimit" not in reason:
                if "storageQuota" in reason:
                    print("::error::Your Google Drive is full. Delete old raw videos and try again.")
                else:
                    print(f"::error::Google Drive refused the upload ({code}): {reason[:300]}")
                sys.exit(1)
            if fails > 8:
                print("::error::Google Drive upload kept failing.")
                sys.exit(1)
            time.sleep(min(60, 5 * fails))
            # Ask how much Google already has, then resume from there.
            try:
                c2, h2, b2 = put(url, b"", {"Content-Length": "0", "Content-Range": f"bytes */{size}"}, timeout=60)
                if c2 in (200, 201):
                    open(out, "wb").write(b2)
                    print("Upload was already complete")
                    return
                if c2 == 308:
                    off = received(h2)
            except Exception:  # noqa: BLE001
                pass
    # Size 0 or loop ended without a final answer: ask once more.
    c2, h2, b2 = put(url, b"", {"Content-Length": "0", "Content-Range": f"bytes */{size}"}, timeout=60)
    if c2 in (200, 201):
        open(out, "wb").write(b2)
        return
    print(f"::error::Upload did not finish ({c2}).")
    sys.exit(1)


if __name__ == "__main__":
    main()
