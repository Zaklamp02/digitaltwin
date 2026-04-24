"""Audio endpoints — /api/transcribe (Whisper) + /api/speak (TTS stream)."""

from __future__ import annotations

import logging
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from .auth import Caller, caller_dep
from .config import get_settings

log = logging.getLogger("ask-my-agent.audio")

router = APIRouter()


class SpeakRequest(BaseModel):
    text: str
    voice: str | None = None


@router.post("/api/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    caller: Caller = Depends(caller_dep),
):
    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured")

    # Lazy import so the module can load in environments without the SDK installed yet.
    from openai import AsyncOpenAI

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty audio")
    # OpenAI SDK wants a (filename, bytes, content_type) tuple-like.
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    try:
        resp = await client.audio.transcriptions.create(
            model=settings.stt_model,
            file=(file.filename or "audio.webm", content, file.content_type or "audio/webm"),
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("transcription failed")
        raise HTTPException(status_code=502, detail=f"transcription failed: {exc}") from exc
    return {"text": getattr(resp, "text", "") or ""}


async def _stream_tts(text: str, voice: str, api_key: str, model: str) -> AsyncIterator[bytes]:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key)
    async with client.audio.speech.with_streaming_response.create(
        model=model,
        voice=voice,
        input=text,
        response_format="pcm",  # 24 kHz, 16-bit signed, little-endian, mono
    ) as response:
        async for chunk in response.iter_bytes():
            yield chunk


@router.post("/api/speak")
async def speak(
    body: SpeakRequest,
    caller: Caller = Depends(caller_dep),
):
    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured")
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="empty text")
    voice = body.voice or settings.tts_voice
    return StreamingResponse(
        _stream_tts(text, voice, settings.openai_api_key, settings.tts_model),
        media_type="audio/pcm",
        headers={"X-PCM-Sample-Rate": "24000", "X-PCM-Bit-Depth": "16", "X-PCM-Channels": "1"},
    )
