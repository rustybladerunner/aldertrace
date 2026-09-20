"""CLI: pick | serve | gate | compact | test | leakcheck."""

from __future__ import annotations

import argparse
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _add_src() -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


def cmd_pick(args: argparse.Namespace) -> int:
    from .engine import pick
    from .ollama import OllamaBackend, OllamaError
    from .pick_payload import build_pick_payload
    from .schema import PickError, parse_request

    try:
        raw = build_pick_payload(
            from_json=args.from_json,
            state=args.state,
            instructions=args.instructions,
            option=args.option,
            qid=args.id,
            model=args.model,
        )
        req = parse_request(raw)
        result = pick(req, OllamaBackend(keep_alive=args.keep_alive))
    except PickError as e:
        print(json.dumps(e.as_dict()), file=sys.stderr)
        return 2
    except OllamaError as e:
        print(json.dumps({"code": "upstream", "message": str(e)}), file=sys.stderr)
        return 3
    print(json.dumps(result, indent=2))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .serve import serve

    httpd = serve(args.host, args.port)
    print(f"logitpick on http://{args.host}:{args.port}  POST /v1/pick", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstop", file=sys.stderr)
    return 0


def cmd_test(args: argparse.Namespace) -> int:
    _add_src()
    loader = unittest.TestLoader()
    suite = loader.discover(str(ROOT / "tests"), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def cmd_gate(args: argparse.Namespace) -> int:
    from .gate import gate
    from .ollama import OllamaBackend, OllamaError

    if args.diff == "-":
        text = sys.stdin.read()
    else:
        path = Path(args.diff)
        if not path.is_file():
            print(json.dumps({"code": "missing_diff", "message": str(path)}), file=sys.stderr)
            return 2
        text = path.read_text(encoding="utf-8")

    backend = None
    if args.with_model:
        backend = OllamaBackend(keep_alive="0")
    try:
        out = gate(text, title=args.title, body=args.body, backend=backend, model=args.model)
    except OllamaError as e:
        print(json.dumps({"code": "upstream", "message": str(e)}), file=sys.stderr)
        return 3
    print(json.dumps(out, indent=2))
    return 0 if out["verdict"] in ("merge", "nits") else 1


def cmd_compact(args: argparse.Namespace) -> int:
    from .compact import compact

    if args.trace == "-":
        raw_text = sys.stdin.read()
    else:
        path = Path(args.trace)
        if not path.is_file():
            print(json.dumps({"code": "missing_trace", "message": str(path)}), file=sys.stderr)
            return 2
        raw_text = path.read_text(encoding="utf-8")
    try:
        raw = json.loads(raw_text)
        out = compact(raw)
    except (json.JSONDecodeError, ValueError) as e:
        print(json.dumps({"code": "bad_trace", "message": str(e)}), file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2))
    return 0


def cmd_leakcheck(_args: argparse.Namespace) -> int:
    from .leakcheck import main as leak_main

    return leak_main()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="logitpick", description="Score declared options from local next-token logprobs")
    sub = p.add_subparsers(dest="cmd", required=True)

    pick_p = sub.add_parser("pick", help="score questions on stdout")
    pick_p.add_argument("--from-json", type=Path, dest="from_json", help="full request JSON (multi-field)")
    pick_p.add_argument("--state")
    pick_p.add_argument("--instructions")
    pick_p.add_argument("--option", action="append", help="id=description (repeat)")
    pick_p.add_argument("--id", default="q")
    pick_p.add_argument("--model", default="llama3.2")
    pick_p.add_argument("--keep-alive", default="0", help="Ollama keep_alive; default 0 unloads after the call")
    pick_p.set_defaults(func=cmd_pick)

    serve_p = sub.add_parser("serve", help="loopback HTTP")
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=7340)
    serve_p.set_defaults(func=cmd_serve)

    gate_p = sub.add_parser("gate", help="scan-first PR verdict; model off unless --with-model")
    gate_p.add_argument("diff", help="unified diff path, or - for stdin")
    gate_p.add_argument("--title", default="")
    gate_p.add_argument("--body", default="")
    gate_p.add_argument("--with-model", action="store_true", help="optional local Ollama yes/no; never unblocks secrets")
    gate_p.add_argument("--model", default="llama3.2")
    gate_p.set_defaults(func=cmd_gate)

    compact_p = sub.add_parser("compact", help="keep/drop tool traces; last observation per path/cmd")
    compact_p.add_argument("trace", help="JSON trace path, or - for stdin")
    compact_p.set_defaults(func=cmd_compact)

    test_p = sub.add_parser("test", help="run unittest (set LOGITPICK_LIVE=1 for Ollama)")
    test_p.set_defaults(func=cmd_test)

    leak_p = sub.add_parser("leakcheck", help="scan this folder for credential-shaped text")
    leak_p.set_defaults(func=cmd_leakcheck)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
