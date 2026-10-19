# Cue plan and timing

`render` takes one UTF-8 JSON file. Source and local sample paths are relative to that file. Output identifiers use ASCII letters, numbers, `_`, or `-`. Times are seconds in the **media playback clock**.

```json
{
  "version": 1,
  "id": "projectile-throw",
  "source": "input.mp4",
  "seed": 20261019,
  "peak_dbfs": -2,
  "events": [
    {
      "id": "release",
      "type": "whoosh",
      "at": 0.345,
      "duration": 0.36,
      "gain": 0.14,
      "pan": -0.08,
      "label": "出手破风",
      "params": {"low_hz": 260, "high_hz": 4800}
    }
  ],
  "prompt_notes": {
    "positive": "A compact swish of a small soft object thrown through the air, isolated dry Foley.",
    "negative": "music, speech, vocals, environmental ambience, continuous background noise"
  }
}
```

## Events

Each event needs a unique `id`, a supported `type`, nonnegative `at`, and positive `duration`. Its window must fit inside the source duration. `gain` is relative, 0–4 (default 1); `pan` ranges from -1 left to +1 right (default center). The mix and optional stems share one final gain. Stereo local samples retain their two channels.

| type | params | Sound |
| --- | --- | --- |
| `whoosh` | `low_hz`, `high_hz`, `power` | Short filtered movement sweep |
| `impact` | `material`: `metal`, `blade`, `ceramic`, `body`, `grain` | Brief contact with material resonance |
| `mud` | none | Blunt sticky splat |
| `scatter` | `count` (1–100), `material` | Sparse decaying particles |
| `rotor` | none | Active blade/motor motion |
| `suction` | none | Active liquid siphon |
| `bubble` | none | Brief liquid glug |
| `sample` | `file`, optional `offset` in seconds | Local WAV/FLAC etc.; resampled to 48 kHz and faded |

Noise bands require `0 < low_hz < high_hz < 24000`. The global `peak_dbfs` ceiling ranges from -30 to -1.5; default -2. Empty events produce silence, appropriate for a clip without an audible action.

## GIF frame holds and event clocks

For 39 GIF frames with 38 delays of 40 ms and a final delay of 450 ms:

- Actual duration: **1.970 s**; the last frame begins at **1.520 s**.
- If those 39 visible frames sample an animation uniformly from 0 to 1.6 s, the first frame at/after animation event 0.86 s is index `ceil(0.86 / 1.6 × 38) = 21`.
- Use frame 21's actual GIF PTS, **0.840 s**, as the media cue. Confirm against the rendered frames rather than assuming every exporter uses this sampling rule.
- The WAV contains **94,560 frames per channel**. Its length includes the final hold.
- The 30 fps preview extends only the final frame/silence to **2.000 s**, less than one video-frame difference. This does not time-stretch the WAV or shift an event.

For arbitrary GIFs, use `media.json`'s `frame_starts_seconds` and `frame_durations_seconds`. Inspect the relevant frames when an event's source clock or sampling relation is unknown.

Rendering preserves positive GIF delays including 10 ms frames. The 30 fps preview samples that playback clock, so frames shorter than 1/30 s may be skipped. Odd frame dimensions are padded on the right or bottom by one pixel for H.264/yuv420p compatibility.

## Outputs and verification

Each render creates `ID.wav`, `ID.mp4`, `manifest.json`, `verification.json`, and `cue_sheet.csv`; `--stems` adds `stems/EVENT.wav`. Prompt notes are retained in the manifest. `batch` reads `*.json` from one plan directory, checks unique clip IDs, creates one subfolder per clip, and adds `index.json` and `delivery.zip`.

All generated paths are checked before writing; existing outputs require `--overwrite`. A successful replacement removes only obsolete stems explicitly listed in the old manifest, preserving other files. The batch ZIP includes only the current delivery's generated files.

Technical checks cover PCM format, sample count, finite samples, clipping, exact zero outside declared event windows, preview codecs, audio/video duration and full decode. They do not classify whether a supplied sample contains speech or music. A manifest identifies procedural and local-sample methods without claiming AI generation.
