#!/usr/bin/env python3
"""
WhisperFlow - Terminal-based Speech-to-Text using Groq API
A real-time, asynchronous voice transcription and text processing application.

Architecture:
    Audio Capture → VAD → Buffer → Groq Whisper STT → Groq LLM → Terminal UI
"""

import asyncio
import io
import os
import sys
import time
import wave
import signal
import argparse
import tempfile
import subprocess
from dataclasses import dataclass, field
from typing import Optional, List, Callable
from collections import deque
from pathlib import Path

import numpy as np
import aiohttp
import pyaudio
from rich.console import Console
from rich.panel import Panel
from rich.live import Live
from rich.layout import Layout
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.syntax import Syntax


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

GROQ_API_BASE = "https://api.groq.com/openai/v1"
WHISPER_MODEL = "whisper-large-v3"   # multilingual; also the only Groq model that supports translation
LLM_MODEL = "llama-3.3-70b-versatile"  # 3.1-70b was decommissioned by Groq

# Audio settings
SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_DURATION_MS = 30
CHUNK_SIZE = int(SAMPLE_RATE * CHUNK_DURATION_MS / 1000)
FORMAT = pyaudio.paInt16

# VAD settings
VAD_AGGRESSIVENESS = 2
VAD_FRAME_DURATION_MS = 30
SILENCE_THRESHOLD_MS = 800
MIN_SPEECH_DURATION_MS = 250
MAX_RECORDING_DURATION_S = 30

# Buffer settings
PRE_SPEECH_BUFFER_MS = 300

# Push-to-talk: safety cap so a forgotten toggle can't record forever.
MANUAL_MAX_RECORDING_S = 300


# ─────────────────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AudioSegment:
    """Represents a captured speech segment ready for transcription."""
    audio_data: bytes
    timestamp: float = field(default_factory=time.time)
    duration_ms: float = 0.0

    def to_wav_bytes(self) -> bytes:
        """Convert raw PCM to WAV format bytes."""
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(self.audio_data)
        return buffer.getvalue()


@dataclass
class TranscriptionResult:
    """Result from STT + optional LLM processing."""
    raw_text: str
    processed_text: str
    transcription_time: float
    processing_time: float
    total_latency: float
    language: str = ""   # language Whisper detected for this utterance


# ─────────────────────────────────────────────────────────────────────────────
# VOICE ACTIVITY DETECTION
# ─────────────────────────────────────────────────────────────────────────────

class WebRTCVAD:
    """Python implementation of WebRTC VAD logic (no external deps)."""

    def __init__(self, aggressiveness: int = 2):
        self.aggressiveness = aggressiveness
        self.frame_duration_ms = VAD_FRAME_DURATION_MS
        self.sample_rate = SAMPLE_RATE

        # Simple energy-based VAD with adaptive threshold
        self.noise_floor = 0.0
        self.adaptation_rate = 0.1
        self.speech_threshold_db = 20 + (aggressiveness * 5)  # 30-50 dB range

    def _frame_to_rms(self, frame: bytes) -> float:
        """Calculate RMS energy of a frame."""
        audio_array = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
        if len(audio_array) == 0:
            return 0.0
        # RMS in dB
        rms = np.sqrt(np.mean(audio_array ** 2))
        if rms == 0:
            return -100.0
        return 20 * np.log10(rms)

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        """Determine if frame contains speech."""
        if sample_rate != self.sample_rate:
            raise ValueError(f"Expected {self.sample_rate}Hz, got {sample_rate}Hz")

        rms_db = self._frame_to_rms(frame)

        # Update noise floor
        if rms_db < self.noise_floor + self.speech_threshold_db:
            self.noise_floor = (1 - self.adaptation_rate) * self.noise_floor +                                self.adaptation_rate * rms_db

        # Speech detection
        return rms_db > (self.noise_floor + self.speech_threshold_db)


# ─────────────────────────────────────────────────────────────────────────────
# AUDIO CAPTURE & SEGMENTATION
# ─────────────────────────────────────────────────────────────────────────────

