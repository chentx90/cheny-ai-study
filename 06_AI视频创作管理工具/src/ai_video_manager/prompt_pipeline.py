from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import replace
from typing import Any

from .llm import parse_json_object
from .models import EntityCard, PromptCard


def build_prompt_cards_from_script(
    *,
    project_id: str,
    segment_id: str,
    script: str,
    entity_cards: list[EntityCard],
    split_llm_client: Any,
    write_llm_client: Any,
    split_prompt: str,
    write_prompt_renderer: Any,
    max_duration_seconds: object = 15.0,
    temperature_split: float = 0.3,
    temperature_write: float = 0.6,
    max_tokens_split: int = 100000,
    max_tokens_write: int = 100000,
) -> list[PromptCard]:
    clean_script = script.strip()
    if not clean_script:
        raise ValueError("当前集没有剧本原文，无法生成提示词")

    duration_limit = _safe_float(max_duration_seconds, fallback=15.0, minimum=3.0)
    chunks = split_script_to_chunks(
        script=clean_script,
        llm_client=split_llm_client,
        rendered_prompt=split_prompt,
        max_duration_seconds=duration_limit,
        temperature=temperature_split,
        max_tokens=max_tokens_split,
    )
    cards: list[PromptCard] = []
    for index, chunk in enumerate(chunks):
        neighbor_context = _neighbor_context_json(chunks, index)
        write_prompt = write_prompt_renderer(
            {
                "script_excerpt": chunk["script_excerpt"],
                "entity_catalog": entity_catalog_json(entity_cards),
                "max_duration_seconds": duration_limit,
                "neighbor_context": neighbor_context,
            }
        )
        written = write_prompt_for_chunk(
            chunk=chunk,
            llm_client=write_llm_client,
            rendered_prompt=write_prompt,
            max_duration_seconds=duration_limit,
            temperature=temperature_write,
            max_tokens=max_tokens_write,
        )
        order = index + 1
        title = _normalize_segment_title(order, written.get("title") or chunk.get("title"))
        prompt_text = str(written.get("prompt_text") or "").strip()
        if not prompt_text:
            raise ValueError(f"第 {order} 张提示词卡片未返回 prompt_text")
        source_text = str(chunk["script_excerpt"])
        source_start = int(chunk["source_start"])
        source_end = int(chunk["source_end"])
        duration = _bounded_duration(
            written.get("duration", chunk.get("duration")),
            fallback=duration_limit,
            limit=duration_limit,
        )
        cards.append(
            PromptCard(
                project_id=project_id,
                segment_id=segment_id,
                order=order,
                title=title,
                prompt_text=prompt_text,
                anchor_text="",
                duration=duration,
                source_text=source_text,
                source_start=source_start,
                source_end=source_end,
                source_hash=hash_prompt_card(clean_script, title, source_text, prompt_text, ""),
                status="generated",
            )
        )
    if not cards:
        raise ValueError("LLM 未返回有效提示词卡片")
    return cards


def split_script_to_chunks(
    *,
    script: str,
    llm_client: Any,
    rendered_prompt: str,
    max_duration_seconds: float = 15.0,
    temperature: float = 0.3,
    max_tokens: int = 100000,
) -> list[dict[str, object]]:
    clean_script = script.strip()
    if not clean_script:
        raise ValueError("当前集没有剧本原文，无法切分")
    prompt = rendered_prompt.strip()
    if not prompt:
        raise ValueError("提示词切分模板渲染结果为空")
    raw = llm_client.complete(
        prompt,
        temperature=temperature,
        max_tokens=_bounded_int(max_tokens, fallback=100000, minimum=1, maximum=200000),
        json_mode=True,
    )
    payload = parse_json_object(raw)
    rows = payload.get("chunks")
    if not isinstance(rows, list):
        raise ValueError("切分结果缺少 chunks 数组，请使用 JSON：{\"chunks\":[...]}")
    chunks: list[dict[str, object]] = []
    for index, item in enumerate(rows):
        if not isinstance(item, dict):
            continue
        excerpt = str(item.get("script_excerpt") or item.get("source_text") or "").strip()
        if not excerpt:
            continue
        source_text, source_start, source_end = _locate_source_text(clean_script, excerpt)
        chunks.append(
            {
                "title": _normalize_segment_title(index + 1, item.get("title")),
                "duration": _bounded_duration(
                    item.get("duration"),
                    fallback=max_duration_seconds,
                    limit=max_duration_seconds,
                ),
                "script_excerpt": source_text,
                "source_start": source_start,
                "source_end": source_end,
            }
        )
    if not chunks:
        raise ValueError("切分未返回有效 chunks，请检查模型是否按 JSON 返回")
    return chunks


