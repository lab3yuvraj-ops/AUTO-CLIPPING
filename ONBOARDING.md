# Student onboarding

Open your own clone as a project in Codex and say **onboarding**. Each student has a separate local checkout, private `.env`, channel and processing history. The repository contains no creator credentials, channel connection, saved videos or local model weights.

## First-time installation (Windows)

Use Python 3.11, Git, FFmpeg/ffprobe and a supported yt-dlp JavaScript runtime such as Node.js. From the repository folder in PowerShell:

```powershell
py -3.11 -m venv .venv
.venv/Scripts/python.exe -m pip install --upgrade pip
.venv/Scripts/python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
.venv/Scripts/python.exe -m pip install -r requirements-local.txt
Copy-Item .env.example .env
```

Do not overwrite an existing `.env`. This workflow currently uses Windows process locking; other platforms need that part adapted before use. CPU/int8 is the supported default; no GPU or paid inference API is required. Model downloads are a one-time setup and depend on your connection and machine.

## Connect your accounts

1. Tell Codex which YouTube channel URL or channel ID to use. Public channel lookup requires no YouTube API key.
2. Connect your own Instagram account in Zernio. Enter `ZERNIO_API_KEY` and `ZERNIO_INSTAGRAM_ID` in the private local `.env` editor. The ID is Zernio's connected account `_id`, not your Instagram username or numeric Instagram ID. Never paste secrets into chat or commit them. [Zernio account connection guide](https://docs.zernio.com/guides/connecting-accounts), [account verification API](https://docs.zernio.com/accounts/list-accounts).
3. Run the following, replacing `CHANNEL_URL_OR_ID`:

```powershell
.venv/Scripts/python.exe reel.py onboarding --channel CHANNEL_URL_OR_ID --from-env
```

The command verifies that the Instagram account is accessible to your Zernio key, saves your channel in ignored `workflow/connection.json`, and installs the four-second CTA default. It makes no post. Running without `--from-env` provides a hidden terminal key prompt instead. Never supply API keys as command-line arguments.

## Prepare local transcription once

Accept access conditions for [pyannote Community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) using your own Hugging Face account. Set your read token as `HF_TOKEN` in private `.env`, then run:

```powershell
.venv/Scripts/python.exe reel.py prepare-models --download
```

This downloads Whisper small and the approved speaker model locally. Later analysis uses cached models offline; HF_TOKEN is for gated model provisioning, not hosted inference. After preparation, `reel.py prepare-models` checks offline model loading. OpenAI, Groq and AssemblyAI keys are not used.

If YouTube challenges downloads, configure an authorized cookie-file path in `YOUTUBE_COOKIE_FILE`; cookie files are private and must never be shared in Git. A blocked download remains a real blocker, not a simulated successful job.

## Everyday use

Say **YouTube analyze**. Codex asks how many clips you want, checks your saved channel, downloads/transcribes the source, reviews all of it, and chooses complete moments. If an additional clip is weaker, it explains why and asks before creating it. Tracking, full-height horizontal framing, smooth movement, locked Hinglish captions and the four-second CTA follow `AGENTS.md`.

You receive the actual MP4 and the question **“Do you want to upload this video to Instagram?”** Clear approval of that exact preview authorizes publication. Codex polls the same Zernio request until it confirms a post ID/link. Saying no leaves the clip local. No dashboard, hosted worker or background schedule is created.

## Sharing on GitHub

Use `tools/build_release.py` to prepare a clean, allowlisted repository folder and ZIP under ignored `release/`. It includes code, docs, tests, licensed fonts, the supplied CTA and blank configuration templates. It excludes `.env`, cookies, connections, saved jobs, private footage, model weights, virtual environments and publication records. The CTA is shared intentionally as the project's supplied end card; students may replace it with their own.

Authenticate GitHub locally with `gh auth login` or your Git credential manager. Do not put a personal access token into a remote URL or files. If a token was pasted into chat, revoke it before publishing. A repository URL/name and visibility are still needed before an actual push.