class AudioCapture:
    """Handles real-time audio capture with VAD-based segmentation."""

    def __init__(self,
                 on_segment: Callable[[AudioSegment], None],
                 sample_rate: int = SAMPLE_RATE,
                 channels: int = CHANNELS,
                 manual: bool = False):
        self.sample_rate = sample_rate
        self.channels = channels
        self.on_segment = on_segment
        # manual=True → push-to-talk: recording is toggled by start_manual()/
        # stop_manual() and VAD is bypassed entirely.
        self.manual = manual

        self.vad = WebRTCVAD(aggressiveness=VAD_AGGRESSIVENESS)
        self.audio = pyaudio.PyAudio()
        self.stream: Optional[pyaudio.Stream] = None

        # State
        self.is_recording = False
        self.is_running = False
        self.current_segment: List[bytes] = []
        self.pre_speech_buffer: deque = deque(maxlen=int(PRE_SPEECH_BUFFER_MS / CHUNK_DURATION_MS))
        self.silence_frames = 0
        self.speech_frames = 0
        self.total_frames = 0

    def _calculate_duration_ms(self, frames: List[bytes]) -> float:
        """Calculate duration of audio frames in milliseconds."""
        total_samples = sum(len(f) // 2 for f in frames)  # 16-bit = 2 bytes
        return (total_samples / self.sample_rate) * 1000

    def _emit_segment(self):
        """Finalize and emit the current speech segment."""
        if not self.current_segment:
            return

        duration = self._calculate_duration_ms(self.current_segment)
        if duration < MIN_SPEECH_DURATION_MS:
            self.current_segment = []
            return

        # Combine all frames
        audio_data = b''.join(self.current_segment)

        segment = AudioSegment(
            audio_data=audio_data,
            duration_ms=duration
        )

        self.on_segment(segment)
        self.current_segment = []
        self.silence_frames = 0
        self.speech_frames = 0

    def start_manual(self):
        """Push-to-talk: begin recording (toggle pressed)."""
        self.current_segment = []
        self.is_recording = True

    def stop_manual(self):
        """Push-to-talk: stop recording and emit the whole take as ONE segment."""
        self.is_recording = False
        self._emit_segment()

    def _process_frame(self, frame: bytes):
        """Process a single audio frame."""
        if self.manual:
            # Push-to-talk mode: no VAD — just collect while toggled on.
            if self.is_recording:
                self.current_segment.append(frame)
                if self._calculate_duration_ms(self.current_segment) >= MANUAL_MAX_RECORDING_S * 1000:
                    self.stop_manual()
            return

        is_speech = self.vad.is_speech(frame, self.sample_rate)

        if is_speech:
            self.speech_frames += 1
            self.silence_frames = 0

            if not self.is_recording:
                # Start of speech - include pre-buffer
                self.is_recording = True
                self.current_segment = list(self.pre_speech_buffer)

            self.current_segment.append(frame)

        else:
            self.silence_frames += 1

            if self.is_recording:
                self.current_segment.append(frame)

                # Check if silence threshold exceeded
                silence_ms = self.silence_frames * CHUNK_DURATION_MS
                if silence_ms >= SILENCE_THRESHOLD_MS:
                    self._emit_segment()
                    self.is_recording = False

            else:
                # Store in pre-speech buffer
                self.pre_speech_buffer.append(frame)

        # Safety: max duration
        if self.is_recording:
            duration = self._calculate_duration_ms(self.current_segment)
            if duration >= MAX_RECORDING_DURATION_S * 1000:
                self._emit_segment()
                self.is_recording = False

    def start(self):
        """Start audio capture."""
        self.is_running = True
        self.stream = self.audio.open(
            format=FORMAT,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=CHUNK_SIZE,
            stream_callback=self._audio_callback
        )
        self.stream.start_stream()

    def _audio_callback(self, in_data, frame_count, time_info, status):
        """PyAudio callback for non-blocking audio capture."""
        if self.is_running:
            self._process_frame(in_data)
        return (in_data, pyaudio.paContinue)

    def stop(self):
        """Stop audio capture and emit any pending segment."""
        self.is_running = False
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        self.audio.terminate()

        # Emit any remaining speech
        if self.is_recording and self.current_segment:
            self._emit_segment()


# ─────────────────────────────────────────────────────────────────────────────
# GROQ API CLIENT
# ─────────────────────────────────────────────────────────────────────────────

class GroqClient:
    """Async client for Groq API (STT + LLM)."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = GROQ_API_BASE
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        timeout = aiohttp.ClientTimeout(total=30, connect=5)
        self.session = aiohttp.ClientSession(timeout=timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def transcribe(self, audio_segment: AudioSegment,
                         language: Optional[str] = None) -> tuple[str, str]:
        """Transcribe audio using Groq Whisper API.
        Returns (text, detected_language). With no language pinned, Whisper
        auto-detects PER UTTERANCE — so the user can switch languages mid-
        session and each segment still comes out in the right script."""
        url = f"{self.base_url}/audio/transcriptions"

        wav_data = audio_segment.to_wav_bytes()

        data = aiohttp.FormData()
        data.add_field('file',
                       io.BytesIO(wav_data),
                       filename='audio.wav',
                       content_type='audio/wav')
        data.add_field('model', WHISPER_MODEL)
        # verbose_json instead of text: same transcription, but Whisper also
        # reports WHICH language it detected — that's the multilingual signal.
        data.add_field('response_format', 'verbose_json')

        if language and language != "auto":
            data.add_field('language', language)

        headers = {
            'Authorization': f'Bearer {self.api_key}'
        }

        async with self.session.post(url, data=data, headers=headers) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise RuntimeError(f"STT API error {resp.status}: {error_text}")
            result = await resp.json()
            return result.get("text", "").strip(), (result.get("language") or "")

    async def translate(self, audio_segment: AudioSegment) -> tuple[str, str]:
        """Translate speech in ANY language directly to English text
        (Groq's /audio/translations endpoint, whisper-large-v3 only)."""
        url = f"{self.base_url}/audio/translations"

        wav_data = audio_segment.to_wav_bytes()

        data = aiohttp.FormData()
        data.add_field('file',
                       io.BytesIO(wav_data),
                       filename='audio.wav',
                       content_type='audio/wav')
        data.add_field('model', WHISPER_MODEL)
        data.add_field('response_format', 'verbose_json')

        headers = {
            'Authorization': f'Bearer {self.api_key}'
        }

        async with self.session.post(url, data=data, headers=headers) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise RuntimeError(f"Translate API error {resp.status}: {error_text}")
            result = await resp.json()
            return result.get("text", "").strip(), (result.get("language") or "")

    async def process_text(self, text: str, mode: str = "clean") -> str:
        """Process transcribed text with Groq LLM."""
        url = f"{self.base_url}/chat/completions"

        # Every prompt pins the output to the INPUT's language — without this,
        # the LLM silently translates Hindi/Spanish/etc. speech into English.
        keep_lang = ("The text may be in any language. Reply in the SAME language "
                     "and script as the input — do NOT translate. ")
        prompts = {
            "clean": (
                f"{keep_lang}"
                "Clean up this transcribed text. Fix grammar, punctuation, and formatting. "
                "Keep the meaning identical. Only return the cleaned text, no explanations.\n\n"
                f"Text: {text}"
            ),
            "summarize": (
                f"{keep_lang}"
                "Summarize the following text concisely while preserving key information. "
                "Only return the summary, no explanations.\n\n"
                f"Text: {text}"
            ),
            "format": (
                f"{keep_lang}"
                "Format the following text with proper paragraphs, punctuation, and structure. "
                "Only return the formatted text, no explanations.\n\n"
                f"Text: {text}"
            ),
            "none": text
        }

        if mode == "none":
            return text

        payload = {
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": "You are a multilingual text processing assistant. "
                 "Always reply in the same language and script as the user's text; never translate."},
                {"role": "user", "content": prompts.get(mode, prompts["clean"])}
            ],
            "temperature": 0.1,
            "max_tokens": 2048
        }

        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

        async with self.session.post(url, json=payload, headers=headers) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise RuntimeError(f"LLM API error {resp.status}: {error_text}")
            result = await resp.json()
            return result["choices"][0]["message"]["content"].strip()