def write_prompt_for_chunk(
    *,
    chunk: dict[str, object],
    llm_client: Any,
    rendered_prompt: str,
    max_duration_seconds: float = 15.0,
    temperature: float = 0.6,
    max_tokens: int = 100000,
) -> dict[str, object]:
    prompt = rendered_prompt.strip()
    if not prompt:
        raise ValueError("视频生成提示词模板渲染结果为空")
    raw = llm_client.complete(
        prompt,
        temperature=temperature,
        max_tokens=_bounded_int(max_tokens, fallback=100000, minimum=1, maximum=200000),
        json_mode=True,
    )
    payload = parse_json_object(raw)
    if "cards" in payload and isinstance(payload.get("cards"), list) and payload["cards"]:
        first = payload["cards"][0]
        if isinstance(first, dict):
            payload = first
    prompt_text = str(payload.get("prompt_text") or payload.get("prompt") or payload.get("content") or "").strip()
    if not prompt_text:
        raise ValueError("写卡结果缺少 prompt_text")
    return {
        "title": payload.get("title") or chunk.get("title") or "",
        "duration": _bounded_duration(
            payload.get("duration", chunk.get("duration")),
            fallback=max_duration_seconds,
            limit=max_duration_seconds,
        ),
        "prompt_text": prompt_text,
    }


def rerun_prompt_card_from_script(
    *,
    target_card: PromptCard,
    script: str,
    entity_cards: list[EntityCard],
    llm_client: Any,
    rendered_prompt: str,
    max_duration_seconds: object = 15.0,
    temperature: float = 0.6,
    max_tokens: int = 100000,
) -> PromptCard:
    clean_script = script.strip()
    if not clean_script and not target_card.source_text.strip():
        raise ValueError("当前集没有剧本原文，无法重跑提示词卡片")
    if target_card.locked:
        raise ValueError("提示词卡片已锁定，请先解锁后再重跑")

    duration_limit = _safe_float(max_duration_seconds or target_card.duration, fallback=15.0, minimum=3.0)
    prompt = rendered_prompt.strip()
    if not prompt:
        raise ValueError("提示词单卡重跑模板渲染结果为空")

    written = write_prompt_for_chunk(
        chunk={
            "title": target_card.title,
            "duration": target_card.duration or duration_limit,
            "script_excerpt": target_card.source_text,
        },
        llm_client=llm_client,
        rendered_prompt=prompt,
        max_duration_seconds=duration_limit,
        temperature=temperature,
        max_tokens=_bounded_int(max_tokens, fallback=100000, minimum=1, maximum=200000),
    )
    prompt_text = str(written["prompt_text"]).strip()
    title = _normalize_segment_title(target_card.order, written.get("title") or target_card.title)
    duration = _bounded_duration(written.get("duration"), fallback=duration_limit, limit=duration_limit)
    source_text = target_card.source_text
    source_start = target_card.source_start
    source_end = target_card.source_end
    if (not source_text.strip() or source_end <= source_start) and clean_script:
        source_text, source_start, source_end = _script_slice_for_card(
            clean_script,
            max(0, int(target_card.order or 1) - 1),
            max(1, int(target_card.order or 1)),
        )
    return replace(
        target_card,
        title=title,
        prompt_text=prompt_text,
        duration=duration,
        source_text=source_text,
        source_start=source_start,
        source_end=source_end,
        source_hash=hash_prompt_card(clean_script or source_text, title, source_text, prompt_text, target_card.anchor_text),
        status="generated",
        locked=False,
    )


def prompt_cards_context_json(cards: list[PromptCard], *, target_card_id: str | None = None) -> str:
    rows = []
    for card in sorted(cards, key=lambda item: item.order):
        rows.append(
            {
                "id": card.id,
                "order": card.order,
                "title": card.title,
                "locked": card.locked,
                "is_target": card.id == target_card_id,
                "source_start": card.source_start,
                "source_end": card.source_end,
                "source_text": card.source_text,
                "prompt_text": card.prompt_text,
                "anchor_text": card.anchor_text,
                "duration": card.duration,
            }
        )
    return json.dumps(rows, ensure_ascii=False, indent=2)


