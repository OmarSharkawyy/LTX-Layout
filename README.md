# LTX Layout

Nuke 16 Gizmo by Omar El Sharkawy for the two-stage LTX-2.5 Layout to Render ComfyUI workflow. The final render is a 16-bit half-float ACEScg EXR sequence. The 2×2 comparison video shows Clay, Look Still, Final Render, and a Clay / Final wipe.

**Development target:** Windows with Nuke 16.0v5. Other Nuke 16 builds and Nuke 17 are compatibility candidates. Nuke 14 and 15 are experimental candidates via PySide2. See the [compatibility matrix](docs/COMPATIBILITY.md) for what has been tested.

## Documentation

- [Installation from scratch and model placement](docs/INSTALLATION.md)
- [Every control and render-folder contents](docs/CONTROLS.md)
- [Compatibility, smoke test, and validation status](docs/COMPATIBILITY.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Repository metadata and draft release notes](REPO_SETUP.md)

## Open in Nuke

Extract the folder. For this session, run this in Nuke's Script Editor with the extracted folder path:

~~~python
nuke.pluginAddPath(r"C:\path\to\LTX_Layout_Studio")
from ltx_layout_studio.bridge import create
create()
~~~

For a permanent menu, put the folder under your .nuke directory and add this line to .nuke/init.py, then restart Nuke:

~~~python
nuke.pluginAddPath("./LTX_Layout_Studio")
~~~

Create the Gizmo from **ComfyUI > LTX Layout** in the Nodes menu.

When updating an existing installation, extract the new files into the existing LTX_Layout_Studio folder, restart Nuke, and create a fresh instance to see the new inputs and controls.

## Render

1. Start your existing ComfyUI installation. The default URL is http://127.0.0.1:8188.
2. Connect the animation branch to **Clay** and the finished first-frame branch to **Look Still**. A Read, FrameHold, or processed Nuke branch works for either input. Choose **First** and **Last**, or click **Use Clay Range**. The Look Still defaults to the first clay frame. Turn off that option to pick a different frame on the Look Still branch.
3. Set the output dimensions and positive prompt. The default is 768×448. Both inputs fit inside the requested canvas without stretching. For 720p delivery, choose 1280×768 and crop the padding in Nuke when your content is 16:9. **Place render at** sets the Read's position on the timeline.
4. Click **Queue Render**. Nuke exports the selected frames at the project FPS, then FFmpeg and the ComfyUI job run in the background. For LTX compatibility the range is trimmed to the nearest supported 8n+1 frame count. Use 49 frames at 24 fps for a roughly two-second test. **Cancel Request** cancels this Gizmo's active request.
5. **Bring Render** loads the EXR sequence as a Read. **Bring Contact Sheet** creates a separate Read for the comparison MP4. Both use **Render folder**. If it contains multiple runs, the Gizmo uses its own current run if present, or the newest available run in the selected folder.

Each run uses a new numbered folder such as **0001** and saves **EXR/Render.####.exr**, **Render.mp4** (review copy), and **ContactSheet.mp4**. If Render folder is blank, the folder defaults to LTXLayoutRenders beside your saved Nuke script or in Documents for an unsaved script. The EXR branch uses decoded LTX frames before video compression. Set the Nuke input colorspace to ACEScg if your config does not expose that name automatically.

Requires the LTX-2.5 Layout to Render nodes and ComfyUI-OCIO with an sRGB input and ACEScg output. Model names are editable on the Models tab. Text encoding runs through the local Gemma text encoder on the selected server.

## Set up on another computer

FFmpeg must provide `libx264`. If it is missing from PATH, open **Settings → Set FFmpeg** to select its executable or **Set ComfyUI Folder** to select the `ComfyUI/main.py` of a local Portable installation with bundled FFmpeg. Unattended setups can use `LTX_LAYOUT_FFMPEG` or `LTX_LAYOUT_COMFY_ROOT`. **Check Setup** checks the selected executable, ComfyUI connection, node types, model filenames, and OCIO colorspaces.

Follow the target-machine test in `install.txt` before marking a new installation as verified. The repository also provides a synthetic integration test:

```powershell
python tests/smoke.py --ffmpeg "path\to\ffmpeg.exe"
```

That test uses real media files and a fixture ComfyUI API. Add `--offline` if loopback networking is restricted. It checks the bridge and file handling without running the LTX model or launching Nuke.

## Licenses

See `LICENSE_LTX_Layout.txt`, `ATTRIBUTION.txt`, and `THIRD_PARTY_LICENSES`. Models and FFmpeg are obtained separately.
