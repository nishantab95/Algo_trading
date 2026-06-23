from __future__ import annotations


def chunk_text(text: str, max_chars: int = 1800) -> list[str]:
    paragraphs = [part.strip() for part in text.replace("\r\n", "\n").split("\n\n") if part.strip()]
    chunks: list[str] = []; current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip()
        if current and len(candidate) > max_chars:
            chunks.append(current); current = paragraph
        else: current = candidate
    if current: chunks.append(current)
    return chunks or ([text.strip()] if text.strip() else [])
