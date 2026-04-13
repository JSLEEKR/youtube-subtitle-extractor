# youtube-subtitle-extractor

Turn a YouTube channel (or single video) into a Korean-language knowledge bundle:
English transcript, Korean translation, researched blog article, and a 3-round
adversarial debate document. Orchestrated as Claude Code slash commands.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate     # Windows
pip install -r requirements-dev.txt
```

`ffmpeg` must be on PATH (for yt-dlp audio extraction). For GPU Whisper,
CUDA toolkit with cuBLAS + cuDNN is required; otherwise the script falls
back to CPU automatically.

## Usage (from a Claude Code session)

```
/extract-video <video_url>
/extract-channel <channel_url> [--days 30] [--limit N] [--skip-debate]
```

Output lands in `output/<channel_handle>/`. See
`docs/superpowers/specs/2026-04-13-youtube-channel-extractor-design.md`
for the full design.

## Running tests

```bash
pytest -v
```
