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

1. Close Nuke. Extract the ZIP from the `main` branch and copy its `ltx-layout-main` folder into `%USERPROFILE%\.nuke`. Keep the `ltx_layout_studio` Python folder beside `LTXLayoutStudio.gizmo` and `menu.py`.
2. Open `%USERPROFILE%\.nuke\init.py`, or create it if it is missing. Add the block below near the top, keeping the existing startup code. Replace any earlier LTX Layout path entry. The plugin's own `menu.py` registers the command in the ComfyUI menu.

   ```python
   import nuke
   nuke.pluginAddPath("./ltx-layout-main")
   ```

3. Launch Nuke and create **ComfyUI → LTX Layout** from the Nodes toolbar. To update an existing install, update the files inside its existing folder and use a fresh node after restarting Nuke. Older nodes saved in an existing script can retain older controls.
4. In **Settings**, set the ComfyUI URL. If FFmpeg is on PATH, the Gizmo finds it automatically. Otherwise click **Set FFmpeg** and choose `ffmpeg.exe`, or click **Set ComfyUI Folder** and choose the Portable install's `ComfyUI/main.py` to use its bundled binary. FFmpeg needs the `libx264` encoder and the filters used for the 2×2 comparison.
5. Run **Check Setup**. It checks FFmpeg's H.264 encoder and comparison filters, the server, workflow node types and required inputs, model filenames, and available sRGB/ACEScg entries. Run a short render after the check passes.

## 3. Verify a clean installation

Use a short animated Clay clip and a matching Look Still for the same composition. At 24 fps, start with frame range **1001–1009**, output **512×320**, and a new writable **Render folder**. Click **Queue Render** and wait for **Complete**. Confirm these results.

- `0001/EXR/Render.0001.exr` through `Render.0009.exr` exist and have the chosen dimensions.
- `0001/ContactSheet.mp4` plays all nine frames at the project FPS and contains four panels.
- **Bring Render** and **Bring Contact Sheet** each create a Read next to the Gizmo. Both start at **Place render at**.
- Run a second job in the same folder to verify **0002**. Change **Render folder** to a different existing job or base folder and repeat the Bring checks before recording that build as verified.

The repository includes a [fixture-based integration test](COMPATIBILITY.md#automated-bridge-test) for the Python and file workflow.
