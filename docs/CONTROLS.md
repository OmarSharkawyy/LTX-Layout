# Controls and output

## Main tab

| Control | Behavior |
|---|---|
| Clay input | Animated layout guide from the Nuke graph. |
| Look Still input | Finished appearance reference for the same shot and pose. |
| First / Last | Inclusive input frame range read at the Nuke project's FPS. The end may be trimmed to the largest valid LTX length, `8n+1`. |
| Use Clay Range | Copies the connected Clay range and places the render at its first frame. |
| Match Look Still frame to Clay First | Samples the same timeline frame number on the Look Still input. Turn it off to enable **Look frame**. |
| Look frame | Independent frame on the Look Still input. |
| Positive / Negative | Text describing the intended appearance and features to avoid. |
| Width / Height | Final canvas dimensions. Use multiples of 64, with a minimum of 128 per dimension. |
| Place render at | Starting timeline frame for the imported EXR and contact video. |
| Seed | Noise seed for both sampling stages. |
| Render folder | Parent folder for numbered runs. Choose an existing run directly to use the Bring buttons. |
| Version | Selects the numbered output folder. Version 1 uses 0001. |
| Version Up Output | Selects the next unused version. Click Queue Render to render it. |
| Queue Render | Exports the Nuke inputs, encodes the guide, and submits the job. |
| Cancel Request | Targets this Gizmo's active ComfyUI job. |
| Bring Render | Creates a Read for the EXR sequence. Older runs can fall back to an available render MP4. |
| Bring Contact Sheet | Creates a separate Read for the comparison MP4. |
| Status | Reports export, queue, rendering, post-processing, completion, or an error. |

## Settings and Models

| Control | Behavior |
|---|---|
| ComfyUI URL | Server used for uploads, queueing, history, and downloads. |
| Check Setup | Finds FFmpeg and the local ComfyUI folder automatically, shows them under the button, and checks dependencies and the server's graph/model capabilities. |
| Transformer | LTX-2.5 distilled diffusion weights. |
| Text encoder | Gemma text encoder for prompt conditioning. |
| Video VAE | Guide encoder and output decoder. |
| Layout LoRA | Layout-to-Render adapter. |
| Latent upscaler | Learned ×2 latent upscale before the refine pass. |

See [Installation](INSTALLATION.md#1-prepare-comfyui) for the exact default filenames.

## Run layout

```text
Render folder/
└── 0001/
    ├── Clay.mp4
    ├── LookStill.png
    ├── Render.mp4
    ├── ContactSheet.mp4
    ├── ComfyRun.txt
    └── EXR/
        ├── Render.0001.exr
        └── …
```

`EXR/` contains the 16-bit half-float ACEScg master from the decoded LTX frames. `Render.mp4` is an H.264 review copy. `ContactSheet.mp4` shows Clay and Look Still on top, with Final Render and a Clay/Final wipe below. Both Bring buttons use the selected Version, or the existing run chosen directly in Render folder. Queue Render protects existing versions. Gizmos saved before the Version control was added retain their automatic numbering.
