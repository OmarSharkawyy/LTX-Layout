# Troubleshooting

| Symptom | What to check |
|---|---|
| LTX Layout is missing from Nuke | Check the folder path and single `pluginAddPath` line in `init.py`, then restart Nuke. |
| The panel looks like an older version | Create a fresh node after upgrading the plugin files. |
| Check Setup cannot reach ComfyUI | Open the address in a browser and confirm the hostname, port, and ComfyUI instance. |
| Missing node types or models | Read the names reported by Check Setup. Confirm ComfyUI-LTXVideo and ComfyUI-OCIO loaded in that instance, and use the exact filenames in the Models tab. |
| FFmpeg isn't found | Select it in Settings or choose the appropriate local ComfyUI Portable installation. |
| OCIO errors or unexpected contrast | Confirm OCIO Write exposes an sRGB source and ACEScg output. Check that the imported EXR Read uses ACEScg and the Viewer applies the intended project display transform. |
| Out of memory | Reproduce using nine frames at 512×320, then adjust resolution and duration separately. |
| Model output drifts from the layout | Confirm both inputs have matching framing and that Look Still holds the intended frame. Compare the Clay/Final wipe in the review video. |
| Bring finds an older sequence | Select the exact numbered run directory and confirm its `EXR/` or `ContactSheet.mp4` exists. A new job is unnecessary for re-import. |
| Bring produces the wrong offset | Check **Place render at**. EXRs are numbered from 0001 and are placed at the selected project frame by the Read. |
| Final EXRs exist but the comparison is missing | Check the job status and FFmpeg errors. The EXR output can be available before the comparison MP4 finishes. |
