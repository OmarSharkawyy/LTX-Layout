# Troubleshooting

| Symptom | What to check |
|---|---|
| LTX Layout is missing from Nuke | Confirm that `LTXLayoutStudio.gizmo` and `menu.py` are directly inside `.nuke/LTX-Layout-main`. Add the `init.py` block below, then restart Nuke. |
| The panel looks like an older version | Create a fresh node after upgrading the plugin files. |
| An older version keeps loading after an update | An older copy is still inside `.nuke`. Follow [Update from an older version](INSTALLATION.md#update-from-an-older-version), then check the path that `bridge.__file__` prints. |
| Check Setup cannot reach ComfyUI | Open the address in a browser and confirm the hostname, port, and ComfyUI instance. |
| Missing node types or models | Read the names reported by Check Setup. Confirm ComfyUI-LTXVideo and ComfyUI-OCIO loaded in that instance, and use the exact filenames in the Models tab. |
| FFmpeg is missing or lacks an encoder/filter | Install a full build (`winget install Gyan.FFmpeg`) and run Check Setup again; it is found automatically. To force a specific build, set the `LTX_LAYOUT_FFMPEG` environment variable to its path. |
| `WinError 193` or another error when FFmpeg starts | The file found does not run as FFmpeg on this computer. The gizmo runs each FFmpeg once with `-version`, skips one that fails, and clears a broken path saved in an older node. Run Check Setup again to use the next working build. |
| Status shows "Reconnecting to ComfyUI" | The connection dropped briefly. The gizmo retries a few times while ComfyUI keeps rendering. If it gives up, the render may still be running: check ComfyUI. |
| FFmpeg "did not finish" | FFmpeg was stopped after a time limit so the gizmo is free again. Try again, or point `LTX_LAYOUT_FFMPEG` at a different FFmpeg build. |
| ComfyUI runs in WSL or Docker | When its filesystem differs from Nuke's, the gizmo detects this and downloads the EXR frames from ComfyUI instead of asking it to write into your render folder. |
| OCIO errors or unexpected contrast | Confirm OCIO Write exposes an sRGB source and ACEScg output. Check that the imported EXR Read uses ACEScg and the Viewer applies the intended project display transform. |
| Out of memory | Reproduce using nine frames at 512×320, then adjust resolution and duration separately. |
| Model output drifts from the layout | Confirm both inputs have matching framing and that Look Still holds the intended frame. Compare the Clay/Final wipe in the review video. |
| Bring finds an older sequence | Select the exact numbered run directory and confirm its `EXR/` or `ContactSheet.mp4` exists. A new job is unnecessary for re-import. |
| Bring produces the wrong offset | Check **Place render at**. EXRs are numbered from 0001 and are placed at the selected project frame by the Read. |
| Final EXRs exist but the comparison is missing | Check the job status and FFmpeg errors. The EXR output can be available before the comparison MP4 finishes. |

## Check the startup path

In `%USERPROFILE%\.nuke\init.py`, place `import nuke` before the plugin path:

```python
import nuke
nuke.pluginAddPath("./LTX-Layout-main")
```

After restarting Nuke, run this in the Script Editor in Python mode:

```python
print(any("ltx-layout-main" in path.lower() for path in nuke.pluginPath()))
```

If it prints `False`, check that the saved file is named `init.py` and its entry matches the extracted folder. You can use the full path to the plugin folder in `nuke.pluginAddPath()` to verify where Nuke is looking.
