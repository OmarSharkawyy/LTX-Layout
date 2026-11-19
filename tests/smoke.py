"""Exercise the portable bridge with real media and a local ComfyUI API fixture."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--offline", action="store_true", help="Mock HTTP transport for restricted environments.")
    args = parser.parse_args()
    nuke = types.ModuleType("nuke")
    sys.modules["nuke"] = nuke
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ltx_layout_studio import bridge

    ffmpeg = bridge.find_ffmpeg(args.ffmpeg)
    model_names = {key: f"{key}-fixture.safetensors" for key in bridge.MODEL_INPUTS}
    settings = (128, 128, 42, "Clay figure in winter clothes", "", model_names, "clean_fixture")
    template = bridge.build_prompt("Clay.mp4", "LookStill.png", *settings)
    assert not {"RandomImageFromBatch", "ImageConcatFromBatch", "SaveImage"} & {
        step["class_type"] for step in template.values()
    }, "The contact sheet must not depend on ComfyUI image-grid nodes."
    catalog = {step["class_type"]: {"input": {"required": {}}} for step in template.values()}
    for key, (node_id, field) in bridge.MODEL_INPUTS.items():
        options = [model_names[key]]
        catalog[template[node_id]["class_type"]]["input"]["required"][field] = (
            ["COMBO", {"options": options}] if key in ("layout_lora", "upscaler") else [options]
        )
    catalog["OCIOWrite"] = {"input": {"required": {
        "input_colorspace": [["sRGB - Display"]],
        "output_colorspace": [["ACEScg"]],
    }}}

    def make_media(*arguments):
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *arguments], check=True)

    with tempfile.TemporaryDirectory(prefix="ltx layout clean ") as destination:
        root = Path(destination)
        fixture_video, fixture_exr = root / "Final.mp4", root / "Final.exr"
        make_media("-f", "lavfi", "-i", "testsrc2=size=128x128:rate=24", "-frames:v", "9",
                   "-c:v", "libx264", str(fixture_video))
        make_media("-f", "lavfi", "-i", "color=green:size=128x128", "-frames:v", "1",
                   "-pix_fmt", "gbrpf32le", "-c:v", "exr", "-format", "half",
                   "-update", "1", str(fixture_exr))
        run = bridge.new_render_folder(root / "New render root")
        assert run.name == "0001"
        staging = tempfile.TemporaryDirectory(dir=run)
        try:
            input_dir = Path(staging.name)
            sequence = input_dir / "Clay.%04d.png"
            look = input_dir / "LookStill.png"
            make_media("-f", "lavfi", "-i", "testsrc2=size=128x128:rate=24", "-frames:v", "9",
                       "-start_number", "1001", str(sequence))
            shutil.copyfile(input_dir / "Clay.1001.png", look)
            server_test(bridge, nuke, settings, catalog, run, staging, ffmpeg, sequence,
                        look, fixture_video, fixture_exr, args.offline)
        finally:
            staging.cleanup()
        available = bridge.contact_filters(ffmpeg)
        with patch.object(bridge, "ffmpeg_names", return_value=available - {"xstack"}):
            try:
                bridge.contact_filters(ffmpeg)
            except RuntimeError as error:
                assert "xstack" in str(error)
            else:
                raise AssertionError("Check Setup must detect a missing contact sheet filter.")
        with patch.object(bridge, "contact_filters", return_value=available - {"drawtext"}):
            unlabelled = run / "ContactSheetNoLabels.mp4"
            bridge.make_contact_video(ffmpeg, run / "Clay.mp4", run / "LookStill.png",
                                      run / "Render.mp4", unlabelled, 128, 128, 24, 9)
            assert unlabelled.stat().st_size > 0
        detection_test(bridge, root)
        ffmpeg_check_test(bridge, ffmpeg, root)
        size_test(bridge)
        robustness_test(bridge, nuke, settings, ffmpeg, run, fixture_video, fixture_exr, root)
    print("Portable integration passed: new paths, setup, upload, queue, EXRs, review MP4, both Reads, "
          "and recovery from network, FFmpeg, resume, seed and path problems.")


def detection_test(bridge, root):
    """FFmpeg and ComfyUI folders are found without any Settings input."""
    portable = root / "ComfyUI_windows_portable"
    comfy = portable / "ComfyUI"
    (comfy / "custom_nodes").mkdir(parents=True)
    (comfy / "models").mkdir()
    (comfy / "main.py").write_text("", encoding="utf-8")
    binaries = portable / "python_embeded/Lib/site-packages/imageio_ffmpeg/binaries"
    binaries.mkdir(parents=True)
    bundled = binaries / ("ffmpeg-win-x86_64-v7.1.exe" if bridge.IS_WINDOWS else "ffmpeg-linux-x86_64-v7.1")
    bundled.write_bytes(b"")
    bundled.chmod(0o755)
    for choice in (portable, comfy, comfy / "main.py"):
        assert bridge.comfy_base(choice) == comfy.resolve(), choice
    assert bridge.comfy_base(root / "missing") is None
    assert bridge.find_comfy_root(str(root / "stale path from another PC")) is None

    def server(host, route, *_, **__):
        if route == "/internal/folder_paths":
            return {"custom_nodes": [str(comfy / "custom_nodes")]}
        return {"system": {"argv": ["ComfyUI\\main.py"]}}

    bridge._FOUND.clear()
    with patch.object(bridge.client, "json_request", side_effect=server):
        assert bridge.find_comfy_root("", "http://127.0.0.1:8188") == comfy.resolve()
        assert bridge.find_comfy_root("", "http://10.0.0.5:8188") is None
    nowhere = dict(shutil=patch.object(bridge.shutil, "which", return_value=None),
                   registry=patch.object(bridge, "registry_path_dirs", return_value=[]),
                   known=patch.object(bridge, "known_ffmpeg_dirs", return_value=[]),
                   scan=patch.object(bridge, "scan_comfy_installs", return_value=[]))
    runs = patch.object(bridge, "is_ffmpeg", side_effect=lambda path: Path(path).resolve() == bundled.resolve())
    with nowhere["shutil"], nowhere["registry"], nowhere["known"], nowhere["scan"], runs, \
            patch.dict(sys.modules, {"imageio_ffmpeg": None}), \
            patch.dict(bridge.os.environ, {"LTX_LAYOUT_FFMPEG": ""}):
        bridge._FOUND.clear()
        found = bridge.find_ffmpeg(str(root / "stale ffmpeg.exe"), comfy.resolve())
        assert Path(found) == bundled.resolve(), found
        bridge._FOUND.clear()
        try:
            bridge.find_ffmpeg("")
        except ValueError as error:
            assert "not found" in str(error)
        else:
            raise AssertionError("A machine with no FFmpeg must report it.")
    runs = patch.object(bridge, "is_ffmpeg", side_effect=lambda path: Path(path).resolve() == bundled.resolve())
    with nowhere["shutil"], nowhere["registry"], nowhere["known"], runs, \
            patch.object(bridge, "scan_comfy_installs", return_value=[comfy.resolve()]):
        bridge._FOUND.clear()
        assert Path(bridge.find_ffmpeg("")) == bundled.resolve()
    bridge._FOUND.clear()


def size_test(bridge):
    """Width and Height only take sizes LTX accepts: multiples of 64, at least 128."""
    for typed, expected in ((1900, 1920), (1856, 1856), (1080, 1088), (1110, 1088), (1120, 1152),
                            (100, 128), (0, 128), (-64, 128), (130, 128), (2000.0, 1984)):
        assert bridge.snap_size(typed) == expected, (typed, bridge.snap_size(typed))

    class Knob:
        def __init__(self, value):
            self.saved, self.sets = value, 0

        def value(self):
            return self.saved

        def setValue(self, value):
            self.saved, self.sets = value, self.sets + 1

    node = {"render_width": Knob(1856), "render_height": Knob(1088)}
    bridge.step_size(node, "render_width", 1)
    bridge.step_size(node, "render_height", -1)
    assert (node["render_width"].value(), node["render_height"].value()) == (1920, 1024)
    small = {"render_width": Knob(128)}
    bridge.step_size(small, "render_width", -1)
    assert small["render_width"].value() == 128, "The down arrow must stop at 128."
    odd = {"render_width": Knob(1900)}
    bridge.step_size(odd, "render_width", 1)
    assert odd["render_width"].value() == 1984, "An odd size snaps first, then steps."
    typed = Knob(1900)
    bridge.snap_knob(None, typed)
    assert typed.value() == 1920
    exact = Knob(1920)
    bridge.snap_knob(None, exact)
    assert exact.sets == 0, "A valid size must not be set again."
    for width, height in ((1920, 1088), (128, 128)):
        bridge.build_prompt("Clay.mp4", "LookStill.png", width, height, 1, "", "",
                            {key: "x" for key in bridge.MODEL_INPUTS}, "size")


def ffmpeg_check_test(bridge, ffmpeg, root):
    """A saved path that exists but does not run as FFmpeg must not stop the search."""
    broken = root / "broken" / "ffmpeg.exe"
    broken.parent.mkdir()
    broken.write_bytes(b"MZ this is not a program")  # like a build for another system (WinError 193)
    text = root / "notes" / "ffmpeg.exe"
    text.parent.mkdir()
    text.write_text("not ffmpeg", encoding="utf-8")
    assert bridge.is_ffmpeg(ffmpeg)
    for bad in (broken, text, root / "missing.exe", root):
        assert not bridge.is_ffmpeg(bad), bad

    bridge._FOUND.clear()
    with patch.object(bridge.shutil, "which", return_value=ffmpeg), \
            patch.dict(bridge.os.environ, {"LTX_LAYOUT_FFMPEG": ""}):
        assert Path(bridge.find_ffmpeg(str(broken))) == Path(ffmpeg).resolve()

        class Knob:
            def __init__(self, value):
                self.saved = value

            def value(self):
                return self.saved

            def setValue(self, value):
                self.saved = value

        class Node:
            def __init__(self, value):
                self.knobs = {"ffmpeg_path": Knob(value)}

            def knob(self, name):
                return self.knobs.get(name)

        node = Node(str(broken))
        assert Path(bridge.node_ffmpeg(node)) == Path(ffmpeg).resolve()
        assert node.knob("ffmpeg_path").value() == "", "A broken saved path must be cleared."
        node = Node(str(ffmpeg))
        assert Path(bridge.node_ffmpeg(node)) == Path(ffmpeg).resolve()
        assert node.knob("ffmpeg_path").value() == str(ffmpeg), "A working saved path must be kept."

    bridge._FOUND.clear()
    nowhere = (patch.object(bridge.shutil, "which", return_value=None),
               patch.object(bridge, "registry_path_dirs", return_value=[]),
               patch.object(bridge, "known_ffmpeg_dirs", return_value=[]),
               patch.object(bridge, "scan_comfy_installs", return_value=[]),
               patch.dict(sys.modules, {"imageio_ffmpeg": None}),
               patch.dict(bridge.os.environ, {"LTX_LAYOUT_FFMPEG": ""}))
    for item in nowhere:
        item.start()
    try:
        bridge.find_ffmpeg(str(broken))
    except ValueError as error:
        assert "not a working FFmpeg" in str(error) and str(broken) in str(error), error
    else:
        raise AssertionError("A broken saved FFmpeg with no other build must be reported.")
    finally:
        for item in reversed(nowhere):
            item.stop()
        bridge._FOUND.clear()


def server_test(bridge, nuke, settings, catalog, run, staging, ffmpeg, sequence,
                look, fixture_video, fixture_exr, offline):
    uploads = []
    submitted = []
    events = []

    def fixture_request(path, payload=None):
        if payload is None:
            route = urlsplit(path)
            if route.path == "/view":
                params = parse_qs(route.query)
                assert params["filename"] == ["Final.mp4"]
                return fixture_video.read_bytes()
            values = {"/system_stats": {"system": {}, "devices": []}, "/internal/folder_paths": {},
                      "/object_info": catalog, "/object_info/OCIOWrite": {"OCIOWrite": catalog["OCIOWrite"]},
                      "/history/fixture-job": {"fixture-job": {"status": {"completed": True}, "outputs": {
                          "4852": {"gifs": [{"filename": "Final.mp4", "type": "output", "subfolder": "clean_fixture"}]},
                          "9100": {"count": ["9"]},
                      }}}}
            return json.dumps(values[route.path]).encode("utf8")
        if path == "/upload/image":
            suffix = ".mp4" if b'.mp4"' in payload else ".png"
            uploads.append(suffix)
            return json.dumps({"name": f"fixture{suffix}", "subfolder": "", "type": "input"}).encode("utf8")
        if path == "/prompt":
            prompt = json.loads(payload)["prompt"]
            submitted.append(prompt)
            target = Path(prompt["9100"]["inputs"]["output_folder"])
            assert target == run / "EXR"
            target.mkdir()
            for frame in range(1, 10):
                shutil.copyfile(fixture_exr, target / f"Render.{frame:04d}.exr")
            return b'{"prompt_id": "fixture-job"}'
        raise KeyError(path)

    def exercise(host):
        assert bridge.verify_setup(host, ffmpeg, settings[5]).startswith("Setup passed")
        wrong = {**settings[5], "layout_lora": "missing-lora", "upscaler": "missing-upscaler"}
        try:
            bridge.verify_setup(host, ffmpeg, wrong)
        except RuntimeError as error:
            assert "missing-lora" in str(error) and "missing-upscaler" in str(error)
        else:
            raise AssertionError("Check Setup accepted missing V3 model choices.")
        node_id, field = bridge.MODEL_INPUTS["layout_lora"]
        required = catalog[bridge.build_prompt("Clay.mp4", "LookStill.png", *settings)[node_id]["class_type"]]["input"]["required"]
        with patch.dict(required, {field: ["COMBO", {}]}):
            try:
                bridge.verify_setup(host, ffmpeg, settings[5])
            except RuntimeError as error:
                assert "Could not verify model choices" in str(error)
            else:
                raise AssertionError("An unknown combo schema passed Check Setup.")
        bridge.publish = lambda *args, **kwargs: events.append((args, kwargs))
        bridge.render(("fixture", "fixture-token", "fixture-script"), host, run, None,
                      (Path(staging.name) / "Clay.mp4", look, settings),
                      (staging, ffmpeg, sequence, 1001, 1009, 24, None))

    if offline:
        original = bridge.client.request
        bridge.client.request = lambda host, path, data=None, *_, **__: io.BytesIO(fixture_request(path, data))
        try:
            exercise("http://127.0.0.1:8188")
        finally:
            bridge.client.request = original
    else:
        class FixtureServer(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def reply(self, payload=None):
                data = fixture_request(self.path, payload)
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self.reply()

            def do_POST(self):
                self.reply(self.rfile.read(int(self.headers["Content-Length"])))

        with ThreadingHTTPServer(("127.0.0.1", 0), FixtureServer) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                exercise(f"http://127.0.0.1:{server.server_port}")
            finally:
                server.shutdown()
                thread.join()

    assert events[-1][0][1] == "Complete", events
    assert uploads == [".mp4", ".png"]
    assert submitted[0]["9100"]["inputs"]["images"] == ["5518:5538", 0]
    assert (run / "Render.mp4").read_bytes() == fixture_video.read_bytes()
    assert len(list((run / "EXR").glob("*.exr"))) == 9
    assert (run / "ContactSheet.mp4").stat().st_size > 0

    class Knob:
        def __init__(self, value=""):
            self.data = value

        def value(self):
            return self.data

        setValue = fromUserText = lambda self, value: setattr(self, "data", value)
        values = lambda self: ["ACEScg"]

    class GraphicsNode:
        def __init__(self, **data):
            self.knobs = {key: Knob(value) for key, value in data.items()}

        def knob(self, name):
            return self.knobs.get(name)

        __getitem__ = knob
        xpos = ypos = lambda self: 0
        fullName = lambda self: "LTXLayoutStudio"
        setXYpos = lambda self, *_: None

    root = types.SimpleNamespace(begin=lambda: None, end=lambda: None)
    nuke.root = lambda: root
    nuke.nodes = types.SimpleNamespace(Read=lambda: GraphicsNode(
        file="", colorspace="", frame="", frame_mode="", first=0, last=0, origfirst=0, origlast=0))
    def reject(message):
        raise AssertionError(message)
    nuke.message = reject
    node = GraphicsNode(render_dir=str(run.parent), job_folder="", job_host="",
                        start_at=1001, sheet_path="", video_path="")
    render, sheet = bridge.bring_render(node), bridge.read_sheet(node)
    assert render["file"].value().endswith("/0001/EXR/Render.%04d.exr 1-9")
    assert render["frame"].value() == "1001" and render["colorspace"].value() == "ACEScg"
    assert sheet["file"].value().endswith("/0001/ContactSheet.mp4")

    version_two = bridge.new_render_folder(run.parent, 2)
    assert version_two.name == "0002"
    try:
        bridge.new_render_folder(run.parent, 2)
    except ValueError as error:
        assert "already exists" in str(error)
    else:
        raise AssertionError("Queue must protect an existing version.")
    (version_two / "EXR").mkdir()
    shutil.copyfile(run / "EXR/Render.0001.exr", version_two / "EXR/Render.0001.exr")
    shutil.copyfile(run / "ContactSheet.mp4", version_two / "ContactSheet.mp4")
    node.knobs["output_version"] = Knob(2)
    node["job_folder"].setValue(str(run))
    assert "/0002/EXR/" in bridge.bring_render(node)["file"].value()
    assert bridge.read_sheet(node)["file"].value().endswith("/0002/ContactSheet.mp4")
    node["output_version"].setValue(1)
    bridge.version_up(node)
    assert node["output_version"].value() == 3
    with patch.object(nuke, "message") as message:
        assert bridge.read_sheet(node) is None
        message.assert_called_once()
    node["render_dir"].setValue(str(run))
    assert "/0001/EXR/" in bridge.bring_render(node)["file"].value()
    bridge.version_up(node)
    assert node["output_version"].value() == 3
    assert Path(node["render_dir"].value()) == run.parent

    retry_root = run.parent / "retry"
    retry = GraphicsNode(
        render_dir=str(retry_root), output_version=1, clay_first=1, clay_last=9,
        match_clay_first=True, ffmpeg_path=ffmpeg, server="http://127.0.0.1:8188",
        render_width=128, render_height=128, seed_text="42", positive="", negative="",
        job_status="", **settings[5],
    )
    retry.input = lambda _: object()
    with patch.object(nuke, "root", return_value={"fps": Knob(24)}), \
         patch.object(nuke, "message") as message, \
         patch.object(bridge, "node_portable_root", return_value=None), \
         patch.object(bridge.client, "json_request", side_effect=RuntimeError("offline")) as request, \
         patch.object(bridge, "export_input") as export:
        bridge.queue(retry)
        request.assert_called_once_with("http://127.0.0.1:8188", "/system_stats", timeout=5)
        export.assert_not_called()
        assert not retry_root.exists()
        message.assert_called_once()
    with patch.object(nuke, "root", return_value={"fps": Knob(24)}), \
         patch.object(nuke, "message"), \
         patch.object(bridge, "node_portable_root", return_value=None), \
         patch.object(bridge, "check_server"), \
         patch.object(bridge, "export_input", side_effect=RuntimeError("Nuke export failed")):
        bridge.queue(retry)
        assert not (retry_root / "0001").exists()
    retry_run = bridge.new_render_folder(retry_root, 1)
    (retry_run / "ComfyRun.txt").write_text("fixture", encoding="utf-8")
    worker_staging = tempfile.TemporaryDirectory(dir=retry_run)
    with patch.object(bridge, "check_server", side_effect=RuntimeError("offline after export")), \
         patch.object(bridge, "publish") as publish:
        bridge.render(("fixture", "token", "script"), "http://127.0.0.1:8188", retry_run, None,
                      (Path(worker_staging.name) / "Clay.mp4", look, settings),
                      (worker_staging, ffmpeg, sequence, 1, 9, 24, None))
        assert not retry_run.exists()
        assert publish.call_args.kwargs["terminal"]



def robustness_test(bridge, nuke, settings, ffmpeg, run, fixture_video, fixture_exr, root):
    """Network blips, hung FFmpeg, resumed jobs, bad seeds, and servers that cannot see local folders."""
    seed_test(bridge, nuke)
    transport_test(bridge)
    ffmpeg_timeout_test(bridge, nuke, settings, root)
    exr_location_test(bridge, settings, fixture_exr, root)
    resume_test(bridge, settings, ffmpeg, run, fixture_video, fixture_exr)


def seed_test(bridge, nuke):
    """A seed that is not a whole number gets a clear message, not Python's int() error."""
    assert bridge.parse_seed(" 42 ") == 42
    for text in ("abc", "4.5", "", "   "):
        try:
            bridge.parse_seed(text)
        except ValueError as error:
            assert "Seed" in str(error) and "invalid literal" not in str(error), error
        else:
            raise AssertionError(f"Seed {text!r} was accepted.")

    class Knob:
        def __init__(self, value):
            self.data = value

        def value(self):
            return self.data

        def setValue(self, value):
            self.data = value

    class QueueNode:
        def __init__(self, **knobs):
            self.knobs = {key: Knob(value) for key, value in knobs.items()}

        def __getitem__(self, name):
            return self.knobs[name]

        fullName = lambda self: "LTXSeedTest"
        input = lambda self, index: object()

    node = QueueNode(clay_first=1001, clay_last=1009, match_clay_first=True, look_frame=1001,
                     seed_text="abc", job_status="")
    messages = []
    with patch.object(nuke, "message", messages.append):
        bridge.queue(node)
    assert messages == ["Seed must be a whole number such as 42, not 'abc'."], messages
    assert node["job_status"].value() == "Queue stopped"
    assert "LTXSeedTest" not in bridge.ACTIVE


