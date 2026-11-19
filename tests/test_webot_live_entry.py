"""Verify the candidate's service boundary without calling the macOS driver."""
import tempfile
import unittest
from pathlib import Path

from wechat_control.recommendation_preview import validate_integrated_live


class LiveEntryTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.builds = Path(tmp.name).resolve()
        self.run = self.builds / "unique-run"
        self.resources = self.run / "WeBot.app/Contents/Resources"
        self.resources.mkdir(parents=True)
        (self.resources / "integrated-rehearsal").touch()
        self.driver = self.resources / "wechat-vision-ax"
        self.driver.touch()
        self.driver.chmod(0o700)
        self.profile = self.run / "live-test-123456ab-1234-4567-abcd-1234567890ab.profile"
        self.profile.mkdir(mode=0o700)
        self.args = [str(self.driver), "专用测试会话", "试用期限：试用期七天。"]

    def check(self, data=None, args=None, resources=None):
        validate_integrated_live(data or self.profile, args or self.args, resources=resources or self.resources, builds=self.builds)

    def test_accepts_fresh_local_profile_and_bundled_driver(self):
        self.check()
        self.assertFalse(any(self.profile.iterdir()))

    def test_rejects_reuse_shared_modes_and_location_escape(self):
        (self.profile / "auth.json").touch()
        with self.assertRaisesRegex(ValueError, "private candidate profile"):
            self.check()
        (self.profile / "auth.json").unlink()
        self.profile.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "private candidate profile"):
            self.check()
        other = self.builds / self.profile.name
        other.mkdir(mode=0o700)
        with self.assertRaisesRegex(ValueError, "private candidate profile"):
            self.check(data=other)
        alias = self.run / "live-test-123456ab-1234-4567-abcd-1234567890ac.profile"
        alias.symlink_to(other, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "private candidate profile"):
            self.check(data=alias)

    def test_rejects_invalid_title_knowledge_or_driver(self):
        for title, fact in (("", "fact"), ("-a", "fact"), ("name", " "), ("name", "line\nline"), ("name", "a" * 261)):
            with self.subTest(title=title, fact=fact):
                with self.assertRaisesRegex(ValueError, "precise conversation title"):
                    self.check(args=[str(self.driver), title, fact])
        with self.assertRaisesRegex(ValueError, "bundled native driver"):
            self.check(args=["/bin/true", *self.args[1:]])
        self.driver.unlink()
        self.driver.symlink_to("/bin/true")
        with self.assertRaisesRegex(ValueError, "bundled native driver"):
            self.check()


if __name__ == "__main__":
    unittest.main()
