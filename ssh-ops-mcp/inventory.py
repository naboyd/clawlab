"""Host inventory field helpers (tags, legacy description migration)."""

from __future__ import annotations


def parse_tags_field(raw: str) -> list[str]:
    """Parse a comma-separated tags string from a form field."""
    return [t.strip() for t in (raw or "").split(",") if t.strip()]


def normalize_tags(host: dict) -> list[str]:
    """Return deduplicated tags for a host entry (preserves order)."""
    raw = host.get("tags")
    tags: list[str] = []
    if isinstance(raw, list):
        tags = [str(t).strip() for t in raw if str(t).strip()]
    elif isinstance(raw, str) and raw.strip():
        tags = parse_tags_field(raw)

    if not tags:
        legacy = (host.get("description") or "").strip()
        if legacy:
            tags = parse_tags_field(legacy) if "," in legacy else [legacy]

    seen: set[str] = set()
    out: list[str] = []
    for tag in tags:
        key = tag.lower()
        if key not in seen:
            seen.add(key)
            out.append(tag)
    return out


def has_tag(host: dict, tag: str) -> bool:
    """Case-insensitive tag membership (includes legacy description substring)."""
    needle = tag.strip().lower()
    if not needle:
        return False
    if any(t.lower() == needle for t in normalize_tags(host)):
        return True
    legacy = (host.get("description") or "").lower()
    return needle in legacy.split() or needle in legacy