def transport_test(bridge):
    """Only failures that can clear up are marked transient; HTTP 4xx errors are not retried."""
    release = threading.Event()

    class Reply(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.path == "/stalled":
                self.send_response(200)
                self.send_header("Content-Length", "50")
                self.end_headers()
                self.wfile.flush()
                release.wait(5)
                return
            self.send_response({"/busy": 503, "/missing": 404}.get(self.path, 200))
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
    with ThreadingHTTPServer(("127.0.0.1", 0), Reply) as server:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        host = f"http://127.0.0.1:{server.server_port}"
        try:
            for base, route, transient in ((host, "/busy", True), (host, "/missing", False),
                                           (host, "/stalled", True),
                                           (f"http://127.0.0.1:{closed_port}", "/", True)):
                try:
                    bridge.client.json_request(base, route, timeout=1)
                except bridge.client.TransientError:
                    assert transient, route
                except RuntimeError:
                    assert not transient, route
                else:
                    raise AssertionError(f"{route} did not fail")
        finally:
            release.set()
            server.shutdown()


def ffmpeg_timeout_test(bridge, nuke, settings, root):
    """A hung FFmpeg is stopped with a clear message and never leaves the gizmo busy."""
    quick = dict(FFMPEG_QUICK_SECONDS=1, FFMPEG_BASE_SECONDS=1, FFMPEG_SECONDS_PER_FRAME=0)
    sequence = root / "Clay.%04d.png"

    def hung(arguments, **kwargs):
        raise subprocess.TimeoutExpired(arguments, kwargs["timeout"])

    with patch.multiple(bridge, **quick), patch.object(bridge, "contact_filters", return_value=bridge.CONTACT_FILTERS):
        with patch.object(bridge.subprocess, "run", side_effect=hung) as process:
            for call in (lambda: bridge.ffmpeg_names("ffmpeg", "-filters"),
                         lambda: bridge.encode_clay("ffmpeg", sequence, 1, 9, 24, root / "hung.mp4"),
                         lambda: bridge.make_contact_video("ffmpeg", root / "c.mp4", root / "l.png", root / "r.mp4",
                                                           root / "ContactSheet.mp4", 128, 128, 24, 9)):
                try:
                    call()
                except RuntimeError as error:
                    assert "did not finish within 1 seconds" in str(error), error
                else:
                    raise AssertionError("A hung FFmpeg call returned.")
                assert process.call_args.kwargs["timeout"] == 1
        assert not (root / "ContactSheet.partial.mp4").exists()
        if not bridge.IS_WINDOWS:
            stuck = root / "hung-ffmpeg"
            stuck.write_text("#!/bin/sh\nexec sleep 30\n", encoding="utf-8")
            stuck.chmod(0o755)
            started = time.monotonic()
            try:
                bridge.encode_clay(str(stuck), sequence, 1, 9, 24, root / "hung.mp4")
            except RuntimeError as error:
                assert "did not finish" in str(error), error
            else:
                raise AssertionError("A real hung process was not stopped.")
            assert time.monotonic() - started < 15

    key = "LTXTimeoutTest"
    nuke_root = types.SimpleNamespace(name=lambda: "script", begin=lambda: None, end=lambda: None)

    def failing_render(publish_breaks=False, cleanup_breaks=False):
        statuses = []
        stop = threading.Event()
        bridge.ACTIVE[key] = ("token", stop)

        def publish(context, status, job=None, result=None, terminal=False):
            statuses.append(status)
            if publish_breaks and terminal:
                raise RuntimeError("Nuke is shutting down.")
            bridge.apply_update(context, status, job, result, terminal)

        def cleanup():
            raise PermissionError("locked by another process")

        staging = types.SimpleNamespace(cleanup=cleanup if cleanup_breaks else lambda: None)
        stopped = RuntimeError("FFmpeg did not finish within 1 seconds while trying to encode the clay video.")
        with patch.object(bridge, "publish", publish), patch.object(bridge, "check_server"), \
                patch.object(bridge, "encode_clay", side_effect=stopped), \
                patch.object(nuke, "root", lambda: nuke_root), patch.object(nuke, "toNode", lambda name: None, create=True):
            bridge.render((key, "token", "script"), "http://127.0.0.1:8188", root / "stuck run", None,
                          (root / "c.mp4", root / "l.png", settings),
                          (staging, "ffmpeg", sequence, 1001, 1009, 24, None), stop)
        assert key not in bridge.ACTIVE, "The gizmo stayed on 'already watching a render'."
        return statuses

    assert failing_render()[-1].startswith("Error: FFmpeg did not finish")
    assert failing_render(cleanup_breaks=True)[-1].startswith("Error: FFmpeg did not finish")
    failing_render(publish_breaks=True)


def exr_location_test(bridge, settings, fixture_exr, root):
    """A ComfyUI in WSL or Docker is sent a relative folder and its EXRs are downloaded."""
    catalog = {"OCIOWrite": {"input": {"required": {
        "input_colorspace": [["sRGB - Display"]], "output_colorspace": [["ACEScg"]]}}}}
    shared = root / "ComfyUI where server and Nuke share files" / "custom_nodes"
    shared.mkdir(parents=True)
    other_os = "posix" if os.name == "nt" else "nt"
    folder = root / "Render 0009"
    local = (folder / "EXR").as_posix()
    relative = f"LTXLayoutStudio/{settings[-1]}/EXR"

    def server(os_name, folders):
        def reply(host, route, *_, **__):
            if route == "/system_stats":
                return {"system": {"os": os_name} if os_name else {}}
            if route == "/internal/folder_paths":
                return {"custom_nodes": folders} if folders else {}
            raise AssertionError(route)
        return reply

    def failing(host, route, *_, **__):
        raise RuntimeError("ComfyUI HTTP 404 on " + route)

    cases = (
        ("http://127.0.0.1:8188", server(os.name, [str(shared)]), local),            # same computer
        ("http://localhost:8188", server(other_os, [str(shared)]), relative),        # WSL / Docker Desktop
        ("http://127.0.0.1:8188", server(os.name, [str(root / "only inside the container")]), relative),
        ("http://10.0.0.5:8188", server(os.name, [str(shared)]), relative),          # another computer
        ("http://127.0.0.1:8188", failing, local),                                   # cannot tell: as before
        ("http://127.0.0.1:8188", server(None, None), local),                        # older ComfyUI
    )
    for host, reply, expected in cases:
        with patch.object(bridge.client, "json_request", side_effect=reply):
            prompt = bridge.build_prompt("Clay.mp4", "LookStill.png", *settings)
            assert bridge.add_exr_output(host, prompt, folder, catalog) == relative
        assert prompt["9100"]["inputs"]["output_folder"] == expected, (host, expected)
        assert bridge.exr_in_folder(prompt, folder) == (expected == local)

    downloads = []

    def download(host, item, destination):
        downloads.append(item)
        shutil.copyfile(fixture_exr, destination)

    entry = {"outputs": {"9100": {"count": ["9"]}}}
    with patch.object(bridge.client, "download", side_effect=download):
        first = bridge.fetch_exr("http://127.0.0.1:8188", root / "Render 0010", entry, relative,
                                 threading.Event(), local=False)
    assert first.is_file() and len(downloads) == 9
    assert downloads[0] == {"filename": "Render.0001.exr", "subfolder": relative, "type": "output"}


def resume_test(bridge, settings, ffmpeg, run, fixture_video, fixture_exr):
    """Watching survives network blips, and a resumed job needs no state from the original submit."""
    relative = f"LTXLayoutStudio/{settings[-1]}/EXR"
    downloads = []

    def download(host, item, destination):
        downloads.append(item["filename"])
        shutil.copyfile(fixture_video if item["filename"] == "Final.mp4" else fixture_exr, destination)

    def history(output_folder):
        prompt = bridge.build_prompt("Clay.mp4", "LookStill.png", *settings)
        prompt["9100"] = {"class_type": "OCIOWrite", "inputs": {"output_folder": output_folder}}
        return {"fixture-job": {
            "status": {"completed": True}, "prompt": [1, "fixture-job", prompt, {}, ["4852"]],
            "outputs": {"4852": {"gifs": [{"filename": "Final.mp4", "type": "output", "subfolder": "clean_fixture"}]},
                        "9100": {"count": ["9"]}}}}

    def watch(folder, script, stop=None, retries=5, submission=None):
        """Watch 'fixture-job' (resumed, or submitted when given) with scripted replies; the last reply repeats."""
        events, calls = [], {}

        def json_request(host, route, body=None, **kwargs):
            calls[route] = calls.get(route, 0) + 1
            steps = script.get(route)
            if steps is None:
                return {}
            step = steps.pop(0) if len(steps) > 1 else steps[0]
            if isinstance(step, Exception):
                raise step
            return step() if callable(step) else step

        def publish(context, status, job=None, result=None, terminal=False):
            events.append((status, terminal))

        downloads.clear()
        bridge._FOUND.clear()
        with patch.multiple(bridge, WATCH_RETRY_SECONDS=0, WATCH_POLL_SECONDS=0, WATCH_RETRIES=retries), \
                patch.object(bridge, "publish", publish), \
                patch.object(bridge.client, "json_request", side_effect=json_request), \
                patch.object(bridge.client, "download", side_effect=download), \
                patch.object(bridge.client, "upload", side_effect=lambda host, path: path.name), \
                patch.dict(bridge.os.environ, {"LTX_LAYOUT_FFMPEG": ffmpeg, "LTX_LAYOUT_COMFY_ROOT": ""}):
            bridge.render(("fixture", "token", "script"), "http://127.0.0.1:8188", folder,
                          None if submission else "fixture-job", submission, None, stop or threading.Event())
        return events, calls

    def folder_with(version, inputs=True, frames=False):
        folder = bridge.new_render_folder(run.parent, version)
        if inputs:
            shutil.copyfile(run / "Clay.mp4", folder / "Clay.mp4")
            shutil.copyfile(run / "LookStill.png", folder / "LookStill.png")
        if frames:
            shutil.copytree(run / "EXR", folder / "EXR")
        return folder

    blip = bridge.client.TransientError("Could not reach ComfyUI at http://127.0.0.1:8188: timed out")

    # Blips on both status routes, then a finished job: local EXRs, contact sheet rebuilt.
    folder = folder_with(3, frames=True)
    script = {"/history/fixture-job": [blip, blip, {}, history((folder / "EXR").as_posix())],
              "/queue": [blip, {"queue_running": [[0, "fixture-job"]], "queue_pending": []}]}
    events, calls = watch(folder, script)
    statuses = [status for status, _ in events]
    assert statuses.count("Reconnecting to ComfyUI (1/5)") == 2 and "Reconnecting to ComfyUI (2/5)" in statuses
    assert "Rendering in ComfyUI" in statuses, statuses
    assert events[-1] == ("Complete", True), events
    assert (folder / "ContactSheet.mp4").stat().st_size > 0
    assert (folder / "Render.mp4").read_bytes() == fixture_video.read_bytes()
    assert downloads == ["Final.mp4"]

    # A fresh submission with no export state (no FFmpeg, fps or ComfyUI folder) must not hit a NameError.
    folder = folder_with(6, frames=True)
    ocio = {"OCIOWrite": {"input": {"required": {
        "input_colorspace": [["sRGB - Display"]], "output_colorspace": [["ACEScg"]]}}}}
    events, _ = watch(folder, {"/system_stats": [{"system": {}}], "/object_info/OCIOWrite": [ocio],
                               "/prompt": [{"prompt_id": "fixture-job"}],
                               "/history/fixture-job": [history((folder / "EXR").as_posix())]},
                      submission=(folder / "Clay.mp4", folder / "LookStill.png", settings))
    assert events[-1] == ("Complete (contact sheet not built)", True), events

    # A server that cannot see this folder: frames come back by download, same resume path.
    folder = folder_with(4)
    events, _ = watch(folder, {"/history/fixture-job": [history(relative)]})
    assert events[-1] == ("Complete", True), events
    assert len(list((folder / "EXR").glob("Render.*.exr"))) == 9 and downloads.count("Render.0001.exr") == 1

    # Nothing left to rebuild the contact sheet from: finish cleanly instead of failing.
    folder = folder_with(5, inputs=False, frames=True)
    events, _ = watch(folder, {"/history/fixture-job": [history((folder / "EXR").as_posix())]})
    assert events[-1] == ("Complete (contact sheet not built)", True), events
    assert not (folder / "ContactSheet.mp4").exists()

    # ComfyUI stays unreachable: give up after the retries with a message that says why.
    folder = run.parent / "never created"
    events, calls = watch(folder, {"/history/fixture-job": [blip]}, retries=2)
    assert calls["/history/fixture-job"] == 3, calls
    assert events[-1][1] and events[-1][0].startswith("Error: Lost contact with ComfyUI after 3 attempts"), events

    # A real error from ComfyUI is reported at once, not retried.
    events, calls = watch(folder, {"/history/fixture-job": [RuntimeError("ComfyUI HTTP 404 on /history/fixture-job")]})
    assert calls["/history/fixture-job"] == 1 and events[-1][0].startswith("Error: ComfyUI HTTP 404"), events

    # Cancel pressed while waiting to reconnect cancels the job instead of reporting an error.
    stop = threading.Event()

    def cancel_during_blip():
        stop.set()
        raise blip

    events, _ = watch(folder, {"/history/fixture-job": [cancel_during_blip]}, stop=stop)
    assert events[-1] == ("Request canceled", True), events


if __name__ == "__main__":
    main()
