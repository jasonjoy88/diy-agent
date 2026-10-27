from __future__ import annotations

import json
import os
from dataclasses import asdict

from .models import DownloadResult

MANIFEST_NAME = "manifest.json"


class Manifest:
    def __init__(self, out_dir: str, artist: str):
        self.out_dir = out_dir
        self.artist = artist
        self.path = os.path.join(out_dir, MANIFEST_NAME)
        self.results: dict[str, DownloadResult] = {}

    @classmethod
    def load(cls, out_dir: str, artist: str) -> "Manifest":
        m = cls(out_dir, artist)
        if os.path.isfile(m.path):
            with open(m.path, encoding="utf-8") as f:
                data = json.load(f)
            for tid, rd in data.get("results", {}).items():
                m.results[tid] = DownloadResult(track_id=tid, **{k: v for k, v in rd.items() if k != "track_id"})
        return m

    def upsert(self, result: DownloadResult) -> None:
        self.results[result.track_id] = result

    def get(self, track_id: str) -> DownloadResult | None:
        return self.results.get(track_id)

    def todo_ids(self) -> list[str]:
        return [tid for tid, r in self.results.items() if r.status != "ok"]

    def summary(self) -> dict:
        ok = sum(1 for r in self.results.values() if r.status == "ok")
        failed = sum(1 for r in self.results.values() if r.status == "failed")
        return {"total": len(self.results), "ok": ok, "failed": failed,
                "pending": len(self.results) - ok - failed}

    def save(self) -> None:
        os.makedirs(self.out_dir, exist_ok=True)
        payload = {
            "artist": self.artist,
            "summary": self.summary(),
            "results": {tid: asdict(r) for tid, r in self.results.items()},
        }
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