# ─────────────────────────────────────────────────────────────────────────────
# TERMINAL UI
# ─────────────────────────────────────────────────────────────────────────────

class TerminalUI:
    """Rich-based terminal user interface."""

    def __init__(self):
        self.console = Console()
        self.transcriptions: List[TranscriptionResult] = []
        self.is_listening = False
        self.status_message = "Ready"
        self.current_latency = 0.0

    def _build_layout(self) -> Layout:
        """Build the terminal layout."""
        layout = Layout()

        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main"),
            Layout(name="status", size=3)
        )

        # Header
        title = Text("🎙️  WhisperFlow", style="bold cyan")
        subtitle = Text("Real-time Speech-to-Text via Groq", style="dim")
        header_text = Text.assemble(title, "  ", subtitle)
        layout["header"].update(Panel(header_text, border_style="cyan"))

        # Main content - transcriptions
        content = []
        for i, result in enumerate(self.transcriptions[-10:], 1):
            latency_str = f"[{result.total_latency:.2f}s]"
            lang_str = f" · {result.language}" if result.language else ""
            content.append(f"[bold green]►[/bold green] {result.processed_text}")
            content.append(f"[dim]{latency_str}{lang_str} raw: {result.raw_text[:60]}...[/dim]\n")

        main_text = Text.from_markup("\n".join(content) if content else "[dim]Waiting for speech...[/dim]")
        layout["main"].update(Panel(main_text, title="Transcriptions", border_style="green"))

        # Status bar
        status_color = "green" if self.is_listening else "yellow"
        status_icon = "● LISTENING" if self.is_listening else "○ PAUSED"
        status_text = Text.assemble(
            Text(f"{status_icon}  ", style=f"bold {status_color}"),
            Text(f"{self.status_message}  ", style="white"),
            Text(f"Latency: {self.current_latency:.2f}s", style="dim")
        )
        layout["status"].update(Panel(status_text, border_style=status_color))

        return layout

    def update(self, live: Live):
        """Refresh the UI."""
        live.update(self._build_layout())

    def add_transcription(self, result: TranscriptionResult):
        """Add a new transcription result."""
        self.transcriptions.append(result)
        self.current_latency = result.total_latency

    def set_listening(self, listening: bool):
        """Update listening state."""
        self.is_listening = listening
        self.status_message = "Capturing audio..." if listening else "Ready"

    def set_status(self, message: str):
        """Update status message."""
        self.status_message = message


