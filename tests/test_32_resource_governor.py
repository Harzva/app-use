"""resource_governor 资源治理专项测试：jsonl 轮转 / 孤儿快照清理 / govern 汇总。"""
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wechat_control.resource_governor import (
    DEFAULT_JSONL_MAX_BYTES,
    govern,
    prune_orphan_snapshots,
    rotate_jsonl,
)


class RotateJsonlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_under_limit_not_rotated(self):
        p = self.dir / "audit.jsonl"
        p.write_text("x" * 100)
        rep = rotate_jsonl(p, max_bytes=1000)
        self.assertFalse(rep["rotated"])
        self.assertTrue(p.exists())

    def test_over_limit_rotates_and_clears(self):
        p = self.dir / "audit.jsonl"
        p.write_text("line\n" * 1000)
        rep = rotate_jsonl(p, max_bytes=100)
        self.assertTrue(rep["rotated"])
        archive = self.dir / "audit.jsonl.old"
        self.assertTrue(archive.exists())
        self.assertEqual(archive.stat().st_size, p.write_text("") or 0 or len("line\n" * 1000))
        self.assertEqual(p.stat().st_size, 0)

    def test_missing_file_noop(self):
        rep = rotate_jsonl(self.dir / "nope.jsonl")
        self.assertFalse(rep["rotated"])


class PruneSnapshotsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_old_files_removed_recent_kept(self):
        now = time.time()
        old = self.dir / "nav_oldfriend_cur.png"
        fresh = self.dir / "nav_newfriend_cur.png"
        old.write_bytes(b"x" * 50)
        fresh.write_bytes(b"y" * 50)
        import os
        os.utime(old, (now - 10 * 86400, now - 10 * 86400))
        rep = prune_orphan_snapshots(self.dir, max_age_days=7, now_ts=now)
        self.assertEqual(rep["removed"], ["nav_oldfriend_cur.png"])
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())

    def test_protected_prefix_never_removed(self):
        now = time.time()
        p = self.dir / "synth_bubbles.png"
        p.write_bytes(b"z")
        import os
        os.utime(p, (now - 30 * 86400, now - 30 * 86400))
        rep = prune_orphan_snapshots(self.dir, protected_prefixes=("synth_",), now_ts=now)
        self.assertEqual(rep["removed"], [])
        self.assertTrue(p.exists())


class GovernTests(unittest.TestCase):
    def test_govern_reports_all_sections(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "logs" / "snapshots").mkdir(parents=True)
        (root / "logs" / "audit.jsonl").write_text("{}\n")
        (root / "logs" / "monitor_events.jsonl").write_text("{}\n")
        rep = govern(root)
        self.assertTrue(rep["ok"])
        for key in ("rotate_audit.jsonl", "rotate_monitor_events.jsonl", "snapshots", "freedTotalBytes"):
            self.assertIn(key, rep)
        self.assertLess(rep["rotate_audit.jsonl"]["sizeBytes"], DEFAULT_JSONL_MAX_BYTES)


if __name__ == "__main__":
    unittest.main()
