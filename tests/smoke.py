"""Exercise the portable bridge with real media and a local ComfyUI API fixture."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
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
    print("Portable integration passed: new paths, setup, upload, queue, EXRs, review MP4, and both Reads.")


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
    with nowhere["shutil"], nowhere["registry"], nowhere["known"], nowhere["scan"], \
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
    with nowhere["shutil"], nowhere["registry"], nowhere["known"], \
            patch.object(bridge, "scan_comfy_installs", return_value=[comfy.resolve()]):
        bridge._FOUND.clear()
        assert Path(bridge.find_ffmpeg("")) == bundled.resolve()
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
            values = {"/system_stats": {"system": {}, "devices": []},
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


if __name__ == "__main__":
    main()
