# LTX Layout

Turn a clay render or playblast into a finished shot from Nuke. Connect the animated layout and a look reference, then click **Queue Render**. ComfyUI runs the two-stage LTX-2.5 workflow in the background. Bring the finished EXRs and the comparison video back into your comp as Read nodes.

**Setup links** · [Install LTX Layout](#install) · [Download Nuke](https://downloads.foundry.com/nuke) · [Install ComfyUI](https://docs.comfy.org/installation/comfyui_portable_windows) · [LTXVideo nodes](https://github.com/Lightricks/ComfyUI-LTXVideo) · [OCIO nodes](https://github.com/SlavaSexton/ComfyUI-OCIO) · [Model files](docs/INSTALLATION.md#1-prepare-comfyui) · [Download FFmpeg](https://ffmpeg.org/download.html)

## Gizmo

Find **LTX Layout Studio** under **Nodes → ComfyUI**.

| Input | What to connect |
| --- | --- |
| **Clay** | An animated layout, clay render, or playblast that defines the framing and movement. |
| **Look Still** | An art-directed still of the same composition, usually based on the first Clay frame. |

## Requirements

- **Nuke on Windows.** The development target is **Nuke 16.0v5**. See [Nuke compatibility](docs/COMPATIBILITY.md) for the status of other versions.
- **ComfyUI** with [ComfyUI-LTXVideo](https://github.com/Lightricks/ComfyUI-LTXVideo), [ComfyUI-OCIO](https://github.com/SlavaSexton/ComfyUI-OCIO), and the [LTX-2.5 model files](docs/INSTALLATION.md#1-prepare-comfyui).
- [**FFmpeg**](https://ffmpeg.org/download.html) with `libx264` and standard video filters. The gizmo finds it automatically: on PATH, in common install folders (winget, Chocolatey, Scoop, `C:\ffmpeg`), or the copy bundled with ComfyUI. **Check Setup** shows and checks the build it found.

## Install

1. Download the repository from **Code → Download ZIP** and extract it. Copy the extracted `ltx-layout-main` folder into `%USERPROFILE%\.nuke`. Confirm that `menu.py` and `LTXLayoutStudio.gizmo` are directly inside that folder.
2. Open `%USERPROFILE%\.nuke\init.py`, or create it if it is missing. Add this block near the top, keeping the existing contents. If you already added an LTX Layout path, replace that entry.

   ```python
   import nuke
   nuke.pluginAddPath("./ltx-layout-main")
   ```

3. Start ComfyUI, then restart Nuke and add **ComfyUI → LTX Layout Studio**.
4. Open the gizmo’s **Settings** and check the ComfyUI URL. The default is `http://127.0.0.1:8188`. Run **Check Setup** before your first render. It finds FFmpeg and the local ComfyUI folder automatically and shows what it found; you are only asked to pick `ffmpeg.exe` if nothing is found.

For exact model filenames, dependency setup, and a short verification render, see the [installation guide](docs/INSTALLATION.md).

**Updating from an older version?** Move any older LTX Layout folder out of `.nuke` and remove its `pluginAddPath` line first, or the old code keeps loading. See [Update from an older version](docs/INSTALLATION.md#update-from-an-older-version).

## Use

1. Connect **Clay** and **Look Still**. Click **Use Clay Range** or enter **First** and **Last**. The gizmo samples the Look Still at the first Clay frame by default. Turn off **Match Look Still frame to Clay First** to choose a different frame.
2. Set the prompt, output size, and **Render folder**. The default output is **768×448**. Use multiples of 64 for width and height. LTX may trim the input range to a supported `8n+1` frame count.
3. Click **Queue Render**. Watch **Status** for progress. Use **Version Up Output** before rendering a new version. Select an existing **Version** to import its outputs. Use **Cancel Request** to stop this gizmo’s active job.
4. Click **Bring Render** for the EXR sequence or **Bring Contact Sheet** for the comparison MP4. Each button creates a separate Read, starting at **Place render at**.

## Standalone ComfyUI workflow

**ComfyUI-OCIO is optional for the standalone Lightricks workflow** when you only need a video. The current **LTX Layout Nuke gizmo** requires it to write the ACEScg EXR sequence during **Queue Render**, even when you only use the review MP4. [Install ComfyUI-OCIO](https://github.com/SlavaSexton/ComfyUI-OCIO)

The standard Lightricks Layout to Render workflow saves a video. The ACEScg EXR sequence and the 2×2 comparison are outputs added by this Nuke gizmo. [Lightricks workflow guide](https://docs.ltx.io/open-source-model/vfx-post-production/layout-to-render)

A regular SDR clay render or playblast works as input. There is no need to convert the source video to ACES first. When reading SDR footage in Nuke, assign the Read its actual source color space, such as sRGB or Rec.709. The gizmo delivers the final EXR sequence in ACEScg.

## Output

Each job creates a numbered folder under **Render folder**, starting at `0001`.

| File | Contents |
| --- | --- |
| `EXR/Render.####.exr` | Final frames in **ACEScg**, 16-bit half-float. |
| `Render.mp4` | H.264 review copy of the final render. |
| `ContactSheet.mp4` | A 2×2 review with Clay and Look Still above, and Final Render and a Clay/Final wipe below. |

The gizmo builds the Contact Sheet on the Nuke machine with FFmpeg. It uses no ComfyUI Contact Sheet node or KJNodes dependency.

Select a specific numbered folder to bring an older render back into Nuke without queueing again. See [Controls and output](docs/CONTROLS.md) for every setting and the full folder structure.

## Documentation

- [Installation guide](docs/INSTALLATION.md)
- [Controls and output](docs/CONTROLS.md)
- [Nuke compatibility and smoke test](docs/COMPATIBILITY.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

## Licenses

The original Nuke integration by **Omar El Sharkawy** is [MIT-licensed](LICENSE). See [attribution](ATTRIBUTION.txt) and the [upstream license texts](THIRD_PARTY_LICENSES) for the adapted Lightricks workflow and model terms. Model weights and FFmpeg are installed separately.
