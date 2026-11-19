# Installation on Windows

## 1. Prepare ComfyUI

1. Install or update [ComfyUI for Windows](https://docs.comfy.org/installation/comfyui_portable_windows). This release targets Nuke 16.0v5 on Windows. See [Compatibility](COMPATIBILITY.md) for other hosts.
2. Install [ComfyUI-LTXVideo](https://github.com/Lightricks/ComfyUI-LTXVideo) and [ComfyUI-OCIO](https://github.com/SlavaSexton/ComfyUI-OCIO) in the ComfyUI instance the Gizmo will contact. Install their dependencies using that instance's Python, then restart ComfyUI. LTX Layout has its own Nuke plugin folder and uses these upstream nodes on the ComfyUI side.
3. Download the five files below. Check the [official LTX guide](https://docs.ltx.io/open-source-model/vfx-post-production/layout-to-render) and the [Layout to Render adapter](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render). The bundled graph is silent and its loader does not reference the audio VAE.

| Gizmo field | Default filename | Under ComfyUI/models |
|---|---|---|
| Transformer | `ltx-2.5-22b-distilled-transformer-bf16.safetensors` | `diffusion_models/` |
| Text encoder | `gemma4-12b-with-proj-ltx-2.5-bf16.safetensors` | `text_encoders/` |
| Video VAE | `ltx-2.5-video-vae-bf16.safetensors` | `vae/` |
| Layout LoRA | `ltx-2.5-22b-ic-lora-layout-to-render-1.0.safetensors` | `loras/` |
| Latent upscaler | `ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors` | `latent_upscale_models/` |

4. Start ComfyUI and confirm it opens. On the same machine the default URL is `http://127.0.0.1:8188`. The machine running ComfyUI needs the GPU and model files. The machine running Nuke needs [FFmpeg](https://ffmpeg.org/download.html) and access to the selected render folder. The 2×2 Contact Sheet runs through FFmpeg after rendering, with no extra ComfyUI custom nodes.

## 2. Install the Nuke plugin

1. Close Nuke. Download `LTX_Layout_Nuke16.zip` from the [latest release](https://github.com/OmarSharkawyy/LTX-Layout/releases/latest), or the ZIP of the `main` branch, and extract it. Copy its `LTX-Layout-main` folder into `%USERPROFILE%\.nuke`. Keep the `ltx_layout_studio` Python folder beside `LTXLayoutStudio.gizmo` and `menu.py`.
2. Open `%USERPROFILE%\.nuke\init.py`, or create it if it is missing. Add the block below near the top, keeping the existing startup code. Replace any earlier LTX Layout path entry. The plugin's own `menu.py` registers the command in the ComfyUI menu.

   ```python
   import nuke
   nuke.pluginAddPath("./LTX-Layout-main")
   ```

3. Launch Nuke and create **ComfyUI → LTX Layout Studio** from the Nodes toolbar. If the ComfyUI menu does not exist yet, the plugin adds it with the ComfyUI icon. To update an earlier install, follow [Update from an older version](#update-from-an-older-version).
4. In **Settings**, set the ComfyUI URL. The Gizmo finds FFmpeg and the ComfyUI folder by itself: it asks a ComfyUI running on this machine where it is installed, checks PATH (including PATH changes made after you logged in), common install folders (winget, Chocolatey, Scoop, `C:\ffmpeg`, Program Files, Downloads), and the FFmpeg bundled with ComfyUI Portable or ComfyUI Desktop. Only if nothing is found does it ask you to pick `ffmpeg.exe`. FFmpeg needs the `libx264` encoder and the filters used for the 2×2 comparison. Advanced: the `LTX_LAYOUT_FFMPEG` and `LTX_LAYOUT_COMFY_ROOT` environment variables override the search.
5. Run **Check Setup**. It checks FFmpeg's H.264 encoder and comparison filters, the server, workflow node types and required inputs, model filenames, and available sRGB/ACEScg entries. Run a short render after the check passes.

## 3. Verify a clean installation

Use a short animated Clay clip and a matching Look Still for the same composition. At 24 fps, start with frame range **1001–1009**, output **512×320**, and a new writable **Render folder**. Click **Queue Render** and wait for **Complete**. Confirm these results.

- `0001/EXR/Render.0001.exr` through `Render.0009.exr` exist and have the chosen dimensions.
- `0001/ContactSheet.mp4` plays all nine frames at the project FPS and contains four panels.
- **Bring Render** and **Bring Contact Sheet** each create a Read next to the Gizmo. Both start at **Place render at**.
- Click **Version Up Output** and run a second job in the same folder to verify **0002**. Change **Render folder** to a different existing job or base folder and repeat the Bring checks before recording that build as verified.

The repository includes a [fixture-based integration test](COMPATIBILITY.md#automated-bridge-test) for the Python and file workflow.

## Update from an older version

Python loads the first `ltx_layout_studio` it finds, so an older copy left inside `.nuke` keeps running even after the new files are installed. Remove the old copy before you install the new one.

1. Close Nuke completely.
2. In `%USERPROFILE%\.nuke`, look for an older copy of the tool:
   - an `LTX_Layout_Studio` folder from the `v0.1.0-rc.1` release ZIP,
   - an `ltx_layout_studio` folder placed directly in `.nuke`,
   - or an earlier `LTX-Layout-main` folder.

   Move it out of `.nuke`, for example to `Documents`, and keep it as a backup until the new version works. Do not leave it anywhere inside `.nuke`.
3. Open `%USERPROFILE%\.nuke\init.py` and `%USERPROFILE%\.nuke\menu.py`. Remove every `nuke.pluginAddPath(...)` line that points at an old LTX Layout folder, such as `./LTX_Layout_Studio`. Keep a single entry in `init.py`:

   ```python
   import nuke
   nuke.pluginAddPath("./LTX-Layout-main")
   ```

4. Copy the new `LTX-Layout-main` folder into `%USERPROFILE%\.nuke`, as in [Install the Nuke plugin](#2-install-the-nuke-plugin).
5. Start Nuke and create a fresh **LTX Layout Studio** node. Nodes saved in older scripts keep their older controls.
6. To confirm which copy is running, open the Script Editor in Python mode and run:

   ```python
   from ltx_layout_studio import bridge
   print(bridge.__file__)
   ```

   The path must end in `LTX-Layout-main\ltx_layout_studio\bridge.py`. If it shows another folder, that older copy is still inside `.nuke`.
