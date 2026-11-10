"""Real local HTTP delivery checks; byte fixtures stand in for FFmpeg output."""
import hashlib
import json
import sqlite3
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import business_local_pilot as pilot
import business_reel_workbench as reel
from tests import test_business_reel_caption_exports as fixtures


class CaptionDeliveryHTTPTests(unittest.TestCase):
    caption = fixtures.CaptionExportTests.caption
    review = fixtures.CaptionExportTests.review
    choose = fixtures.CaptionExportTests.choose
    fake_render = fixtures.CaptionExportTests.fake_render
    request = fixtures.CaptionExportTests.request

    def setUp(self):
        fixtures.CaptionExportTests.setUp(self)
        disk = sqlite3.connect(self.root / "pilot.db")
        self.c.backup(disk)
        disk.row_factory = sqlite3.Row
        self.addCleanup(disk.close)
        self.c = disk
        self.old_root = pilot.BASE
        pilot.BASE = self.root
        self.addCleanup(setattr, pilot, "BASE", self.old_root)
        server = ThreadingHTTPServer(("127.0.0.1", 0), pilot.Handler)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:" + str(server.server_port)
        self.endpoint = "/api/pilot/reel-workbench/" + self.project

    def http(self, path, body=None, origin="http://127.0.0.1:4185"):
        request = Request(self.url + path, method="POST" if body is not None else "GET",
            headers={"Origin": origin, "X-Clippr-Pilot": "local-only",
                     "Content-Type": "application/json"},
            data=json.dumps(body).encode() if body is not None else None)
        try:
            response = urlopen(request, timeout=120 if path.endswith('/render-captions') else 15)
        except HTTPError as error:
            response = error
        with response:
            value = response.read()
            if response.headers.get_content_type() == "application/json":
                value = json.loads(value)
            return response.status, value

    def test_http_render_preview_and_approved_download_bind_one_file(self):
        request = self.request()
        body = {"variant": "a", "expectedContentSha256": request["expected_content_sha256"],
                "expectedEditRevision": request["expected_edit_revision"],
                "expectedCaptionRevision": request["expected_caption_revision"]}
        code, invalid = self.http(self.endpoint + "/render-captions", {**body, "spendCredits": 1})
        self.assertEqual(code, 400, invalid)
        self.assertEqual(len(self.calls), 0)
        code, result = self.http(self.endpoint + "/render-captions", body)
        self.assertEqual(code, 200, result)
        state = result["project"]
        edit = next(e for e in state["edits"] if e["variant"] == "a")
        self.assertTrue(edit["captionsBakedIntoVideo"])
        code, old = self.http(self.endpoint + "/previews/a?contentSha256=" + body["expectedContentSha256"])
        self.assertEqual(code, 409, old)
        query = "?contentSha256=" + edit["contentSha256"] + "&reviewSetSha256=" + state["reviewSetSha256"]
        code, preview = self.http(self.endpoint + "/previews/a" + query)
        self.assertEqual(code, 200)
        self.assertEqual(hashlib.sha256(preview).hexdigest(), edit["captionExport"]["sha256"])
        code, denied = self.http(self.endpoint + "/deliveries/a" + query)
        self.assertEqual(code, 409, denied)
        self.review("a"); self.review("b"); self.choose()
        code, downloaded = self.http(self.endpoint + "/deliveries/a" + query)
        self.assertEqual(code, 200, downloaded)
        self.assertEqual(downloaded, preview)
        code, forbidden = self.http(self.endpoint + "/deliveries/a" + query, origin="https://external.example")
        self.assertEqual(code, 403, forbidden)
        code, missing = self.http(self.endpoint + "/deliveries/a")
        self.assertEqual(code, 409, missing)
        self.caption("a", "Updated owner copy requires a fresh rendered review")
        code, expired = self.http(self.endpoint + "/deliveries/a" + query)
        self.assertEqual(code, 409, expired)
        self.assertEqual(expired["code"], "stale_review")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(reel.read(self.c, self.project)["customerAllowanceConsumed"], 0)

    def test_real_ffmpeg_captioned_file_reaches_private_http_download(self):
        # Actual local encoding and HTTP bytes; supplied review receipts remain
        # explicitly synthetic, with no customer/content-quality claim.
        import subprocess
        self.render_patch.stop()
        video = self.folder_path / "a-1.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=720x1280:rate=24:duration=6",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=6",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart",
            "-shortest", str(video)], check=True, capture_output=True, timeout=30)
        self.c.execute("UPDATE business_reel_edits SET sha256=?,bytes=? WHERE project_id=? AND variant='a'",
            (hashlib.sha256(video.read_bytes()).hexdigest(), video.stat().st_size, self.project))
        self.c.commit()
        request = self.request()
        body = {"variant": "a", "expectedContentSha256": request["expected_content_sha256"],
                "expectedEditRevision": request["expected_edit_revision"],
                "expectedCaptionRevision": request["expected_caption_revision"]}
        code, result = self.http(self.endpoint + "/render-captions", body)
        self.assertEqual(code, 200, result)
        self.review("a"); self.review("b"); selected = self.choose()
        edit = next(e for e in selected["edits"] if e["variant"] == "a")
        query = "?contentSha256=" + edit["contentSha256"] + "&reviewSetSha256=" + selected["reviewSetSha256"]
        code, data = self.http(self.endpoint + "/deliveries/a" + query)
        self.assertEqual(code, 200)
        self.assertEqual(hashlib.sha256(data).hexdigest(), edit["captionExport"]["sha256"])
        delivered = self.root / "downloaded-synthetic-review.mp4"
        delivered.write_bytes(data)
        probe = json.loads(subprocess.check_output(["ffprobe", "-v", "error",
            "-show_streams", "-show_format", "-of", "json", str(delivered)], timeout=10))
        self.assertEqual({stream["codec_type"] for stream in probe["streams"]}, {"video", "audio"})
        visual = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
        self.assertEqual((visual["width"], visual["height"]), (720, 1280))
        self.assertAlmostEqual(float(probe["format"]["duration"]), 6, delta=.15)
        self.assertEqual(len(self.calls), 0)

    def test_missing_fields_and_invalid_variant_fail_without_rendering(self):
        for body in ({}, {"variant": "a"}, {
            "variant": "../a", "expectedContentSha256": "0"*64,
            "expectedEditRevision": 1, "expectedCaptionRevision": 1}):
            code, error = self.http(self.endpoint + "/render-captions", body)
            self.assertIn(code, (400, 409), error)
        self.assertEqual(len(self.calls), 0)


if __name__ == "__main__":
    unittest.main()
