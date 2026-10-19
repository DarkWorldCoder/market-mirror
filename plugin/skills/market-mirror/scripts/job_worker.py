#!/usr/bin/env python3
"""Detached MCP job worker that persists a terminal status after server restarts."""

import json
import os
import subprocess
import sys
import time


def write(path, data):
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(temp, path)


def main():
    mm, meta_path, out_path, log_path, *args = sys.argv[1:]
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    try:
        with open(out_path, "w", encoding="utf-8") as out, open(log_path, "w", encoding="utf-8") as log:
            code = subprocess.run(["bash", mm, *args], stdout=out, stderr=log).returncode
    except Exception as e:
        with open(log_path, "a", encoding="utf-8") as log:
            log.write(f"job worker failed: {type(e).__name__}: {e}\n")
        code = 1
    meta.update({"status": "done" if code == 0 else "failed", "exit_code": code,
                 "finished": time.time(), "elapsed_s": round(time.time() - meta["started"], 2)})
    write(meta_path, meta)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
