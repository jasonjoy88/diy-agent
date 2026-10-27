from __future__ import annotations

import os

from langgraph.graph import END, StateGraph

from .nodes import (
    convert,
    fetch_lyrics,
    fetch_loop,
    plan_tracks,
    resolve_artist,
    upload,
    validate,
    write_manifest,
)
from .state import MusicState


def _after_plan(state: dict) -> str:
    """无待下载曲目时直接结束，避免空跑下载链；检索失败提示已由 plan_tracks 写入。"""
    if state.get("tracks"):
        return "fetch"
    return "done"


def _build() -> StateGraph:
    g = StateGraph(MusicState)
    g.add_node("resolve_artist", resolve_artist.run)
    g.add_node("plan_tracks", plan_tracks.run)
    g.add_node("fetch_loop", fetch_loop.run)
    g.add_node("convert", convert.run)
    g.add_node("validate", validate.run)
    g.add_node("fetch_lyrics", fetch_lyrics.run)
    g.add_node("write_manifest", write_manifest.run)
    g.add_node("upload", upload.run)
    g.set_entry_point("resolve_artist")
    g.add_edge("resolve_artist", "plan_tracks")
    g.add_conditional_edges("plan_tracks", _after_plan, {"fetch": "fetch_loop", "done": END})
    g.add_edge("fetch_loop", "convert")
    g.add_edge("convert", "validate")
    g.add_edge("validate", "fetch_lyrics")
    g.add_edge("fetch_lyrics", "write_manifest")
    g.add_edge("write_manifest", "upload")
    g.add_edge("upload", END)
    return g


def build_graph():
    return _build().compile()


def build_graph_with_sqlite(db_path: str):
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    import sqlite3

    from langgraph.checkpoint.sqlite import SqliteSaver

    conn = sqlite3.connect(db_path, check_same_thread=False)
    return _build().compile(checkpointer=SqliteSaver(conn))