# ─────────────────────────────────────────────────────────────────────────────
# MAIN APPLICATION
# ─────────────────────────────────────────────────────────────────────────────

class WhisperFlow:
    """Main application orchestrator."""

    def __init__(self, api_key: str, processing_mode: str = "clean",
                 language: Optional[str] = None, translate: bool = False,
                 auto: bool = False, toggle_key: str = " "):
        self.api_key = api_key
        self.processing_mode = processing_mode
        self.language = language      # None/"auto" → per-utterance auto-detect
        self.translate = translate    # True → any spoken language, English text out
        self.manual = not auto        # push-to-talk toggle (default) vs VAD hands-free
        self.toggle_key = toggle_key

        self.ui = TerminalUI()
        self.client: Optional[GroqClient] = None
        self.capture: Optional[AudioCapture] = None

        # Async queue for audio segments
        self.segment_queue: asyncio.Queue[AudioSegment] = asyncio.Queue()
        self.is_running = False

    def _on_audio_segment(self, segment: AudioSegment):
        """Callback when VAD detects a speech segment."""
        try:
            self.segment_queue.put_nowait(segment)
        except asyncio.QueueFull:
            pass

    # ── Push-to-talk keyboard handling ────────────────────────────────────

    def _key_name(self) -> str:
        return "SPACE" if self.toggle_key == " " else self.toggle_key.upper()

    def _toggle_recording(self):
        if self.capture.is_recording:
            self.capture.stop_manual()   # emits the whole take → queue → Whisper
            self.ui.set_listening(False)
            self.ui.set_status("Got it — analyzing…")
        else:
            self.capture.start_manual()
            self.ui.set_listening(True)
            self.ui.set_status(f"Recording… press {self._key_name()} when you're done")

    def _handle_key(self, ch: str):
        if not ch:
            return
        if self.manual and ch == self.toggle_key:
            self._toggle_recording()
        elif ch.lower() == "q":
            self.is_running = False

    def _on_stdin_readable(self):
        """POSIX: called by the event loop whenever a key is pressed."""
        try:
            self._handle_key(sys.stdin.read(1))
        except Exception:
            pass

    async def _poll_keys_windows(self):
        """Windows: poll the console for keypresses."""
        import msvcrt
        while self.is_running:
            while msvcrt.kbhit():
                try:
                    self._handle_key(msvcrt.getch().decode(errors="ignore"))
                except Exception:
                    pass
            await asyncio.sleep(0.05)

    async def _process_segments(self):
        """Worker that processes audio segments from the queue."""
        async with GroqClient(self.api_key) as client:
            self.client = client

            while self.is_running:
                try:
                    segment = await asyncio.wait_for(self.segment_queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue

                start_time = time.time()

                try:
                    # Step 1: Transcribe (or translate to English)
                    self.ui.set_status("Transcribing with Groq Whisper...")
                    t0 = time.time()
                    if self.translate:
                        raw_text, detected_lang = await client.translate(segment)
                    else:
                        raw_text, detected_lang = await client.transcribe(segment, self.language)
                    transcription_time = time.time() - t0

                    if not raw_text.strip():
                        continue

                    # Step 2: Process with LLM (optional)
                    self.ui.set_status("Processing with Groq LLM...")
                    t0 = time.time()
                    processed_text = await client.process_text(raw_text, self.processing_mode)
                    processing_time = time.time() - t0

                    total_latency = time.time() - start_time

                    result = TranscriptionResult(
                        raw_text=raw_text,
                        processed_text=processed_text,
                        transcription_time=transcription_time,
                        processing_time=processing_time,
                        total_latency=total_latency,
                        language=detected_lang
                    )

                    self.ui.add_transcription(result)
                    self.ui.set_status(
                        f"Ready · press {self._key_name()} to talk again"
                        if self.manual else "Ready")

                except Exception as e:
                    self.ui.set_status(f"Error: {str(e)[:50]}")

    async def run(self):
        """Main application loop."""
        self.is_running = True

        # Setup audio capture
        self.capture = AudioCapture(
            on_segment=self._on_audio_segment,
            sample_rate=SAMPLE_RATE,
            channels=CHANNELS,
            manual=self.manual
        )

        # Handle Ctrl+C gracefully
        def signal_handler(sig, frame):
            self.is_running = False

        signal.signal(signal.SIGINT, signal_handler)

        # Keyboard: push-to-talk toggle + Q to quit (needs a real terminal)
        loop = asyncio.get_running_loop()
        key_task = None
        stdin_fd, old_term_attrs = None, None
        if sys.stdin.isatty():
            if os.name == "nt":
                key_task = asyncio.create_task(self._poll_keys_windows())
            else:
                import termios, tty
                stdin_fd = sys.stdin.fileno()
                old_term_attrs = termios.tcgetattr(stdin_fd)
                tty.setcbreak(stdin_fd)
                loop.add_reader(stdin_fd, self._on_stdin_readable)

        # Start audio capture
        self.capture.start()
        if self.manual:
            self.ui.set_listening(False)
            self.ui.set_status(f"Press {self._key_name()} to talk · Q to quit")
        else:
            self.ui.set_listening(True)

        # Start processing worker
        processor_task = asyncio.create_task(self._process_segments())

        try:
            # UI loop
            with Live(self.ui._build_layout(), refresh_per_second=4, console=self.ui.console) as live:
                while self.is_running:
                    self.ui.update(live)
                    await asyncio.sleep(0.25)
        finally:
            # Restore the terminal before anything else
            if stdin_fd is not None:
                loop.remove_reader(stdin_fd)
                import termios
                termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_term_attrs)
            if key_task:
                key_task.cancel()

        # Cleanup
        self.capture.stop()
        self.ui.set_listening(False)
        await processor_task

        # Final summary
        self.ui.console.print("\n[bold cyan]Session Complete[/bold cyan]")
        self.ui.console.print(f"Total transcriptions: {len(self.ui.transcriptions)}")
        if self.ui.transcriptions:
            avg_latency = sum(r.total_latency for r in self.ui.transcriptions) / len(self.ui.transcriptions)
            self.ui.console.print(f"Average latency: {avg_latency:.2f}s")


