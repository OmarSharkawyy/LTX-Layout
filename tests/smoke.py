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
        catalog[template[node_id]["class_type"]]["input"]["required"][field] = [[model_names[key]]]
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
    print("Portable integration passed: new paths, setup, upload, queue, EXRs, review MP4, and both Reads.")


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


if __name__ == "__main__":
    main()
