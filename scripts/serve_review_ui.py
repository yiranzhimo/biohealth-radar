#!/usr/bin/env python3
"""Serve the local radar UI with a localhost-only candidate review write-back API."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from .review_company_candidates import MANUAL_DECISIONS, candidate_input_hash
except ImportError:
    from review_company_candidates import MANUAL_DECISIONS, candidate_input_hash


MAX_REQUEST_BYTES = 16_384
PRIVATE_PATH_PREFIXES = (
    "/.git",
    "/.github",
    "/.env",
    "/data/raw",
    "/data/company_candidate_overrides.json",
    "/scripts",
    "/tests",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve BioHealth Radar with local review controls.")
    parser.add_argument("--bind", default="127.0.0.1", choices=["127.0.0.1", "localhost"])
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reviewer", default=os.environ.get("BHR_REVIEWER", "local-reviewer"))
    parser.add_argument("--root", default=".")
    return parser.parse_args()


def load_json(path: Path, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists() and fallback is not None:
        return fallback
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def find_candidate(discovery_payload: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    for candidate in discovery_payload.get("candidates", []):
        if candidate.get("id") == candidate_id:
            return candidate
    raise ValueError(f"Unknown candidate ID: {candidate_id}")


def build_override(
    candidate: dict[str, Any],
    *,
    decision: str,
    reviewer: str,
    reason: str,
    target_company_id: str | None = None,
    evidence_urls: list[str] | None = None,
    reviewed_at: str | None = None,
) -> dict[str, Any]:
    if decision not in MANUAL_DECISIONS:
        raise ValueError(f"Invalid decision: {decision}")
    if decision == "merged" and not target_company_id:
        raise ValueError("Merged decisions require targetCompanyId")
    if not reviewer.strip():
        raise ValueError("Reviewer is required")
    if not reason.strip():
        raise ValueError("Review reason is required")
    urls = []
    for value in evidence_urls or []:
        parsed = urlparse(str(value))
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("Evidence URLs must be absolute HTTPS URLs")
        urls.append(str(value))
    return {
        "candidateId": candidate["id"],
        "candidateInputHash": candidate_input_hash(candidate),
        "decision": decision,
        "reviewer": reviewer.strip(),
        "reviewedAt": reviewed_at or dt.date.today().isoformat(),
        "reason": reason.strip(),
        "targetCompanyId": target_company_id or None,
        "evidenceUrls": sorted(set(urls)),
    }


def upsert_override(payload: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    overrides = [
        item for item in payload.get("overrides", []) if item.get("candidateId") != override["candidateId"]
    ]
    overrides.append(override)
    overrides.sort(key=lambda item: item["candidateId"])
    return {
        "schemaVersion": "1.0",
        "kind": "company_candidate_review_overrides",
        "overrides": overrides,
    }


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def run_rebuild(root: Path) -> list[str]:
    commands = [
        [sys.executable, "scripts/review_company_candidates.py"],
        [sys.executable, "scripts/build_company_intelligence.py"],
        [sys.executable, "scripts/validate_data.py"],
    ]
    output = []
    for command in commands:
        result = subprocess.run(
            command,
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output.extend(line for line in (result.stdout + result.stderr).splitlines() if line)
        if result.returncode:
            raise RuntimeError(f"{' '.join(command)} failed: {' | '.join(output[-4:])}")
    return output


class ReviewRequestHandler(SimpleHTTPRequestHandler):
    server_version = "BioHealthRadarReview/1.0"

    def __init__(self, *args: Any, directory: str, reviewer: str, **kwargs: Any) -> None:
        self.repo_root = Path(directory).resolve()
        self.reviewer = reviewer
        super().__init__(*args, directory=str(self.repo_root), **kwargs)

    def send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self) -> None:
        # Review actions rebuild browser assets immediately; never reuse a pre-review copy.
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def allowed_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        parsed = urlparse(origin)
        return (
            parsed.scheme == "http"
            and parsed.hostname in {"127.0.0.1", "localhost"}
            and parsed.netloc == self.headers.get("Host")
        )

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/review-capabilities":
            self.send_json(
                HTTPStatus.OK,
                {
                    "enabled": True,
                    "reviewer": self.reviewer,
                    "decisions": sorted(MANUAL_DECISIONS),
                },
            )
            return
        if any(path.startswith(prefix) for prefix in PRIVATE_PATH_PREFIXES):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/candidate-review":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not self.allowed_origin():
            self.send_json(HTTPStatus.FORBIDDEN, {"error": "Only localhost origins may submit reviews."})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
                raise ValueError("Invalid request size")
            request_payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            if not isinstance(request_payload, dict):
                raise ValueError("Request body must be a JSON object")
            discovery = load_json(self.repo_root / "data/raw/company_discovery_latest.json")
            candidate = find_candidate(discovery, str(request_payload.get("candidateId") or ""))
            target_company_id = str(request_payload.get("targetCompanyId") or "").strip() or None
            if target_company_id:
                companies = json.loads((self.repo_root / "data/companies.json").read_text(encoding="utf-8"))
                company_items = companies if isinstance(companies, list) else companies.get("companies", [])
                if target_company_id not in {item.get("id") for item in company_items}:
                    raise ValueError(f"Unknown target company ID: {target_company_id}")
            override = build_override(
                candidate,
                decision=str(request_payload.get("decision") or ""),
                reviewer=self.reviewer,
                reason=str(request_payload.get("reason") or ""),
                target_company_id=target_company_id,
                evidence_urls=request_payload.get("evidenceUrls") or [],
            )
            override_path = self.repo_root / "data/company_candidate_overrides.json"
            previous_text = override_path.read_text(encoding="utf-8") if override_path.exists() else None
            override_payload = load_json(
                override_path,
                {"schemaVersion": "1.0", "kind": "company_candidate_review_overrides", "overrides": []},
            )
            atomic_write_json(override_path, upsert_override(override_payload, override))
            try:
                rebuild_output = run_rebuild(self.repo_root)
            except Exception:
                if previous_text is None:
                    override_path.unlink(missing_ok=True)
                else:
                    override_path.write_text(previous_text, encoding="utf-8")
                run_rebuild(self.repo_root)
                raise
            reviews = load_json(self.repo_root / "data/raw/company_candidate_reviews_latest.json")
            self.send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "candidateId": candidate["id"],
                    "decision": override["decision"],
                    "summary": reviews.get("summary", {}),
                    "rebuild": rebuild_output,
                },
            )
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    if not (root / "index.html").exists() or not (root / "data/companies.json").exists():
        raise SystemExit(f"{root} does not look like the BioHealth Radar repository root")
    handler = partial(ReviewRequestHandler, directory=str(root), reviewer=args.reviewer)
    server = ThreadingHTTPServer((args.bind, args.port), handler)
    print(f"BioHealth Radar review UI: http://{args.bind}:{args.port}/")
    print(f"Reviewer: {args.reviewer}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
