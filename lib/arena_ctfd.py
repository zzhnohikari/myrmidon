#!/usr/bin/env python3
"""
arena_ctfd — CTFd platform adapter for sapper.

CTFd is the most common self-hosted CTF platform (ctfd.io). Its player API:

    GET  /api/v1/challenges                  -> {data:[{id,name,description,value,..}]}
    POST /api/v1/challenges/attempt          {challenge_id, submission}
                                             -> {data:{status:"correct"|"incorrect"|"already_solved"}}

Auth: an account API token, sent as  Authorization: Token <token>
      (CTFd → Settings → Access Tokens; the user must be able to see the challenge.)

Config — <store>/arena.json:
    {
      "provider": "ctfd",
      "base_url": "https://ctf.example.com",
      "token": "ctfd_xxx",
      "targets": {"12": "10.0.0.5:8080"}     # optional: code -> attack address
    }

Notes
  * CTFd itself has no containers. If your event runs a container plugin, put the
    address in `targets` (or in the challenge description); otherwise the graph
    has no target and auto can only reason, not attack.
  * `unique_code` is the CTFd challenge **id** (string).
  * Solved state comes from `solved_by_me` when the API exposes it; otherwise
    from /api/v1/challenges/<id>/solves if available.

Standard library only.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

ARENA_FILE = "arena.json"


class ArenaError(Exception):
    def __init__(self, message: str, *, code: str | None = None,
                 status: int | None = None, detail=None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.detail = detail

    def __str__(self) -> str:  # pragma: no cover
        return self.args[0] if self.args else "arena error"


class ArenaClient:
    def __init__(self, base_url: str, token: str, targets: dict | None = None,
                 timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.targets = {str(k): str(v) for k, v in (targets or {}).items()}
        self.timeout = timeout

    # ---- construction -----------------------------------------------------
    @classmethod
    def config_path(cls, store_root: Path | None = None) -> Path:
        return Path(store_root or Path.cwd()) / ARENA_FILE

    @classmethod
    def load(cls, store_root: Path | None = None) -> "ArenaClient":
        root = Path(store_root or Path.cwd())
        path = root / ARENA_FILE
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ArenaError(f"找不到 {path}（provider=ctfd 需要它）") from exc
        except json.JSONDecodeError as exc:
            raise ArenaError(f"{path} 不是合法 JSON: {exc}") from exc
        base = str(cfg.get("base_url") or "").strip()
        token = str(cfg.get("token") or os.environ.get("CTFD_TOKEN") or "").strip()
        if not base or not token:
            raise ArenaError("arena.json 需要 base_url 与 token（CTFd 访问令牌）")
        return cls(base, token, cfg.get("targets"))

    @classmethod
    def write_template(cls, store_root: Path) -> Path:
        path = Path(store_root) / ARENA_FILE
        path.write_text(json.dumps({
            "provider": "ctfd",
            "base_url": "https://your-ctfd.example.com",
            "token": "ctfd_access_token_here",
            "targets": {},
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    # ---- http -------------------------------------------------------------
    def _request(self, method: str, path: str, payload: dict | None = None):
        url = self.base_url + path
        data = None
        headers = {"Authorization": f"Token {self.token}",
                   "Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:300]
            raise ArenaError(f"CTFd {method} {path} -> HTTP {exc.code}: {body}",
                             status=exc.code) from exc
        except urllib.error.URLError as exc:
            raise ArenaError(f"CTFd 连接失败 {url}: {exc.reason}") from exc
        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise ArenaError(f"CTFd 返回非 JSON: {raw[:200]}") from exc

    # ---- contract ---------------------------------------------------------
    def list_challenges(self) -> list[dict]:
        reply = self._request("GET", "/api/v1/challenges")
        data = reply.get("data") if isinstance(reply, dict) else None
        items = data if isinstance(data, list) else []
        out = []
        for c in items:
            if not isinstance(c, dict):
                continue
            try:
                cid = str(int(c.get("id")))
            except (TypeError, ValueError):
                continue
            target = self.targets.get(cid)
            out.append({
                "unique_code": cid,
                "description": f"{c.get('name','')} — {c.get('description','')}".strip(" —"),
                "difficulty": c.get("category") or "unknown",
                "level": c.get("category") or "",
                "total_score": int(c.get("value") or 0),
                "flag_count": 1,
                "correct_flag_count": 1 if c.get("solved_by_me") else 0,
                "is_completed": bool(c.get("solved_by_me")),
                "container_status": "available" if target else "stopped",
                "container_addr": [target] if target else [],
            })
        return out

    def start_challenge(self, unique_code: str) -> dict:
        # CTFd: nothing to start; the address must come from `targets`.
        target = self.targets.get(str(unique_code))
        return {"unique_code": unique_code,
                "container_addr": [target] if target else []}

    def get_hint(self, unique_code: str) -> dict:
        try:
            reply = self._request("GET", f"/api/v1/challenges/{int(unique_code)}/hints")
        except ArenaError:
            return {"unique_code": unique_code, "hint": None}
        data = reply.get("data", reply) if isinstance(reply, dict) else reply
        hints = []
        if isinstance(data, list):
            for h in data:
                if isinstance(h, dict):
                    if h.get("content"):
                        hints.append(str(h["content"]))
                    elif not h.get("locked") and h.get("cost", 0) == 0:
                        pass
        return {"unique_code": unique_code, "hint": "\n".join(hints) or None}

    def submit_flag(self, unique_code: str, flag: str) -> dict:
        reply = self._request("POST", "/api/v1/challenges/attempt", {
            "challenge_id": int(unique_code), "submission": flag,
        })
        data = (reply.get("data") if isinstance(reply, dict) else {}) or {}
        status = str(data.get("status") or "").lower()
        if status == "already_solved":
            raise ArenaError("flag 已经提交过（already_solved）", code="duplicate", status=409)
        correct = status == "correct"
        return {
            "correct": correct,
            "awarded": 0 if not correct else int(data.get("value") or 0),
            "cumulative_score": 0,
            "correct_flag_count": 1 if correct else 0,
            "total_flag_count": 1,
            "matched_flag_index": 0 if correct else None,
            "raw": data,
        }

    def close_challenge(self, unique_code: str) -> dict:
        return {"unique_code": unique_code, "closed": True}


import os  # noqa: E402  (kept at the bottom to keep the contract section readable)
