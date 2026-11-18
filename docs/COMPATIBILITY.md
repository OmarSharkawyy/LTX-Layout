# Nuke compatibility

Windows with **Nuke 16.0v5** is the development target. Earlier builds of the tool produced EXR and comparison outputs on the original setup. The portable package passed an isolated fixture test. A complete install and render of that package on an independent machine remains pending.

| Nuke version | Status for this release |
|---|---|
| 16.0v5 on Windows | Development target. Use this version for the first independent test. |
| Other 16.0 builds and 16.1 | Candidate. They share the Nuke 16-era PySide6 interface. Verify the actual build with the clean-install test. |
| 17.x | Candidate. PySide6 support is present. A licensed Nuke 17 GUI test and LTX Queue are still pending. |
| 14.x and 15.x | Experimental candidates. The prompt editor falls back to PySide2. Loading the Gizmo, editing prompts, and completing a render and both Reads remain unverified. |
| 13.x and earlier | Outside the current support target. |
| macOS or Linux Nuke | Unverified. The installation instructions and Portable FFmpeg discovery target Windows. |

Foundry references: [PySide migration in Nuke 16+](https://support.foundry.com/hc/en-us/articles/25604028087570-Q100715-How-to-address-Python-PySide-issues-in-Nuke-16), [Nuke 14.0 release notes](https://learn.foundry.com/nuke/14.0/content/release_notes/nuke_14.0.html), [Nuke 17 release notes](https://learn.foundry.com/nuke/content/release_notes/17.0/nuke_17.0v6_releasenotes.html).

## Automated bridge test

Run from the repository root with Python and a working FFmpeg.

```powershell
python tests/smoke.py --ffmpeg "C:\path\to\ffmpeg.exe"
```

The synthetic test covers multipart upload, the API job lifecycle, EXR files, the comparison MP4, and the two Read callbacks with fixtures. Use `--offline` if your environment blocks loopback. The offline run uses simulated API responses and Nuke callbacks with real EXR and MP4 media. A fixture result does not certify any Nuke GUI or GPU configuration.

## Record a platform result

Record the Nuke build, Windows version, ComfyUI build, LTXVideo and OCIO node versions, GPU/VRAM, FFmpeg version, frame range, output dimensions, EXR count, and whether both Bring buttons worked. Use [the nine-frame acceptance test](INSTALLATION.md#3-verify-a-clean-installation). Omit private file paths and production frames from public reports.