def prompt_card_target_json(card: PromptCard) -> str:
    return json.dumps(
        {
            "id": card.id,
            "order": card.order,
            "title": card.title,
            "source_start": card.source_start,
            "source_end": card.source_end,
            "source_text": card.source_text,
            "current_prompt_text": card.prompt_text,
            "anchor_text": card.anchor_text,
            "duration": card.duration,
        },
        ensure_ascii=False,
        indent=2,
    )


def prompt_card_with_inferred_source(card: PromptCard, script: str, card_count: int) -> PromptCard:
    if card.source_text.strip() and card.source_end > card.source_start:
        return card
    source_text, source_start, source_end = _script_slice_for_card(
        script.strip(),
        max(0, int(card.order or 1) - 1),
        max(1, int(card_count or 1)),
    )
    return replace(
        card,
        source_text=source_text,
        source_start=source_start,
        source_end=source_end,
    )


def hash_prompt_card(script: str, title: str, script_excerpt: str, prompt_text: str, anchor_text: str) -> str:
    payload = {
        "script": script,
        "title": title,
        "script_excerpt": script_excerpt,
        "prompt_text": prompt_text,
        "anchor_text": anchor_text,
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def entity_catalog_json(entity_cards: list[EntityCard]) -> str:
    rows = [
        {
            "name": card.entity_name,
            "type": card.type.value,
            "state": card.state or "",
            "tags": card.tags,
        }
        for card in entity_cards
    ]
    return json.dumps(rows, ensure_ascii=False, indent=2) if rows else "[]"


def _neighbor_context_json(chunks: list[dict[str, object]], index: int) -> str:
    rows: list[dict[str, object]] = []
    if index > 0:
        prev = chunks[index - 1]
        rows.append(
            {
                "position": "prev",
                "title": prev.get("title"),
                "script_excerpt": prev.get("script_excerpt"),
                "duration": prev.get("duration"),
            }
        )
    if index + 1 < len(chunks):
        nxt = chunks[index + 1]
        rows.append(
            {
                "position": "next",
                "title": nxt.get("title"),
                "script_excerpt": nxt.get("script_excerpt"),
                "duration": nxt.get("duration"),
            }
        )
    return json.dumps(rows, ensure_ascii=False, indent=2) if rows else "[]"


def _normalize_segment_title(order: int, raw_title: object = "") -> str:
    prefix = f"片段{order}"
    title = str(raw_title or "").strip()
    if not title or title == prefix:
        return prefix
    if title.startswith(f"{prefix} "):
        return title
    if title.startswith(prefix):
        body = title[len(prefix) :].strip()
        return f"{prefix} {body}".strip() if body else prefix
    legacy = re.match(r"^提示词卡片\s*(\d+)\s*(.*)$", title)
    if legacy:
        body = legacy.group(2).strip()
        return f"{prefix} {body}".strip() if body else prefix
    return f"{prefix} {title}".strip()


def _locate_source_text(full_script: str, source_text: str) -> tuple[str, int, int]:
    clean = source_text.strip()
    if not clean:
        return "", 0, 0
    index = full_script.find(clean)
    if index >= 0:
        return clean, index, index + len(clean)
    head = clean[: min(120, len(clean))]
    head_index = full_script.find(head) if head else -1
    if head_index >= 0:
        end = min(len(full_script), head_index + len(clean))
        return full_script[head_index:end], head_index, end
    return clean, 0, min(len(full_script), len(clean))


def _script_slice_for_card(full_script: str, card_index: int, card_count: int) -> tuple[str, int, int]:
    if not full_script:
        return "", 0, 0
    count = max(1, int(card_count or 1))
    index = min(max(0, int(card_index or 0)), count - 1)
    start = round((len(full_script) * index) / count)
    end = round((len(full_script) * (index + 1)) / count)
    if start > 0:
        previous_break = full_script.rfind("\n", 0, start)
        if previous_break >= 0:
            start = previous_break + 1
    if end < len(full_script):
        next_break = full_script.find("\n", end)
        if next_break >= 0:
            end = next_break
    return full_script[start:end].strip(), start, end


def _bounded_duration(value: object, *, fallback: float, limit: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = fallback
    return round(min(max(number, 1.0), max(3.0, float(limit or fallback))), 1)


def _bounded_int(value: object, *, fallback: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = fallback
    return min(max(number, minimum), maximum)


def _safe_float(
    value: object,
    *,
    fallback: float,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = fallback
    if not math.isfinite(number):
        number = fallback
    if minimum is not None:
        number = max(float(minimum), number)
    if maximum is not None:
        number = min(float(maximum), number)
    return number
