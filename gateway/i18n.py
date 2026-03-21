"""
Internationalisation — display-layer translation for WhatsApp messages.

Only two languages for now: English (en) and Simplified Chinese (zh).
Backend stays entirely in English; translation happens just before sending.

Strategy:
- Static dict for short UI strings (button titles, list titles)
- AI translation with in-memory cache for longer body text
"""

import logging
from contextvars import ContextVar
from typing import Optional

logger = logging.getLogger(__name__)

# Current language for the active request — set in the router
current_language: ContextVar[str] = ContextVar("current_language", default="en")


def get_language() -> str:
    return current_language.get()


def set_language(lang: str):
    current_language.set(lang)


# ---------------------------------------------------------------------------
# Static translations — instant lookup, no API call
# Keys are the English string (exact match)
# ---------------------------------------------------------------------------
ZH_STATIC = {
    # Button titles
    "Facebook": "Facebook",
    "Instagram": "Instagram",
    "Generate with AI": "AI 生成",
    "Write My Own": "自己撰写",
    "Publish Now": "立即发布",
    "Edit Caption": "编辑文案",
    "Cancel": "取消",
    "Try Again": "重试",
    "Beautify with AI": "AI 美化",
    "Done — I connected": "完成 — 已连接",
    "Disconnect All": "断开全部",
    "Yes": "是",
    "No": "否",
    "Choose Plan": "选择方案",
    "Choose Pack": "选择套餐",
    "Text Only": "纯文字",
    "With Photo": "附带图片",
    "With Video": "附带视频",
    "3 posts": "3 篇帖子",
    "5 posts": "5 篇帖子",
    "7 posts": "7 篇帖子",
    "Custom": "自定义",
    "Approve All": "全部批准",
    "Edit": "编辑",
    "Discard": "放弃",
    "English": "English",
    "中文": "中文",
    "Select Length": "选择长度",
    "5 seconds": "5 秒",
    "10 seconds": "10 秒",
    "15 seconds": "15 秒",
    "20 seconds": "20 秒",
    "25 seconds": "25 秒",
    "30 seconds": "30 秒",

    # List section titles
    "Plans": "方案",
    "Credit Packs": "积分套餐",
    "Platforms": "平台",
    "Languages": "语言",

    # Common phrases in messages
    "Send *help* to see available commands.": "发送 *help* 查看可用命令。",
    "Send *post* to create your first post!": "发送 *post* 创建您的第一条帖子！",
    "Send *setup* to connect Facebook or Instagram.": "发送 *setup* 连接 Facebook 或 Instagram。",
}


def translate_static(text: str) -> str:
    """Translate a short UI string using the static dict. Returns original if not found."""
    if get_language() != "zh":
        return text
    return ZH_STATIC.get(text, text)


# ---------------------------------------------------------------------------
# AI translation with in-memory cache for body text
# ---------------------------------------------------------------------------
_translation_cache: dict[tuple[str, str], str] = {}


def translate_text(text: str) -> str:
    """Translate body text. Uses cache, falls back to AI, returns original on failure."""
    lang = get_language()
    if lang == "en":
        return text

    # Don't translate very short strings or strings that are just URLs/numbers
    stripped = text.strip()
    if not stripped or stripped.startswith("http") or stripped.replace(".", "").replace(",", "").isdigit():
        return text

    cache_key = (lang, stripped)
    if cache_key in _translation_cache:
        return _translation_cache[cache_key]

    # Try AI translation
    try:
        translated = _ai_translate(stripped, lang)
        if translated:
            _translation_cache[cache_key] = translated
            return translated
    except Exception as e:
        logger.error("Translation failed: %s", e)

    return text


def _ai_translate(text: str, target_lang: str) -> Optional[str]:
    """Use Claude to translate text."""
    from services.ai.ai_service import _call_claude

    lang_name = "Simplified Chinese" if target_lang == "zh" else "English"

    result = _call_claude(
        max_tokens=2048,
        system=(
            f"You are a translator. Translate the following text to {lang_name}. "
            "Output ONLY the translated text. Preserve all markdown formatting "
            "(bold with *, italic with _, etc). Preserve any English command words "
            "wrapped in * (like *post*, *help*, *setup*) — keep them in English. "
            "Preserve URLs, numbers, and code exactly as-is."
        ),
        messages=[{"role": "user", "content": text}],
    )
    return result


def translate_button(button: dict) -> dict:
    """Translate a button dict's title field."""
    if get_language() == "en":
        return button
    return {**button, "title": translate_static(button["title"])}


def translate_buttons(buttons: list[dict]) -> list[dict]:
    """Translate a list of button dicts."""
    if get_language() == "en":
        return buttons
    return [translate_button(b) for b in buttons]


def translate_list_sections(sections: list[dict]) -> list[dict]:
    """Translate interactive list sections (title + row titles)."""
    if get_language() == "en":
        return sections
    result = []
    for section in sections:
        new_section = {**section, "title": translate_static(section["title"])}
        if "rows" in section:
            new_rows = []
            for row in section["rows"]:
                new_row = {**row, "title": translate_static(row["title"])}
                if "description" in row:
                    new_row["description"] = translate_text(row["description"])
                new_rows.append(new_row)
            new_section["rows"] = new_rows
        result.append(new_section)
    return result
