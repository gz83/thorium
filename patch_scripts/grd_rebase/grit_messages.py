# Copyright (c) 2026 Alex313031 and gz83.
"""Read message declarations and calculate Chromium GRIT translation IDs."""

import hashlib
import html
import re

MESSAGE_RE = re.compile(
    r"<message\b((?:[^>\"']+|\"[^\"]*\"|'[^']*')*)>"
    r"(.*?)</message>",
    re.DOTALL,
)
MESSAGE_NAME_RE = re.compile(r"\bname\s*=\s*\"([^\"]+)\"")
MEANING_RE = re.compile(r"\bmeaning=\"([^\"]*)\"")
GRIT_USE_NAME_FOR_ID_RE = re.compile(r'\buse_name_for_id="true"')
GRIT_PH_BLOCK_RE = re.compile(
    r"<ph\b(?=[^>]*\bname=\"([^\"]+)\")[^>]*>.*?</ph>",
    re.DOTALL,
)
GRIT_PH_SELF_CLOSING_RE = re.compile(
    r"<ph\b(?=[^>]*\bname=\"([^\"]+)\")[^>]*/>"
)
GRIT_EX_BLOCK_RE = re.compile(r"<ex\b[^>]*>.*?</ex>", re.DOTALL)
MARKUP_TAG_RE = re.compile(r"<[^>]+>")


def _grit_fingerprint(text: str) -> int:
    digest = hashlib.md5(
        text.encode("utf-8"),
        usedforsecurity=False,
    )
    value = int(digest.hexdigest()[:16], 16)
    if value & 0x8000000000000000:
        value = -((~value & 0xFFFFFFFFFFFFFFFF) + 1)
    return value


def text_to_id(text: str, meaning: str = "") -> str:
    value = _grit_fingerprint(text)
    if meaning:
        value = _grit_fingerprint(meaning) + (value << 1) + (1 if value < 0 else 0)
    return str(value & 0x7FFFFFFFFFFFFFFF)


def message_block_to_id(message_block: str) -> str:
    """Calculate Chromium GRIT's translation ID for one message block."""
    match = MESSAGE_RE.fullmatch(message_block.strip())
    if not match:
        raise ValueError("not a complete GRD/GRDP <message> block")
    attrs, body = match.groups()
    name_match = MESSAGE_NAME_RE.search(attrs)
    if not name_match:
        raise ValueError("GRD/GRDP <message> block has no name attribute")
    message_name = name_match.group(1)
    if GRIT_USE_NAME_FOR_ID_RE.search(attrs):
        return message_name
    body = GRIT_PH_BLOCK_RE.sub(lambda item: item.group(1).upper(), body)
    body = GRIT_PH_SELF_CLOSING_RE.sub(
        lambda item: item.group(1).upper(),
        body,
    )
    body = GRIT_EX_BLOCK_RE.sub("", body)
    body = html.unescape(MARKUP_TAG_RE.sub("", body)).strip()
    if body.startswith("'''") and body.endswith("'''"):
        body = body[3:-3].strip()
    meaning_match = MEANING_RE.search(attrs)
    return text_to_id(body, html.unescape(meaning_match.group(1)) if meaning_match else "")
