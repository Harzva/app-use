"""io_utils 原子写专项测试：崩溃安全、并发写、旧文件不破坏。"""
import json
import threading
import unittest
import tempfile
from pathlib import Path

from wechat_control.io_utils import atomic_write_json, atomic_write_text


class AtomicWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_write_and_read_roundtrip(self):
        p = self.dir / "state.json"
        atomic_write_json(p, {"a": 1, "列表": ["中文", "ok"]})
        self.assertEqual(json.loads(p.read_text(encoding="utf-8")), {"a": 1, "列表": ["中文", "ok"]})
        # 默认带换行、无 tmp 残留
        self.assertTrue(p.read_text().endswith("\n"))
        self.assertFalse(list(self.dir.glob("*.tmp")), f"tmp 残留: {list(self.dir.glob('*.tmp'))}")

    def test_newline_false_no_trailing_newline(self):
        p = self.dir / "meta.json"
        atomic_write_json(p, {"x": 1}, newline=False)
        self.assertFalse(p.read_text().endswith("\n"))

    def test_serialization_failure_keeps_old_file(self):
        """序列化失败（不可 JSON 化对象）不能破坏旧文件。"""
        p = self.dir / "precious.json"
        atomic_write_json(p, {"v": 1})
        before = p.read_text()
        with self.assertRaises(TypeError):
            atomic_write_json(p, {"bad": object()})
        self.assertEqual(p.read_text(), before)

    def test_overwrite_replaces_content_atomically(self):
        p = self.dir / "counter.json"
        for i in range(50):
            atomic_write_json(p, {"i": i})
            self.assertEqual(json.loads(p.read_text())["i"], i)

    def test_concurrent_writers_never_produce_truncated_json(self):
        """多线程并发写同一文件：每次读到的都应是完整 JSON。"""
        p = self.dir / "race.json"
        atomic_write_json(p, {"seed": True})
        errors = []

        def writer(tid):
            for i in range(30):
                try:
                    atomic_write_json(p, {"writer": tid, "i": i, "pad": "x" * 200})
                except Exception as exc:  # pragma: no cover
                    errors.append(exc)

        def reader():
            for _ in range(120):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    if not isinstance(data, dict):
                        errors.append(f"corrupt: {data!r}")
                except json.JSONDecodeError as exc:
                    errors.append(f"truncated JSON: {exc}")
                except FileNotFoundError:
                    errors.append("missing file during replace")

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
        threads += [threading.Thread(target=reader) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])

    def test_atomic_write_text_unicode(self):
        p = self.dir / "note.txt"
        atomic_write_text(p, "中文内容 emoji ✨")
        self.assertEqual(p.read_text(encoding="utf-8"), "中文内容 emoji ✨")

    def test_creates_parent_dirs(self):
        p = self.dir / "deep" / "nested" / "state.json"
        atomic_write_json(p, {"ok": True})
        self.assertTrue(p.exists())


if __name__ == "__main__":
    unittest.main()
