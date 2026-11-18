"""Nuke controls for the LTX Layout to Render workflow."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlparse
import uuid

import nuke

from . import client

TEMPLATE = Path(__file__).with_name("layout_api.json")
MODEL_INPUTS = {
    "transformer": ("5004:5602", "unet_name"),
    "text_encoder": ("5004:5605", "clip_name"),
    "video_vae": ("5004:5601", "vae_name"),
    "layout_lora": ("5004:5606", "lora_name"),
    "upscaler": ("5004:9035", "model_name"),
}
ACTIVE = {}
CONTACT_FILTERS = {"crop", "fps", "hstack", "pad", "scale", "setsar", "split", "tpad", "xstack"}


def new_render_folder(base, version=None):
    base.mkdir(parents=True, exist_ok=True)
    if version is not None:
        folder = version_folder(base, version)
        try:
            folder.mkdir()
        except FileExistsError as error:
            raise ValueError(f"{folder} already exists. Use Version Up Output or choose another version.") from error
        return folder
    number = max((int(item.name) for item in base.iterdir()
                  if item.is_dir() and item.name.isascii() and item.name.isdecimal()), default=0) + 1
    while True:
        path = base / f"{number:04d}"
        try:
            path.mkdir()
            return path
        except FileExistsError:
            number += 1


def version_folder(base, version):
    if version < 1:
        raise ValueError("Output version must be 1 or higher.")
    return base / f"{version:04d}"


def render_base(node):
    override = node["render_dir"].value().strip()
    if override:
        return Path(override).expanduser().resolve()
    project = Path(nuke.root().name())
    if project.suffix.lower() == ".nk":
        return (project.parent / "LTXLayoutRenders").resolve()
    return Path.home() / "Documents" / "LTXLayoutRenders"


def is_render_run(folder):
    return any((folder / name).is_file() for name in (
        "ComfyRun.txt", "Render.mp4", "ContactSheet.mp4", "EXR/Render.0001.exr", "Render.0001.exr",
    ))


def version_up(node):
    knob = node["output_version"]
    try:
        base = render_base(node)
        selected_run = is_render_run(base)
        current = int(knob.value())
        if selected_run:
            if base.name.isascii() and base.name.isdecimal():
                current = int(base.name)
            base = base.parent
        version = max(1, current + 1)
        while version_folder(base, version).exists():
            version += 1
        if selected_run:
            node["render_dir"].setValue(base.as_posix())
        knob.setValue(version)
    except (OSError, ValueError) as error:
        nuke.message(str(error))


@contextmanager
def graph_context(group):
    group.begin()
    try:
        yield
    finally:
        group.end()


def create():
    node = nuke.createNode("LTXLayoutStudio")
    first = int(nuke.frame())
    node["start_at"].setValue(first)
    node["clay_first"].setValue(first)
    node["clay_last"].setValue(first + 48)
    node["look_frame"].setValue(first)
    return node


def build_prompt(clay, look, width, height, seed, positive, negative, models, job_name):
    if min(width, height) < 128 or width % 64 or height % 64:
        raise ValueError("Output width and height must be at least 128 and divisible by 64.")
    if not 0 <= seed < 2**64:
        raise ValueError("Seed must be between 0 and 2^64 - 1.")
    prompt = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    prompt["5001"]["inputs"]["file"] = clay
    prompt["9009"]["inputs"]["image"] = look
    prompt["5548:5026"]["inputs"].update(width=width // 2, height=height // 2)
    prompt["5014:2483"]["inputs"]["text"] = positive
    prompt["5014:2612"]["inputs"]["text"] = negative
    for node_id in ("5516:4832", "9034:9031"):
        prompt[node_id]["inputs"]["noise_seed"] = seed
    for knob, (node_id, field) in MODEL_INPUTS.items():
        prompt[node_id]["inputs"][field] = models[knob]
    prefix = f"LTXLayoutStudio/{job_name}"
    prompt["4852"]["inputs"].update({
        "filename_prefix": prefix + "/Render", "format": "mp4", "format.codec": "h264",
    })
    return prompt


def queue(node):
    if node.fullName() in ACTIVE:
        nuke.message("This gizmo is already watching a render.")
        return
    staging = None
    folder = None
    started = False
    try:
        if node.input(0) is None or node.input(1) is None:
            raise ValueError("Connect both arrows: Clay and Look Still.")
        first, last = int(node["clay_first"].value()), int(node["clay_last"].value())
        if last < first:
            raise ValueError("Clay Last must be at or after First.")
        look_frame = first if node["match_clay_first"].value() else int(node["look_frame"].value())
        # LTX uses inclusive clips of 8n+1 frames.
        last = first + (last - first) // 8 * 8
        if last == first:
            raise ValueError("Select at least 9 clay frames for video generation.")
        fps = float(nuke.root()["fps"].value())
        comfy_root = node_portable_root(node)
        ffmpeg = find_ffmpeg(node["ffmpeg_path"].value(), comfy_root)
        host = node["server"].value().strip().rstrip("/")
        parsed = urlparse(host)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Enter a valid ComfyUI URL, for example http://127.0.0.1:8188.")
        base = render_base(node)
        version_knob = node.knob("output_version")
        version = int(version_knob.value()) if version_knob is not None else None
        if version is not None and is_render_run(base):
            raise ValueError("Choose the parent Render folder before queueing a version.")
        job_name = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
        settings = (int(node["render_width"].value()), int(node["render_height"].value()),
                    int(node["seed_text"].value()), node["positive"].value(),
                    node["negative"].value(),
                    {key: node[key].value().strip() for key in MODEL_INPUTS}, job_name)
        build_prompt("Clay.mp4", "LookStill.png", *settings)
        check_server(host)
        folder = new_render_folder(base, version)
        (folder / "ComfyRun.txt").write_text(job_name, encoding="utf-8")
        staging = tempfile.TemporaryDirectory(prefix="input_", dir=folder)
        inputs = Path(staging.name)
        clay, look = inputs / "Clay.mp4", inputs / "LookStill.png"
        sequence = inputs / "Clay.%04d.png"
        node["job_status"].setValue(f"Exporting clay frames {first}–{last}")
        export_input(node, "Clay", sequence, first, last, *settings[:2])
        node["job_status"].setValue(f"Exporting look frame {look_frame}")
        export_input(node, "Look_Still", look, look_frame, look_frame, *settings[:2])
        start_worker(node, host, folder, None, (clay, look, settings),
                     (staging, ffmpeg, sequence, first, last, fps, comfy_root))
        started = True
    except (OSError, ValueError, RuntimeError) as error:
        node["job_status"].setValue("Queue stopped")
        nuke.message(str(error))
    finally:
        if not started:
            if staging is not None:
                staging.cleanup()
            if folder is not None:
                discard_empty_run(folder)


def discard_empty_run(folder):
    """Remove a newly reserved run with no outputs, leaving any other files alone."""
    marker = folder / "ComfyRun.txt"
    try:
        if any(path != marker for path in folder.iterdir()):
            return
        marker.unlink(missing_ok=True)
        folder.rmdir()
    except OSError:
        pass


def use_clay_range(node):
    clay = node.input(0)
    if clay is None:
        nuke.message("Connect the Clay arrow first.")
        return
    first, last = int(clay.firstFrame()), int(clay.lastFrame())
    node["clay_first"].setValue(first)
    node["clay_last"].setValue(last)
    node["start_at"].setValue(first)


def portable_root(override=""):
    value = override.strip() or os.environ.get("LTX_LAYOUT_COMFY_ROOT", "")
    if not value:
        return None
    path = Path(value).expanduser()
    if path.name.casefold() == "comfyui" and (path / "main.py").is_file():
        path = path.parent
    if not (path / "ComfyUI" / "main.py").is_file():
        raise ValueError("Choose the ComfyUI Portable folder containing ComfyUI/main.py.")
    return path.resolve()


def node_portable_root(node):
    knob = node.knob("comfy_root")
    return portable_root(knob.value() if knob is not None else "")


def find_ffmpeg(override="", comfy_root=None):
    value = override.strip() or os.environ.get("LTX_LAYOUT_FFMPEG", "")
    if value:
        path = Path(value).expanduser()
        if path.is_file():
            return str(path.resolve())
        raise ValueError("FFmpeg override does not point to an existing executable.")
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    if comfy_root is not None:
        binaries = comfy_root / "python_embeded/Lib/site-packages/imageio_ffmpeg/binaries"
        bundled = next(binaries.glob("ffmpeg*.exe"), None)
        if bundled is not None:
            return str(bundled)
    raise ValueError("FFmpeg was not found. In Settings, use Set FFmpeg or Set ComfyUI Folder.")


def set_setup_path(node, kind):
    is_comfy = kind == "comfy"
    title = "Select ComfyUI/main.py" if is_comfy else "Select the FFmpeg executable"
    pattern = "*.py" if is_comfy else "*"
    selected = nuke.getFilename(title, pattern)
    if not selected:
        return
    try:
        if is_comfy:
            value = portable_root(str(Path(selected).parent))
            node["comfy_root"].setValue(str(value))
        else:
            node["ffmpeg_path"].setValue(find_ffmpeg(selected))
    except (OSError, ValueError) as error:
        nuke.message(str(error))


def ffmpeg_names(ffmpeg, listing):
    output = subprocess.check_output(
        [ffmpeg, "-hide_banner", listing], stderr=subprocess.STDOUT, text=True,
        timeout=12, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return {columns[1] for line in output.splitlines()
            if len(columns := line.split()) >= 3}


def contact_filters(ffmpeg):
    available = ffmpeg_names(ffmpeg, "-filters")
    missing = sorted(CONTACT_FILTERS - available)
    if missing:
        raise RuntimeError("FFmpeg is missing contact sheet filters: " + ", ".join(missing) + ". Select a full build.")
    return available


def check_server(host):
    stats = client.json_request(host, "/system_stats", timeout=5)
    if not isinstance(stats, dict) or "system" not in stats:
        raise RuntimeError("That URL did not return ComfyUI system information.")


def combo_choices(spec):
    if isinstance(spec, (list, tuple)) and spec:
        if isinstance(spec[0], list):
            return spec[0]
        if spec[0] == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict):
            options = spec[1].get("options")
            if isinstance(options, list):
                return options
    return None


def verify_setup(host, ffmpeg, models):
    if "libx264" not in ffmpeg_names(ffmpeg, "-encoders"):
        raise RuntimeError("FFmpeg must include the libx264 encoder.")
    contact_filters(ffmpeg)
    check_server(host)
    catalog = client.json_request(host, "/object_info") or {}
    prompt = build_prompt("Clay.mp4", "LookStill.png", 768, 448, 42, "", "", models, "check")
    required = {step["class_type"] for step in prompt.values()} | {"OCIOWrite"}
    missing_nodes = sorted(required - catalog.keys())
    if missing_nodes:
        raise RuntimeError("Missing ComfyUI node types: " + ", ".join(missing_nodes))
    missing_models = []
    unknown_models = []
    for control, (node_id, name) in MODEL_INPUTS.items():
        node_type = prompt[node_id]["class_type"]
        spec = catalog[node_type].get("input", {}).get("required", {}).get(name, [])
        choices = combo_choices(spec)
        if choices is None:
            unknown_models.append(f"{control} ({node_type}.{name})")
        elif models[control] not in choices:
            missing_models.append(f"{control}: {models[control]}")
    model_errors = []
    if missing_models:
        model_errors.append("Model names not found on the server:\n" + "\n".join(missing_models))
    if unknown_models:
        model_errors.append("Could not verify model choices on the server:\n" + "\n".join(unknown_models))
    if model_errors:
        raise RuntimeError("\n\n".join(model_errors))
    add_exr_output(host, prompt, Path("setup_check"), catalog)
    incompatible = set()
    for step in prompt.values():
        node_type = step["class_type"]
        required_inputs = catalog[node_type].get("input", {}).get("required", {})
        missing_inputs = sorted(required_inputs.keys() - step["inputs"].keys())
        if missing_inputs:
            incompatible.add(f"{node_type}: {', '.join(missing_inputs)}")
    if incompatible:
        raise RuntimeError("Installed node versions expect inputs this workflow does not supply:\n"
                           + "\n".join(sorted(incompatible)))
    return f"Setup passed: FFmpeg encoder and contact sheet filters, {len(required)} node types, model filenames, and sRGB to ACEScg."


def check_setup(node):
    try:
        root = node_portable_root(node)
        ffmpeg = find_ffmpeg(node["ffmpeg_path"].value(), root)
        host = node["server"].value().strip().rstrip("/")
        models = {key: node[key].value().strip() for key in MODEL_INPUTS}
    except (OSError, ValueError) as error:
        nuke.message(str(error))
        return

    def run_check():
        try:
            report = verify_setup(host, ffmpeg, models)
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
            report = f"Setup check failed:\n{error}"
        nuke.executeInMainThread(nuke.message, args=(report,))

    threading.Thread(target=run_check, daemon=True, name="LTXLayoutSetup").start()


def export_input(group, input_name, destination, first, last, width, height):
    reformat = writer = None
    group.begin()
    try:
        reformat = nuke.nodes.Reformat(inputs=[group.node(input_name)])
        for name, value in (
            ("type", "to box"), ("box_width", width), ("box_height", height),
            ("box_fixed", True), ("resize", "fit"), ("center", True),
        ):
            reformat[name].setValue(value)
        writer = nuke.nodes.Write(inputs=[reformat])
        writer["file"].setValue(destination.as_posix())
        writer["file_type"].setValue("png")
        writer["channels"].setValue("rgb")
        nuke.execute(writer, first, last)
    finally:
        if writer is not None:
            nuke.delete(writer)
        if reformat is not None:
            nuke.delete(reformat)
        group.end()


def encode_clay(ffmpeg, sequence, first, last, fps, destination):
    args = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-framerate", str(fps), "-start_number", str(first), "-i", str(sequence),
        "-frames:v", str(last - first + 1), "-an", "-c:v", "libx264", "-crf", "16",
        "-pix_fmt", "yuv420p", str(destination),
    ]
    result = subprocess.run(args, capture_output=True, text=True, check=False,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise RuntimeError("Could not encode the clay video. " + result.stderr.strip())


def make_contact_video(ffmpeg, clay, look, video, destination, width, height, fps, frame_count):
    available_filters = contact_filters(ffmpeg)
    panel_width = min(width, 960)
    panel_height = max(2, round(height * panel_width / width / 2) * 2)
    font = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts/segoeui.ttf"
    font_arg = font.as_posix().replace(":", r"\:")
    filters = []
    for index in range(3):
        panel = (f"[{index}:v]fps={fps},"
                 f"scale={panel_width}:{panel_height}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
                 f"pad={panel_width}:{panel_height}:(ow-iw)/2:(oh-ih)/2:color=0x14171a,setsar=1")
        if index == 0:
            panel += ",tpad=stop_mode=clone:stop=-1"
        if index in (0, 2):
            panel += f",split=2[tile{index}][wipe{index}]"
        else:
            panel += "[tile1]"
        filters.append(panel)
    filters.extend((
        "[wipe0]crop=iw/2:ih:0:0[left]",
        "[wipe2]crop=iw/2:ih:iw/2:0[right]",
        "[left][right]hstack=inputs=2:shortest=1[tile3]",
    ))
    layout = "[tile0][tile1][tile2][tile3]"
    if font.is_file() and "drawtext" in available_filters:
        for index, caption in enumerate(("CLAY LAYOUT", "LOOK STILL", "FINAL RENDER", "CLAY / FINAL WIPE")):
            filters.append(f"[tile{index}]drawtext=fontfile='{font_arg}':text='{caption}':"
                           f"fontsize=16:fontcolor=white:box=1:boxcolor=black@0.66:boxborderw=5:x=14:y=14[p{index}]")
        layout = "[p0][p1][p2][p3]"
    filters.append(layout + "xstack=inputs=4:layout=0_0|w0_0|0_h0|w0_h0:shortest=1[out]")
    partial = destination.with_name("ContactSheet.partial.mp4")
    args = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(clay), "-loop", "1", "-framerate", str(fps), "-i", str(look),
        "-i", str(video), "-filter_complex", ";".join(filters), "-map", "[out]",
        "-frames:v", str(frame_count), "-an", "-c:v", "libx264", "-crf", "17", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(partial),
    ]
    result = subprocess.run(args, capture_output=True, text=True, check=False,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        partial.unlink(missing_ok=True)
        raise RuntimeError("Render saved, but the contact sheet failed. " + result.stderr.strip())
    partial.replace(destination)


def local_comfy_render(host, folder, comfy_root=None):
    if comfy_root is None or not is_local_server(host):
        return None
    marker = folder / "ComfyRun.txt"
    run = marker.read_text(encoding="utf-8").strip() if marker.is_file() else folder.name
    if not run or not all(char.isascii() and (char.isalnum() or char == "_") for char in run):
        return None
    output = comfy_root / "ComfyUI/output/LTXLayoutStudio" / run
    return next(iter(sorted(output.glob("Render_*.mp4"), reverse=True)), None)


def is_local_server(host):
    return urlparse(host).hostname in ("127.0.0.1", "localhost", "::1")


def add_exr_output(host, prompt, folder, catalog=None):
    info = catalog if catalog is not None else client.json_request(host, "/object_info/OCIOWrite")
    required = (info or {}).get("OCIOWrite", {}).get("input", {}).get("required", {})
    if "input_colorspace" not in required or "output_colorspace" not in required:
        raise RuntimeError("The ComfyUI server needs the current ComfyUI-OCIO Write node for EXR output.")
    inputs = combo_choices(required["input_colorspace"]) or []
    outputs = combo_choices(required["output_colorspace"]) or []
    source = next((cs for cs in ("sRGB - Display", "sRGB - Texture", "Utility - sRGB - Texture", "sRGB") if cs in inputs), None)
    target = next((cs for cs in ("ACEScg", "ACES - ACEScg") if cs in outputs), None)
    if not source or not target:
        raise RuntimeError("ComfyUI-OCIO needs an sRGB input and an ACEScg output colorspace.")
    relative = prompt["4852"]["inputs"]["filename_prefix"].rsplit("/", 1)[0] + "/EXR"
    output = (folder / "EXR").as_posix() if is_local_server(host) else relative
    prompt["9100"] = {"class_type": "OCIOWrite", "inputs": {
        "images": ["5518:5538", 0], "profile": "none",
        "input_colorspace": source, "output_colorspace": target,
        "container": "sequence", "still_format": "exr", "bit_depth": "16f",
        "compression": "zip", "video_codec": "prores_4444",
        "auto_range": False, "first_frame": 1, "last_frame": 0,
        "start_number": 1, "source_start": 1, "raw_data": False,
        "colorspace_in_name": False, "auto_colorspace": False,
        "output_folder": output, "filename": "Render",
        "write_audio": False, "write_sidecar": False,
    }}
    return relative


def fetch_exr(host, folder, entry, relative, stop):
    count = int(entry["outputs"]["9100"]["count"][0])
    target = folder / "EXR"
    if not is_local_server(host):
        target.mkdir(parents=True, exist_ok=True)
        for frame in range(1, count + 1):
            if stop.is_set():
                return None
            filename = f"Render.{frame:04d}.exr"
            client.download(host, {"filename": filename, "subfolder": relative, "type": "output"}, target / filename)
    if count < 1 or not all((target / f"Render.{frame:04d}.exr").is_file() for frame in range(1, count + 1)):
        raise RuntimeError("ComfyUI reported an EXR render, but some frames are missing.")
    return target / "Render.0001.exr"


def cancel(node):
    active = ACTIVE.get(node.fullName())
    if active is None:
        nuke.message("This gizmo has no active request.")
        return
    active[1].set()
    node["job_status"].setValue("Cancel requested")


def cancel_remote(host, job_id):
    client.json_request(host, "/queue", {"delete": [job_id]})
    client.json_request(host, "/interrupt", {"prompt_id": job_id})
    for _ in range(15):
        state = client.json_request(host, "/queue")
        if not any(item[1] == job_id for key in ("queue_running", "queue_pending")
                   for item in state.get(key, [])):
            return "Request canceled"
        time.sleep(1)
    return "Cancel sent; waiting for ComfyUI to stop"


def start_worker(node, host, folder, job_id, submission, export=None):
    key = node.fullName()
    if key in ACTIVE:
        raise RuntimeError("This gizmo is already watching a render.")
    token = uuid.uuid4().hex
    stop = threading.Event()
    ACTIVE[key] = (token, stop)
    node["job_status"].setValue("Connecting to ComfyUI")
    context = (key, token, nuke.root().name())
    try:
        threading.Thread(target=render, args=(context, host, folder, job_id, submission, export, stop),
                         daemon=True, name="LTXLayoutStudio").start()
    except RuntimeError:
        ACTIVE.pop(key, None)
        raise


def publish(context, status, job=None, result=None, terminal=False):
    nuke.executeInMainThread(apply_update, args=(context, status, job, result, terminal))


def render(context, host, folder, job_id, submission, export=None, stop=None):
    stop = stop if stop is not None else threading.Event()
    submitting = False
    terminal_status = None
    try:
        if submission is not None:
            clay, look, settings = submission
            folder.mkdir(parents=True, exist_ok=True)
            if stop.is_set():
                terminal_status = "Request canceled"
                return
            check_server(host)
            if export is not None:
                _, ffmpeg, sequence, first, last, fps, comfy_root = export
                publish(context, f"Encoding {last - first + 1} clay frames")
                encode_clay(ffmpeg, sequence, first, last, fps, clay)
                clay = clay.replace(folder / "Clay.mp4")
                look = look.replace(folder / "LookStill.png")
                export[0].cleanup()
            if stop.is_set():
                publish(context, "Request canceled", terminal=True)
                return
            publish(context, "Uploading clay and look still")
            prompt = build_prompt(client.upload(host, clay), client.upload(host, look), *settings)
            exr_subfolder = add_exr_output(host, prompt, folder)
            if stop.is_set():
                publish(context, "Request canceled", terminal=True)
                return
            submitting = True
            reply = client.json_request(host, "/prompt", {"prompt": prompt, "client_id": context[1]})
            job_id = reply["prompt_id"]
            publish(context, "Queued in ComfyUI", (job_id, host, folder))
        started = time.monotonic()
        last_status = None
        while time.monotonic() - started < 12 * 3600:
            if stop.is_set():
                publish(context, cancel_remote(host, job_id), terminal=True)
                return
            entry = client.json_request(host, f"/history/{job_id}").get(job_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    messages = status.get("messages", [])
                    details = next((data for event, data in reversed(messages)
                                    if event in {"execution_error", "execution_interrupted"}), {})
                    raise RuntimeError(details.get("exception_message") or "ComfyUI render failed or was interrupted.")
                if status.get("completed"):
                    break
            queue_data = client.json_request(host, "/queue")
            running = any(item[1] == job_id for item in queue_data.get("queue_running", []))
            pending = any(item[1] == job_id for item in queue_data.get("queue_pending", []))
            current = "Rendering in ComfyUI" if running else "Queued in ComfyUI"
            if not running and not pending and not entry:
                if time.monotonic() - started > 30:
                    raise RuntimeError("The job is no longer in ComfyUI's queue or history.")
                current = "Waiting for ComfyUI"
            if current != last_status:
                publish(context, current)
                last_status = current
            stop.wait(3)
        else:
            raise RuntimeError("Stopped watching after 12 hours. Check the job in ComfyUI.")
        publish(context, "Downloading render")
        folder.mkdir(parents=True, exist_ok=True)
        video, sheet = folder / "Render.mp4", folder / "ContactSheet.mp4"
        local_video = local_comfy_render(host, folder, comfy_root)
        if local_video is not None:
            shutil.copyfile(local_video, video)
        else:
            client.download(host, client.find_output(entry, "4852", ".mp4"), video)
        exr = fetch_exr(host, folder, entry, exr_subfolder, stop)
        if exr is not None:
            publish(context, "EXR render ready", result=(exr, None))
        if stop.is_set():
            publish(context, "Post-processing canceled", terminal=True)
            return
        publish(context, "Building contact sheet video")
        frame_count = int(entry["outputs"]["9100"]["count"][0])
        make_contact_video(ffmpeg, clay, look, video, sheet, settings[0], settings[1], fps, frame_count)
        publish(context, "Complete", result=(None, sheet), terminal=True)
    except Exception as error:
        terminal_status = f"Error: {error}"
    finally:
        if export is not None:
            export[0].cleanup()
            if job_id is None and not submitting:
                discard_empty_run(folder)
        if terminal_status is not None:
            publish(context, terminal_status, terminal=True)


def apply_update(context, status, job, result, terminal):
    key, token, project = context
    active = ACTIVE.get(key)
    if active is None or active[0] != token:
        return
    if terminal:
        ACTIVE.pop(key, None)
    if nuke.root().name() != project:
        return
    with graph_context(nuke.root()):
        node = nuke.toNode(key)
    if node is None or node.knob("job_status") is None:
        return
    node["job_status"].setValue(status.splitlines()[0])
    if status.startswith("Error:"):
        nuke.message(status)
    if job:
        job_id, host, folder = job
        node["job_id"].setValue(job_id)
        node["job_host"].setValue(host)
        node["job_folder"].setValue(folder.as_posix())
    if result:
        video, sheet = result
        if sheet is not None:
            node["sheet_path"].setValue(sheet.as_posix())
        if video is not None and node.knob("video_path") is not None:
            node["video_path"].setValue(video.as_posix())
        if video is None:
            return
        try:
            reader = node.node("RenderedVideo")
            load_read(reader, video, int(node["start_at"].value()))
        except (RuntimeError, ValueError) as error:
            node["job_status"].setValue("Saved to disk; Nuke Read needs attention")
            nuke.message(f"Video saved at {video}\n{error}")


def load_read(reader, path, start_at=None):
    if path.suffix.lower() == ".exr":
        frames = sorted(int(item.stem.rsplit(".", 1)[-1]) for item in path.parent.glob("Render.*.exr")
                        if item.stem.rsplit(".", 1)[-1].isdigit())
        if not frames:
            raise ValueError("The render folder has no EXR frames.")
        pattern = (path.parent / "Render.%04d.exr").as_posix()
        try:
            reader["file"].fromUserText(f"{pattern} {frames[0]}-{frames[-1]}")
        except RuntimeError:
            reader["file"].setValue(pattern)
        for knob, value in (("first", frames[0]), ("last", frames[-1]),
                            ("origfirst", frames[0]), ("origlast", frames[-1])):
            reader[knob].setValue(value)
        get_choices = getattr(reader["colorspace"], "values", None)
        choices = get_choices() if get_choices is not None else ()
        color = next((name for name in ("ACEScg", "ACES - ACEScg") if name in choices), None)
        if color:
            reader["colorspace"].setValue(color)
    else:
        reader["file"].fromUserText(path.as_posix())
    if start_at is not None:
        reader["frame_mode"].setValue("start at")
        reader["frame"].setValue(str(start_at))


def bring_file(node, filename, knob_name, x_offset, start_at=None):
    path_knob = node.knob(knob_name)
    recorded = path_knob.value() if path_knob is not None else ""
    saved = node["job_folder"].value()
    folder = Path(saved) if saved else None
    selected = node["render_dir"].value().strip()
    candidates = []
    version_knob = node.knob("output_version")
    if version_knob is not None:
        try:
            base = render_base(node)
            folder = base if selected and is_render_run(base) else version_folder(base, int(version_knob.value()))
        except (OSError, ValueError) as error:
            nuke.message(str(error))
            return
    elif selected:
        base = Path(selected).expanduser().resolve()
        if folder is None or (folder.resolve() != base and folder.resolve().parent != base):
            folder = None
        if folder is None and base.is_dir():
            if any((base / item).is_file() for item in ("Render.mp4", "ContactSheet.mp4", "EXR/Render.0001.exr", "Render.0001.exr")):
                folder = base
            else:
                runs = [item for item in base.iterdir() if item.is_dir()
                        and any((item / name).is_file() for name in ("Render.mp4", "ContactSheet.mp4", "EXR/Render.0001.exr"))]
                folder = max(runs, key=lambda item: item.stat().st_mtime, default=None)
    elif recorded and (Path(recorded).name == filename or (filename == "Render.mp4" and Path(recorded).suffix.lower() == ".exr")):
        candidates.append(Path(recorded))
    if folder is not None:
        if filename == "Render.mp4":
            candidates.extend((folder / "EXR/Render.0001.exr", folder / "Render.0001.exr"))
        candidates.append(folder / filename)
        if filename == "Render.mp4":
            try:
                comfy_root = node_portable_root(node)
            except ValueError:
                comfy_root = None
            local_video = local_comfy_render(node["job_host"].value(), folder, comfy_root)
            if local_video is not None:
                candidates.append(local_video)
    path = next((item for item in candidates if item.is_file()), None)
    if path is None:
        nuke.message(f"{filename} is not available in the selected render folder yet.")
        return
    parent_name, _, _ = node.fullName().rpartition(".")
    with graph_context(nuke.root()):
        parent = nuke.toNode(parent_name) if parent_name else nuke.root()
    if parent is None:
        nuke.message("Could not find the group containing this gizmo.")
        return
    with graph_context(parent):
        reader = nuke.nodes.Read()
        try:
            load_read(reader, path, start_at)
        except (RuntimeError, ValueError) as error:
            nuke.delete(reader)
            nuke.message(f"Could not read {path}: {error}")
            return
        reader.setXYpos(node.xpos() + x_offset, node.ypos() + 85)
    return reader


def bring_render(node):
    return bring_file(node, "Render.mp4", "video_path", -150, int(node["start_at"].value()))


def read_sheet(node):
    return bring_file(node, "ContactSheet.mp4", "sheet_path", 150, int(node["start_at"].value()))
