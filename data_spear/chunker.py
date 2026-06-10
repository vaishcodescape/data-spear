from __future__ import annotations

from typing import Iterator


def serialize_row(row: dict) -> str:
    # Render a row as 'column: value' lines — readable to both humans and the embedder.
    parts = []
    for k, v in row.items():
        if v is None:
            continue
        parts.append(f"{k}: {v}")
    return "\n".join(parts)


def chunk_text(text: str, size: int, overlap: int) -> Iterator[str]:
    # Sliding window over characters. Snaps to whitespace where possible to avoid splitting words.
    if not text:
        return
    if size <= 0:
        raise ValueError("size must be > 0")
    if overlap >= size:
        raise ValueError("overlap must be < size")

    n = len(text)
    start = 0
    while start < n:
        end = min(start + size, n)
        # snap end back to nearest whitespace inside the window
        if end < n:
            ws = text.rfind(" ", start, end)
            if ws > start + size // 2:
                end = ws
        chunk = text[start:end].strip()
        if chunk:
            yield chunk
        if end >= n:
            break
        start = max(end - overlap, start + 1)
