"""
ElevenLabs voice services: voice cloning from a sample + TTS using a cloned voice.

Flow (one-time setup per user):
  1. clone_voice(name, audio_file_path) → voice_id  (stored to DB)

Flow (per video):
  2. generate_speech(voice_id, script) → mp3_file_path  (saved to media_files/)
"""

import os
import uuid
import logging
from typing import Optional

from shared.config import ELEVENLABS_API_KEY

logger = logging.getLogger(__name__)

MEDIA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "media_files")
os.makedirs(MEDIA_DIR, exist_ok=True)

# ElevenLabs model — highest quality, 70+ languages
TTS_MODEL = "eleven_v3"


def _client():
    from elevenlabs.client import ElevenLabs
    if not ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY is not configured")
    return ElevenLabs(api_key=ELEVENLABS_API_KEY)


def clone_voice(user_label: str, audio_file_path: str) -> Optional[str]:
    """
    Clone a voice from a user-supplied audio sample.

    Args:
        user_label: Unique label e.g. "user_60123456789"
        audio_file_path: Absolute path to the audio file (MP3/OGG/M4A/AAC)

    Returns:
        ElevenLabs voice_id string, or None on failure.
    """
    try:
        client = _client()
        filename = os.path.basename(audio_file_path)
        with open(audio_file_path, "rb") as f:
            # Pass (filename, file_object) so ElevenLabs knows the format
            voice = client.clone(
                name=user_label,
                description="User voice clone for avatar video generation",
                files=[(filename, f)],
            )
        voice_id = voice.voice_id
        logger.info("Voice cloned for %s → voice_id: %s", user_label, voice_id)
        return voice_id
    except Exception as e:
        logger.error("Voice cloning failed for %s: %s", user_label, e)
        return None


def delete_voice(voice_id: str) -> bool:
    """Delete a previously cloned voice from ElevenLabs (called when user re-clones)."""
    try:
        client = _client()
        client.voices.delete(voice_id)
        logger.info("Deleted voice clone: %s", voice_id)
        return True
    except Exception as e:
        logger.error("Failed to delete voice %s: %s", voice_id, e)
        return False


def generate_speech(voice_id: str, script: str, output_format: str = "mp3_44100_128") -> Optional[str]:
    """
    Generate speech from a script using a cloned voice.

    Args:
        voice_id: ElevenLabs voice_id (from clone_voice)
        script: The text to speak
        output_format: ElevenLabs audio format string

    Returns:
        Absolute path to the saved MP3 file, or None on failure.
    """
    try:
        client = _client()
        audio_chunks = client.text_to_speech.convert(
            voice_id=voice_id,
            text=script,
            model_id=TTS_MODEL,
            output_format=output_format,
        )
        filename = f"voice_{uuid.uuid4().hex}.mp3"
        file_path = os.path.join(MEDIA_DIR, filename)
        with open(file_path, "wb") as f:
            for chunk in audio_chunks:
                f.write(chunk)
        logger.info("Speech generated → %s (%d chars)", filename, len(script))
        return file_path
    except Exception as e:
        logger.error("Speech generation failed for voice %s: %s", voice_id, e)
        return None
