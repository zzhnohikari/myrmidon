#!/usr/bin/env python3
"""
arena_local — offline competition provider for sapper.

Use when the "platform" hands you the challenge list (and their flags) as
files instead of an HTTP API — e.g. an on-site CTF, a take-home benchmark, or
a rehearsal. Everything lives next to the graph:

    <store>/arena.json
    {
      "provider": "local",
      "challenges": [
        {"unique_code": "q1",
         "description": "公司官网存在 SQL 注入…",
         "target": "10.0.0.5:8080",           # optional: what auto should attack
         "flag": "flag{example}",             # exact match (case-insensitive)
         "flag_sha256": "…",                  # OR a hash, if you must not store it
         "score": 100,
         "difficulty": "easy",
         "hint": "看看 login.php"}
      ]
    }

Progress is kept in <store>/local_state.json so a restart never re-submits.

Implements the same ArenaClient contract as arena.py:
    list_challenges / start_challenge / get_hint / submit_flag / close_challenge
Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

ARENA_FILE = "arena.json"
STATE_FILE = "local_state.json"


class ArenaError(Exception):
    def __init__(self, message: str, *, code: str | None = None,
                 status: int | None = None, detail=None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.detail = detail

    def __str__(self) -> str:  # pragma: no cover - message passthrough
        return self.args[0] if self.args else "arena error"


class ArenaClient:
    """A file-backed 'platform': no network, deterministic, testable."""

    def __init__(self, store_root: Path):
        self.root = Path(store_root)
        self.config_path = self.root / ARENA_FILE
        self.state_path = self.root / STATE_FILE
        try:
            cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ArenaError(f"找不到 {self.config_path}（provider=local 需要它）") from exc
        except json.JSONDecodeError as exc:
            raise ArenaError(f"{self.config_path} 不是合法 JSON: {exc}") from exc
        if not isinstance(cfg, dict):
            raise ArenaError(f"{self.config_path} 必须是对象")
        self.cfg = cfg
        self.challenges = [c for c in (cfg.get("challenges") or []) if isinstance(c, dict)]
        self._by_code = {str(c.get("unique_code")): c for c in self.challenges}
        self.base_url = "local"

    # ---- construction -----------------------------------------------------
    @classmethod
    def config_path_for(cls, store_root: Path) -> Path:
        return Path(store_root) / ARENA_FILE

    @classmethod
    def config_path(cls, store_root: Path | None = None) -> Path:
        return cls.config_path_for(store_root or Path.cwd())

    @classmethod
    def load(cls, store_root: Path | None = None) -> "ArenaClient":
        return cls(cls._resolve_root(store_root or Path.cwd()))

    @classmethod
    def _resolve_root(cls, root: Path) -> Path:
        """bench hands us a per-challenge store; the config lives at the run
        root, so walk up until an arena.json with challenges[] is found."""
        root = Path(root)
        for cand in (root, root.parent.parent / ".sapper", Path.cwd(), Path.cwd() / ".sapper"):
            cfg = cand / ARENA_FILE
            try:
                data = json.loads(cfg.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and isinstance(data.get("challenges"), list):
                return cand
        return root

    @classmethod
    def write_template(cls, store_root: Path) -> Path:
        path = cls.config_path_for(store_root)
        template = {
            "provider": "local",
            "challenges": [
                {
                    "unique_code": "q1",
                    "description": "示例题目：目标是一个登录页，找找 SQL 注入",
                    "target": "10.0.0.5:8080",
                    "flag": "flag{change-me}",
                    "score": 100,
                    "difficulty": "easy",
                    "hint": "先看 login.php",
                }
            ],
        }
        path.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    # ---- state ------------------------------------------------------------
    def _state(self) -> dict:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, state: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                                   encoding="utf-8")

    # ---- contract ---------------------------------------------------------
    def list_challenges(self) -> list[dict]:
        state = self._state()
        out = []
        for c in self.challenges:
            code = str(c.get("unique_code"))
            solved = bool((state.get(code) or {}).get("solved"))
            out.append({
                "unique_code": code,
                "description": c.get("description") or "",
                "difficulty": c.get("difficulty") or "unknown",
                "level": c.get("level") or c.get("difficulty") or "",
                "total_score": int(c.get("score") or 100),
                "flag_count": 1,
                "correct_flag_count": 1 if solved else 0,
                "is_completed": solved,
                "container_status": "available" if c.get("target") else "stopped",
                "container_addr": [c["target"]] if c.get("target") else [],
            })
        return out

    def start_challenge(self, unique_code: str) -> dict:
        ch = self._by_code.get(str(unique_code))
        if not ch:
            raise ArenaError(f"没有这道题: {unique_code}", code="challenge_not_found",
                             status=404)
        target = ch.get("target")
        return {"unique_code": unique_code,
                "container_addr": [target] if target else []}

    def get_hint(self, unique_code: str) -> dict:
        ch = self._by_code.get(str(unique_code)) or {}
        return {"unique_code": unique_code, "hint": ch.get("hint")}

    def submit_flag(self, unique_code: str, flag: str) -> dict:
        code = str(unique_code)
        ch = self._by_code.get(code)
        if not ch:
            raise ArenaError(f"没有这道题: {code}", code="challenge_not_found", status=404)
        state = self._state()
        rec = state.setdefault(code, {"solved": False})
        if rec.get("solved"):
            raise ArenaError("flag_index=0 already correctly submitted",
                             code="duplicate", status=409)
        given = (flag or "").strip()
        expected = ch.get("flag")
        sha = ch.get("flag_sha256")
        ok = False
        if expected:
            ok = given.lower() == str(expected).strip().lower()
        elif sha:
            ok = hashlib.sha256(given.encode("utf-8")).hexdigest().lower() == str(sha).lower()
        if not ok:
            rec["attempts"] = int(rec.get("attempts") or 0) + 1
            self._save(state)
            return {"correct": False, "awarded": 0, "cumulative_score": 0,
                    "correct_flag_count": 0, "total_flag_count": 1,
                    "matched_flag_index": None}
        rec.update({"solved": True, "flag": given})
        self._save(state)
        score = int(ch.get("score") or 100)
        return {"correct": True, "awarded": score, "cumulative_score": score,
                "correct_flag_count": 1, "total_flag_count": 1,
                "matched_flag_index": 0}

    def close_challenge(self, unique_code: str) -> dict:
        return {"unique_code": unique_code, "closed": True}
