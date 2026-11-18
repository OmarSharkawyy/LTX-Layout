# Repository details

| Field | Suggested value |
|---|---|
| Repository name | `ltx-layout` |
| Display name | LTX Layout |
| Author | Omar El Sharkawy |
| Description | Nuke Gizmo for LTX-2.5 Layout to Render through ComfyUI, with ACEScg OpenEXR delivery and 2×2 video comparisons. |
| Default branch | `main` |
| Topics | `nuke`, `nuke-gizmo`, `comfyui`, `ltx-video`, `vfx`, `compositing`, `openexr`, `acescg`, `layout-to-render` |
| Release label | Release candidate. |

## Draft release notes

LTX Layout connects Nuke's Clay and Look Still branches to Lightricks' LTX-2.5 Layout to Render workflow in ComfyUI. It outputs numbered ACEScg EXRs and a 2×2 comparison MP4, with separate Read import buttons for each. The package includes setup checks for dependencies and model filenames, along with a reproducible integration test.

Windows and Nuke 16.0v5 are the development target. See the [compatibility matrix](docs/COMPATIBILITY.md) and [clean-install check](docs/INSTALLATION.md#3-verify-a-clean-installation).

The original integration is MIT-licensed under Omar El Sharkawy. The adapted Lightricks workflow and independently installed model weights have their own terms. Keep `ATTRIBUTION.txt`, `LICENSE_LTX_Layout.txt`, and `THIRD_PARTY_LICENSES/` in the repository.
