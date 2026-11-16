"""Render LINE message JSON as plain terminal text."""

from __future__ import annotations

from typing import Any


def _walk(node: Any, texts: list[str], buttons: list[str]) -> None:
    if isinstance(node, dict):
        if node.get("type") == "text" and "text" in node:
            texts.append(node["text"])
        if node.get("type") == "button":
            buttons.append(node["action"]["label"])
        for v in node.values():
            _walk(v, texts, buttons)
    elif isinstance(node, list):
        for v in node:
            _walk(v, texts, buttons)


def render(msg: dict[str, Any]) -> str:
    if msg["type"] == "text":
        out = msg["text"]
        items = msg.get("quickReply", {}).get("items", [])
        if items:
            out += "\n" + " ".join(f"[{i['action']['label']}]" for i in items)
        return out
    texts: list[str] = []
    buttons: list[str] = []
    _walk(msg["contents"], texts, buttons)
    return "\n".join(texts) + ("\n" + " ".join(f"[{b}]" for b in buttons) if buttons else "")
