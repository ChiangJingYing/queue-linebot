"""Dashboard announcement + Google Cloud TTS integration."""

from __future__ import annotations

import json
import logging
import mimetypes
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)

_DIGIT_SPEECH_MAP = str.maketrans({
    "0": "零",
    "1": "一",
    "2": "二",
    "3": "三",
    "4": "四",
    "5": "五",
    "6": "六",
    "7": "七",
    "8": "八",
    "9": "九",
})


class GoogleCloudTTSService:
    """Generate speech audio with Google Cloud Text-to-Speech when configured."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        language_code: str = "cmn-TW",
        voice_name: str = "cmn-TW-Standard-A",
        audio_encoding: str = "MP3",
        speaking_rate: float = 1.0,
        pitch: float = 0.0,
    ) -> None:
        self.enabled = enabled
        self.language_code = language_code
        self.voice_name = voice_name
        self.audio_encoding = audio_encoding.upper()
        self.speaking_rate = speaking_rate
        self.pitch = pitch

    def synthesize(self, text: str) -> bytes:
        if not self.enabled:
            return b""

        try:
            from google.cloud import texttospeech
        except Exception as exc:
            logger.warning("Google Cloud TTS SDK unavailable: %s", exc)
            return b""

        try:
            client = texttospeech.TextToSpeechClient()
            input_text = texttospeech.SynthesisInput(text=text)
            voice = texttospeech.VoiceSelectionParams(
                language_code=self.language_code,
                name=self.voice_name,
            )
            audio_config = texttospeech.AudioConfig(
                audio_encoding=getattr(texttospeech.AudioEncoding, self.audio_encoding, texttospeech.AudioEncoding.MP3),
                speaking_rate=self.speaking_rate,
                pitch=self.pitch,
            )
            response = client.synthesize_speech(
                input=input_text,
                voice=voice,
                audio_config=audio_config,
            )
            return bytes(response.audio_content or b"")
        except Exception as exc:
            logger.exception("Google Cloud TTS synthesis failed")
            logger.warning("Google Cloud TTS fallback to silent payload: %s", exc)
            return b""


class DashboardAnnouncementService:
    """維護 dashboard 最新公告內容與可選語音檔。

    這個 service 的責任是「現場公告」而不是對使用者發私訊：
    - ``announce_called_guest()``：更新儀表板上的叫號文案，並視設定產生/複製語音檔
    - ``announce_new_order()``：更新「您有新訂單」類型的公告

    若要把叫號訊息直接推播給被叫號者，應走 ``Notifier`` / ``QueueManager.notifier``。
    """

    def __init__(
        self,
        *,
        root: str | Path = "dashboard_announcements",
        public_base_path: str = "/dashboard/audio",
        tts_service: GoogleCloudTTSService | None = None,
        announcement_template: str = "來賓 {display_name} 請準備demo",
        new_order_announcement_text: str = "您有新訂單",
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.public_base_path = public_base_path.rstrip("/")
        self.tts_service = tts_service or GoogleCloudTTSService(enabled=False)
        self.announcement_template = announcement_template
        self.new_order_announcement_text = new_order_announcement_text
        self.latest_path = self.root / "latest.json"

    def _normalize_display_name_for_speech(self, display_name: str) -> str:
        safe_name = (display_name or "").strip() or "來賓"
        if re.fullmatch(r"\d+", safe_name):
            return safe_name.translate(_DIGIT_SPEECH_MAP)
        return safe_name

    def announce_called_guest(self, *, display_name: str) -> dict:
        """發布「某位來賓請準備 demo」的現場公告。"""
        safe_name = (display_name or "").strip() or "來賓"
        speech_name = self._normalize_display_name_for_speech(safe_name)
        if self._uses_static_audio_template():
            text = f"來賓 {speech_name} 請準備demo"
            return self._write_announcement(text, audio_source=Path(self.announcement_template))
        text = self.announcement_template.format(display_name=speech_name)
        return self._write_announcement(text)

    def announce_new_order(self, *, text: str | None = None) -> dict:
        """發布「您有新訂單」類型的現場公告。"""
        raw_text = (text or self.new_order_announcement_text or "您有新訂單").strip()
        safe_text = raw_text or "您有新訂單"
        if safe_text.lower().endswith(".mp3"):
            return self._write_announcement("您有新訂單", audio_source=Path(safe_text))
        return self._write_announcement(safe_text)

    def _uses_static_audio_template(self) -> bool:
        template = (self.announcement_template or "").strip()
        return template.lower().endswith(".mp3")

    def _write_announcement(self, text: str, audio_source: Path | None = None) -> dict:
        announcement_id = uuid4().hex
        created_at = datetime.now().isoformat()
        payload = {
            "id": announcement_id,
            "text": text,
            "audioUrl": "",
            "createdAt": created_at,
        }

        if audio_source is not None and audio_source.exists():
            target_name = audio_source.name
            target_path = self.root / target_name
            if target_path.resolve() != audio_source.resolve():
                target_path.write_bytes(audio_source.read_bytes())
            payload["audioUrl"] = f"{self.public_base_path}/{target_name}"
        else:
            audio_bytes = self.tts_service.synthesize(text)
            if audio_bytes:
                audio_name = f"{announcement_id}.mp3"
                (self.root / audio_name).write_bytes(audio_bytes)
                payload["audioUrl"] = f"{self.public_base_path}/{audio_name}"

        self.latest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def get_latest(self) -> dict | None:
        if not self.latest_path.exists():
            return None
        try:
            payload = json.loads(self.latest_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def resolve_audio_asset(self, filename: str) -> Path:
        return self.root / Path(filename).name
