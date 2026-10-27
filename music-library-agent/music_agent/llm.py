from __future__ import annotations

from typing import Optional

from .config import Config, CONFIG


def get_llm(config: Optional[Config] = None):
    """有 Ark key 返回 ChatOpenAI 客户端，否则返回 None（节点据此降级为规则）。"""
    cfg = config or CONFIG
    if not (cfg.ark_api_key and cfg.ark_model):
        return None
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=cfg.ark_model,
        api_key=cfg.ark_api_key,
        base_url=cfg.ark_base_url,
        temperature=0,
    )


def ask(prompt: str, config: Optional[Config] = None) -> Optional[str]:
    """向 LLM 提问并返回文本；无 LLM 时返回 None。"""
    client = get_llm(config)
    if client is None:
        return None
    try:
        resp = client.invoke(prompt)
    except Exception:  # noqa: BLE001 - LLM 调用失败也降级为规则
        return None
    return getattr(resp, "content", None) or None
