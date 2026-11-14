"""CLI access to exactly the same approved, checkpointed web workflows."""
import argparse
import json
from pathlib import Path
import sys
import urllib.request
import urllib.error


def main(argv=None):
    parser = argparse.ArgumentParser(description="Manage local guided workflows. Approval always needs the estimate digest and call limit.")
    parser.add_argument("action", choices=["list", "create", "status", "estimate", "approve", "results"])
    parser.add_argument("id", nargs="?")
    parser.add_argument("--inputs", help="JSON inputs file (create)")
    parser.add_argument("--phase", choices=["prepare", "test"])
    parser.add_argument("--digest")
    parser.add_argument("--call-limit", type=int)
    parser.add_argument("--approve-calls", action="store_true")
    parser.add_argument("--retry", action="store_true")
    parser.add_argument("--port", type=int, default=5001)
    args = parser.parse_args(argv)
    token = (Path(__file__).resolve().parents[1] / "logs/setup.token").read_text().strip()
    path, method, data = "", "GET", None
    if args.action == "create":
        if not args.inputs:
            parser.error("create requires --inputs FILE.json")
        method, data = "POST", {"inputs": json.loads(Path(args.inputs).read_text())}
    elif args.action != "list":
        if not args.id or not __import__('re').fullmatch(r"wf_[a-f0-9]{24}", args.id):
            parser.error("supply a workflow ID returned by create or list")
        path = "/" + args.id
        if args.action in ("estimate", "approve"):
            if not args.phase:
                parser.error("choose --phase prepare or test")
            path += "/" + args.action
            method, data = "POST", {"phase": args.phase}
            if args.action == "approve":
                if not args.approve_calls or not args.digest or not args.call_limit:
                    parser.error("review estimate first; approve requires --approve-calls --digest VALUE --call-limit N")
                data.update(approved=True, digest=args.digest, call_limit=args.call_limit, retry=args.retry)
        elif args.action == "results":
            path += "/results"
    req = urllib.request.Request(f"http://127.0.0.1:{args.port}/api/workflows" + path,
                                 data=json.dumps(data).encode() if data is not None else None,
                                 headers={"X-Setup-Token": token, "Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            print(json.dumps(json.load(response), indent=2, ensure_ascii=False))
    except urllib.error.HTTPError as error:
        print(error.read().decode(), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError):
        print("Could not access the local workflows. Run ./mm app and check the inputs file.", file=sys.stderr)
        sys.exit(1)
