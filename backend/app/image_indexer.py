"""Image indexer — caption images from memory/ with OpenAI Vision and index as nodes.

Usage
-----
Call `index_images_from_memory(knowledge, settings)` at startup to ensure all
*.png / *.jpg / *.jpeg / *.webp files in the memory directory have a corresponding
KnowledgeNode with a Vision-generated caption as the body.

The node metadata stores `source_type: "image"` and `image_path` (relative to
the memory root) so the RAG layer can surface the image URL alongside context.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger("ask-my-agent.image_indexer")

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB safety cap


def _image_to_base64(path: Path) -> str:
    """Return base64-encoded image content."""
    return base64.standard_b64encode(path.read_bytes()).decode("utf-8")


def _mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(suffix, "image/jpeg")


def _caption_image(path: Path, api_key: str) -> str:
    """Call OpenAI Vision (gpt-4o) to generate a descriptive caption for an image."""
    import httpx  # type: ignore[import-untyped]

    if path.stat().st_size > _MAX_IMAGE_BYTES:
        log.warning("image %s exceeds size cap, skipping Vision call", path.name)
        return f"[Image: {path.name} — too large to caption automatically]"

    b64 = _image_to_base64(path)
    mime = _mime_type(path)

    payload = {
        "model": "gpt-4o",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "You are indexing personal memory images for an AI knowledge base. "
                            "Describe this image concisely and factually in 2-4 sentences. "
                            "Include: what/who is shown, context if visible, any relevant text. "
                            "Write as a factual caption suitable for retrieval."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "low"},
                    },
                ],
            }
        ],
        "max_tokens": 300,
    }

    resp = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    result = resp.json()
    return result["choices"][0]["message"]["content"].strip()


def _relative_image_path(image_path: Path, memory_root: Path) -> str:
    """Return the path of an image relative to memory_root as a POSIX string."""
    try:
        return image_path.relative_to(memory_root).as_posix()
    except ValueError:
        return image_path.name


def _node_id_for_image(rel_path: str) -> str:
    """Stable deterministic node id for a given relative image path."""
    return "img-" + hashlib.sha1(rel_path.encode()).hexdigest()[:12]


def index_images_from_memory(
    knowledge: Any,
    memory_path: Path,
    api_key: str,
) -> int:
    """Scan memory_path for image files; create/update KnowledgeNodes with Vision captions.

    Returns the number of images newly captioned/indexed.
    """
    if not api_key:
        log.info("OPENAI_API_KEY not set — skipping image indexing")
        return 0

    image_files = [
        p for p in memory_path.rglob("*")
        if p.suffix.lower() in IMAGE_SUFFIXES and p.is_file()
    ]

    if not image_files:
        log.debug("no image files found under %s", memory_path)
        return 0

    log.info("found %d image(s) in memory, checking for new/changed…", len(image_files))
    indexed = 0

    for img_path in image_files:
        rel = _relative_image_path(img_path, memory_path)
        node_id = _node_id_for_image(rel)

        existing = knowledge.get_node(node_id)
        if existing:
            # Check if the node metadata still matches (same path)
            meta = existing.metadata
            if meta.get("image_path") == rel and existing.body:
                log.debug("image node %s already up to date", node_id)
                continue

        # Caption via Vision
        try:
            caption = _caption_image(img_path, api_key)
        except Exception as exc:  # noqa: BLE001
            log.warning("failed to caption image %s: %s", rel, exc)
            caption = f"[Image: {img_path.name}]"

        title = img_path.stem.replace("-", " ").replace("_", " ").title()
        metadata: dict[str, Any] = {"source_type": "image", "image_path": rel}

        if existing:
            knowledge.update_node(
                node_id,
                body=caption,
                metadata=metadata,
                title=title,
            )
            log.info("updated image node %s (%s)", node_id, rel)
        else:
            knowledge.create_node(
                id=node_id,
                type="document",
                title=title,
                body=caption,
                metadata=metadata,
                roles=["personal"],  # images are personal by default
            )
            log.info("created image node %s (%s)", node_id, rel)

        indexed += 1

    return indexed


__all__ = ["index_images_from_memory"]
