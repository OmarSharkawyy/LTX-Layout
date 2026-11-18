# LTX Layout

Turn a clay render or playblast into a finished shot from Nuke. Connect the animated layout and a look reference, then click **Queue Render**. ComfyUI runs the two-stage LTX-2.5 workflow in the background. Bring the finished EXRs and the comparison video back into your comp as Read nodes.

## Gizmo

Find **LTX Layout** under **Nodes → ComfyUI**.

| Input | What to connect |
| --- | --- |
| **Clay** | An animated layout, clay render, or playblast that defines the framing and movement. |
| **Look Still** | An art-directed still of the same composition, usually based on the first Clay frame. |

## Requirements

- **Nuke on Windows.** The development target is **Nuke 16.0v5**. See [Nuke compatibility](docs/COMPATIBILITY.md) for the status of other versions.
- **ComfyUI** with [ComfyUI-LTXVideo](https://github.com/Lightricks/ComfyUI-LTXVideo), [ComfyUI-OCIO](https://github.com/SlavaSexton/ComfyUI-OCIO), and the [LTX-2.5 model files](docs/INSTALLATION.md#1-prepare-comfyui).
- **FFmpeg** with `libx264`. Use FFmpeg on PATH or the executable bundled with your ComfyUI Portable installation.

## Install

1. Download the repository from **Code → Download ZIP** and extract it. Rename the extracted folder to `LTX_Layout_Studio` and place it in `%USERPROFILE%\.nuke`. Confirm that `menu.py` and `LTXLayoutStudio.gizmo` are directly inside that folder.
2. Add this line once to `.nuke/init.py`:

   ```python
   nuke.pluginAddPath("./LTX_Layout_Studio")
   ```

3. Start ComfyUI, then restart Nuke and add **ComfyUI → LTX Layout**.
4. Open the gizmo’s **Settings** and check the ComfyUI URL. The default is `http://127.0.0.1:8188`. If FFmpeg is outside PATH, use **Set FFmpeg** to select it, or **Set ComfyUI Folder** to select the Portable install’s `ComfyUI/main.py`. Run **Check Setup** before your first render.

For exact model filenames, dependency setup, and a short verification render, see the [installation guide](docs/INSTALLATION.md). To update, replace the files in your existing plugin folder, restart Nuke, and create a fresh gizmo.

## Use

1. Connect **Clay** and **Look Still**. Click **Use Clay Range** or enter **First** and **Last**. The gizmo samples the Look Still at the first Clay frame by default. Turn off **Match Look Still frame to Clay First** to choose a different frame.
2. Set the prompt, output size, and **Render folder**. The default output is **768×448**. Use multiples of 64 for width and height. LTX may trim the input range to a supported `8n+1` frame count.
3. Click **Queue Render**. Watch **Status** for progress. Use **Cancel Request** to stop this gizmo’s active job.
4. Click **Bring Render** for the EXR sequence or **Bring Contact Sheet** for the comparison MP4. Each button creates a separate Read, starting at **Place render at**.

## Output

Each job creates a numbered folder under **Render folder**, starting at `0001`.

| File | Contents |
| --- | --- |
| `EXR/Render.####.exr` | Final frames in **ACEScg**, 16-bit half-float. |
| `Render.mp4` | H.264 review copy of the final render. |
| `ContactSheet.mp4` | A 2×2 review with Clay and Look Still above, and Final Render and a Clay/Final wipe below. |

Select a specific numbered folder to bring an older render back into Nuke without queueing again. See [Controls and output](docs/CONTROLS.md) for every setting and the full folder structure.

## Documentation

- [Nuke compatibility and smoke test](docs/COMPATIBILITY.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

## Licenses

The original Nuke integration by **Omar El Sharkawy** is [MIT-licensed](LICENSE_LTX_Layout.txt). See [attribution](ATTRIBUTION.txt) and the [upstream license texts](THIRD_PARTY_LICENSES) for the adapted Lightricks workflow and model terms. Model weights and FFmpeg are installed separately.
