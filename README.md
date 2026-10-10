# Codex Reel workflow

For a fresh student clone, read [ONBOARDING.md](ONBOARDING.md), install the local dependencies and say **onboarding**. Configure your own YouTube channel and Zernio account; no credentials or channel are distributed. **YouTube analyze** is also an accepted trigger.

This is a local Python workflow operated here in Codex. There is no dashboard, server, database, Railway deployment or paid text/vision API. Codex selects the story, corrects Roman Hindi and inspects framing. Python downloads, transcribes locally, edits, renders, validates and publishes approved videos.

Say **analyze video** or **analyze YouTube**. Codex first asks how many clips you want, unless you already specified a count. For a supplied file or URL, it analyzes that source; otherwise it checks the connected channel's latest released upload. Run `.venv/Scripts/python.exe reel.py analyze --clips NUMBER` with optional `--file PATH` or `--url URL`. Saved sources and transcripts are reused. The count is recorded as a request, not a promise that enough strong clips exist.

After transcription, Codex reviews the full transcript and chronological source frames, ranks complete 30–60-second moments, and records the evidence and candidate strengths/weaknesses in `selection-report.json`. A good opening, independent context and intact payoff matter more than filling the requested count. If only one moment works, Codex says so; if a second complete moment is weaker, it explains why and asks whether you still want that candidate before rendering it. It does not invent engagement scores or pad clips. Each produced clip needs its own edit, output and publication approval. Python records requests and processes media; editorial judgment happens here in Codex, without an inference API.

Run `reel.py render JOB_ID --edit EDIT.json` to create the real preview. Say **good to go** for that exact video to authorize `reel.py publish JOB_ID --confirmed`. Repeating publish polls the same Zernio post. Pending requests retain their idempotency key; expired safe-retry windows require reconciliation, never a new post. `reel.py status JOB_ID` shows saved progress.

Use `reel.py connect CHANNEL_URL` to change the connected channel. For testing, `reel.py analyze --url VIDEO_URL` or `reel.py analyze --file VIDEO_PATH`. Use your own connected channel. If its public feed has no released uploads, the script checks the channel's selected Videos tab; downloading verifies the video's channel, public availability and source quality.

## Credentials and dependencies

Private `.env`: `ZERNIO_API_KEY` and `ZERNIO_INSTAGRAM_ID` are required for publishing. Connect the account in Zernio. The script uses its direct presigned upload flow: https://docs.zernio.com/guides/media-uploads . No public localhost server or callback is required.

YouTube public lookup needs no API key. `YOUTUBE_COOKIE_FILE` can be configured for authorized downloads when needed. Local Whisper and pyannote models are already cached. `HF_TOKEN` is only for authorized model provisioning, not hosted inference per video. There is no OpenAI, Groq or AssemblyAI usage. Unused credentials/server fields were removed from `.env`.

Install `requirements.txt` and `requirements-local.txt`. FFmpeg, ffprobe and a yt-dlp JavaScript runtime must be available. The existing virtual environment, trust store and models were preserved. CPU/int8 transcription remains supported.

## Saved files and editing

`workflow/connection.json` stores the channel; `workflow/jobs/JOB_ID/job.json` stores real progress and publication state. Atomic JSON writes and a process lock prevent overlapping local commands. Successful sources, transcripts and matching renders are reused. Download attempts are bounded.

Historical approved references, if present in an existing local checkout, remain private under ignored `workflow/` and `data/`. They are not included in student clones. `AGENTS.md` records the portable editing contract; `templates/output-defaults.json` initializes the CTA during onboarding.

Edit JSON requires `candidate`, `words`, `tracking` and `caption`. The candidate supplies source start/end, first/last word IDs, reason, opening, ending and preserved pauses. Words supply unique source IDs, source word timestamps, Roman text and speaker labels. Tracking supplies source-time crop points, actual scene cuts and evidenced visual targets, including reviewed identity box keyframes. Use the approved reference as a schema example; create new boxes for each source.

Output: 1080 × 1920 H.264/AAC; one full-screen crop spanning the entire source height, with width = source height × 9/16. Follow story targets horizontally only, with 1.2-second scene-bounded easing; no added zoom or vertical movement. Creepster captions fixed at (500,1420); white text with only the spoken word red. No borders, inset or duplicated video. Preserve a complete 30–60-second story after silence removal. Technical checks cannot prove perfect wording, lip sync or semantic identity; Codex must review and state any uncertainty before approval.

No scheduled Codex automation was created by this conversion. This is the script workflow that you can trigger here.

Freshness checks: every channel analysis requests the public feed again. Render caching includes the editing code and AGENTS.md rule fingerprint plus caption style. Updated rules/code invalidate older unposted previews; output hashes prevent reusing a modified MP4. Already published posts are preserved, never republished automatically. New footage still requires Codex visual/editorial review.

## Processing speed and current measurements

Caption/framing revisions reuse a SHA-verified lossless source edit. Reviewed identity anchors plan camera geometry without decoding a second video pass. The `review` command produces combined source/crop/caption pages before rendering; `recheck` batches uncertain passages through one cached Whisper model load. These do not reduce resolution, beam size, caption timing precision or encoding quality.

For job `oNIXR036tHc`, the earlier camera-planning pass took 10.55 seconds; anchor planning took 0.04 seconds with exactly matching geometry. Lossless preparation dropped from 12.12 seconds to about 0.5–0.7 seconds on a valid cache hit. Encoding remains the main render cost. The final full-height 59.4-second preview took 58.02 seconds to render plus 2.31 seconds of technical checks; this is a revision with saved audio/transcript/edit, not a fresh end-to-end benchmark. Five to six minutes for a new video is not yet demonstrated.

The experimental NVENC comparison encoded in 34.93 seconds versus a 53.53-second CPU trial, but produced different compressed pixels and a larger file. Keep libx264 CRF18 as the default. A separate `.venv-gpu` speech runtime was attempted; the working CPU environment and cached models are preserved. GPU transcription is not enabled or validated. There are no additional hosted inference API fees for these local optimizations; existing Codex/Zernio charges and electricity still apply.

## Default CTA ending

The supplied `Watch.mp4` is preserved as `assets/cta/watch-full-video.mp4`. Every new render appends its first four seconds, controlled by `workflow/output-defaults.json`. The existing story stays 30–60 seconds; the CTA is additional export time. Keep the original laughter/reaction once, at its original speed, and append the CTA directly when it finishes. No repeated audio, added freeze holds or stretched endings. Nonzero `ending_hold_seconds` is rejected. The current mirror export is approximately 63.4 seconds including the four-second CTA.

The CTA is normalized to compatible 1080 × 1920 / 30fps H.264/AAC; silent audio is added when absent. Story and ending parts are concatenated using stream copy so the story is not recompressed. Validation records story duration separately from total export duration. The black CTA background is intentional; the story still receives black/frozen-frame checks. CTA source hashes participate in preview caching; publication always requires approval of the complete new MP4.

The optional GPU speech-runtime download subsequently failed with a DNS lookup error at the PyTorch download host. GPU transcription remains inactive; the existing CPU environment is working and was used for this edit.