# ─────────────────────────────────────────────────────────────────────────────
# CLI ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main():
    global VAD_AGGRESSIVENESS
    parser = argparse.ArgumentParser(
        description="🎙️  WhisperFlow - Real-time Speech-to-Text via Groq",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                    # Push-to-talk: SPACE starts/stops, Q quits
  %(prog)s --auto                             # Hands-free: VAD segments speech automatically
  %(prog)s --toggle-key r                     # Use 'r' instead of SPACE to start/stop
  %(prog)s --mode clean                       # Clean up grammar/punctuation
  %(prog)s --mode summarize                   # Summarize each utterance
  %(prog)s --mode none                        # Raw transcription only
  %(prog)s                                    # Multilingual: auto-detects language per utterance
  %(prog)s --language hi                      # Pin one language (skips auto-detect)
  %(prog)s --translate                        # Speak ANY language, get English text out
  %(prog)s --key YOUR_API_KEY                 # Pass API key directly

Environment Variables:
  GROQ_API_KEY    Your Groq API key (required if --key not provided)
        """
    )

    parser.add_argument(
        "--key", "-k",
        default=os.environ.get("GROQ_API_KEY"),
        help="Groq API key (or set GROQ_API_KEY env var)"
    )
    parser.add_argument(
        "--mode", "-m",
        choices=["clean", "summarize", "format", "none"],
        default="clean",
        help="LLM post-processing mode (default: clean)"
    )
    parser.add_argument(
        "--language", "-l",
        default=None,
        help="Pin a language code (e.g., en, hi, es, fr). Omit (or 'auto') to "
             "auto-detect per utterance — you can switch languages mid-session."
    )
    parser.add_argument(
        "--translate", "-t",
        action="store_true",
        help="Translate any spoken language directly to English text"
    )
    parser.add_argument(
        "--auto", "-a",
        action="store_true",
        help="Hands-free mode: VAD detects speech automatically instead of push-to-talk"
    )
    parser.add_argument(
        "--toggle-key",
        default=" ",
        metavar="CHAR",
        help="Push-to-talk key that starts/stops a recording (default: spacebar)"
    )
    parser.add_argument(
        "--vad-aggressiveness", "-v",
        type=int,
        choices=[0, 1, 2, 3],
        default=VAD_AGGRESSIVENESS,
        help="VAD aggressiveness: 0=permissive, 3=strict (default: 2)"
    )

    args = parser.parse_args()

    if not args.key:
        print("Error: Groq API key required. Set GROQ_API_KEY environment variable or use --key.")
        sys.exit(1)

    # Update VAD setting
    VAD_AGGRESSIVENESS = args.vad_aggressiveness

    app = WhisperFlow(
        api_key=args.key,
        processing_mode=args.mode,
        language=args.language,
        translate=args.translate,
        auto=args.auto,
        toggle_key=(args.toggle_key or " ")[0]
    )

    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
