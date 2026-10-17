# Lepakshi V1 baseline

Audit of production `prod_a575b17b4f8b4967` ("Lena at Lepakshi: the pillar that doesn't touch the floor") before any V2 provider work. No new paid generation was run for this note.

Current master: `asset_d3cfde22720748a3`. 1080x1920, 72.0s (69.0s of shots plus a 3s end card). State READY. Spend on the production ledger: **$8.06**, **187.25 Higgsfield credits**.

## What each agent does today

Agents are plain Python classes. The workflow engine calls them. They do not touch the database themselves. Every paid call goes through `PaidCallGuard`.

| Agent | Job on this video | Model actually used |
|---|---|---|
| A1 Master Orchestrator | Orders the steps and the approval gates | none |
| A2 Research | Facts | Wikipedia. One Claude Sonnet 4.5 call exists on the ledger ($0.0086) for planning text |
| A3 Media Discovery | Public photos used only as generator context | Wikimedia, Openverse. Free |
| A4 Creative Director | Look and tone | Claude, shared with the planning call above |
| A5 Scriptwriter | Spoken lines | The authored Lepakshi script. Not a fresh LLM draft |
| A6 Scene Director | One clip per spoken line, prompts, durations | no separate provider call |
| A7 Visual Production | Stills, then clips | Higgsfield `nano_banana_2`, `wan2_7`, `kling3_0` |
| A8 Audio & Performance | One voice line per spoken shot | Higgsfield `text2speech_v2` (Juno) |
| A9 Editor & QC | FFmpeg master, then duration and profile checks | local FFmpeg. QC does not score lip-sync |
| A10 Cost Optimizer | Price check against the credit cap | none |

Vlog gates, in order: script, preview (stills and voice), pilot (first talking clip and first temple clip), final (the rest), assemble, review.

## How a talking shot is made

1. A8 speaks the line with `text2speech_v2`. The file is stored as an `AUDIO` asset on the shot.
2. A7 builds the clip with `wan2_7` (`generate_video`). Inputs are the still (`start_image`) and that voice job (`audio_references`).
3. The mp4 comes back with its own audio track. That track is what the mouth was generated against.
4. Temple shots use `kling3_0` and are voice-over. They are not lip-synced.

There is no dedicated lip-sync tool on the Higgsfield connector. `TOOLS` maps image, image-to-video, video, and voice only. `wan2_7` is an image-to-video model that accepts an audio reference. It is not a separate talking-avatar product.

The classic A8 path can call a `lip_sync` capability (`mock-lipsync` in tests, Sync Labs only as a planned provider). The vlog studio does not use that path.

## Lena references

Persona `lena-voss` v2. Higgsfield element `01288044-0746-4b24-8fa8-bea17c4a9233`. Nine ingested stills, hashed in `packages/configurations/personas/lena-voss/persona.v2.yaml` (front, close-up, three-quarter, profile). They guide stills. They are not shown as footage. Voice id is the Juno preset on `text2speech_v2`.

## What the ledger paid for

| Output | Count | Model | Credits | USD |
|---|---:|---|---:|---:|
| Stills | 11 | nano_banana_2 | 22 | 0.95 |
| Voice lines | 11 | text2speech_v2 | 3.75 | 0.16 |
| Talking clips | 5 | wan2_7 | 77.5 | 3.33 |
| Temple clips | 6 | kling3_0 | 84 | 3.61 |
| Planning text | 1 | claude-sonnet-4-5 | 0 | 0.01 |

11 clips were generated. The lunch-joke talking clip was removed from the timeline after the fact. The master plays 4 talking clips and 6 temple clips. Four visual attempts failed on a quote that returned no credit amount (one was a Higgsfield preset notice). Those failures were not charged.

Music in the master is a local theme bed written at render time. It is not a provider generation.

## Talking-clip timing (the lip-sync evidence)

Probed from the stored mp4s. `asset.duration_sec` is empty on all four, so the editor does not slow the picture or the audio (`_sync_tempo` stays 1.0).

| Shot | Shot length | Video stream | Audio in the mp4 | Separate TTS file |
|---|---:|---:|---:|---:|
| scene_01_shot_01 | 5.4s | 5.000s | 5.038s | 3.631s |
| scene_02_shot_02 | 6.6s | 7.000s | 7.035s | 6.113s |
| scene_05_shot_01 | 6.2s | 6.000s | 6.037s | 6.113s |
| scene_06_shot_01 | 8.7s | 9.000s | 9.032s | 7.236s |

Stream start time is 0 on each file. Video and the baked audio differ by about 0.03 to 0.04s, which is container padding, not a drift we introduced.

## Why the mouth and the voice did not match

Two different failures stacked.

**Assembly (fixed on the current master).** The editor used to drop every clip's audio (`concat` video only) and play one narration file per scene, the last voice line, stretched across the whole scene. The mouth had been generated against the mp4's own track. The viewer heard a different file, often the wrong line. The current editor keeps a lip-sync clip's own audio and places each voice-over on its own shot. That re-cut is the master above. It does not spend credits.

**Model and fit (still open).** Even with the right audio:

- The TTS file and the mp4 are not the same length. Wan did not return a clip that matches the voice duration. Example: the hook voice is 3.6s and the clip is 5.0s. Playing the clip audio keeps the mouth with that clip. It does not prove the mouth follows the original Juno file.
- The editor then trims or freezes to the shot length. Shot 1 is 5.4s of timeline over a 5.0s picture, so the last frames hold. Because duration metadata is missing, the picture is not time-stretched to match.
- `wan2_7` plus `audio_references` is the only lip-sync we have. If the mouth is soft, late, or unlike speech, that is the model, not FFmpeg. QC never measures it.

No word timestamps are stored. Approved speech can still be replaced by a later voice attempt. Nothing locks an audio checksum to the clip.

## What V1 already has that V2 should keep

- 10 agents, RQ jobs, approval gates, `PaidCallGuard`, rights gate, asset storage, ledger.
- Per-shot regenerate at the preview, pilot, and final gates (`still`, `voice`, or `clip`).
- Script confirm dialog at the script gate, blocked while facts are still open.
- Captions are off for vlog dialogue (`burn_in` false).
- Lepakshi V1 stays playable. New benchmark work must not change its default model.

## What V1 does not have

- A `TalkingAvatarProvider` interface.
- HeyGen, Runway, or a Higgsfield talking-avatar tool. Do not invent those endpoints.
- A driving-performance video for Runway Act-Two.
- Word-level timestamps, locked approved audio, or an audio/video offset test.
- Shot types beyond A-roll and B-roll. One spoken line becomes one clip.
- Lip-sync, identity, or hand QC. A9 checks profile and duration only.
- Cost per accepted shot. The ledger is cost per committed generation.

## Baseline verdict

The worst mismatch was the edit playing the wrong audio. That is fixed. The remaining problem is that talking shots are Wan image-to-video clips whose length does not match the Juno file, with no measurement of mouth accuracy. A three-model benchmark is the right next step. It should use one locked voice file and must not be treated as the new production default until someone picks a winner.
