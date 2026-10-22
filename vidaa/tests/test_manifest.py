import tempfile
import unittest
from pathlib import Path

from detox.manifest import Manifest


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "manifest.json"

    def tearDown(self):
        self.dir.cleanup()

    def test_entry_is_on_disk_before_the_change_is_applied(self):
        entry_id = Manifest(self.path).record(
            kind="menu", target="Enhanced Viewing > ACR", before="On", after="Off",
            undo="Settings > Advanced > Enhanced Viewing > ACR: On")

        reopened = Manifest(self.path).entries()

        self.assertEqual(len(reopened), 1)
        self.assertEqual(reopened[0]["id"], entry_id)
        self.assertEqual(reopened[0]["status"], "pending")
        self.assertEqual(reopened[0]["before"], "On")


class RestoreOrderTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.manifest = Manifest(Path(self.dir.name) / "manifest.json")

    def tearDown(self):
        self.dir.cleanup()

    def _record(self, target):
        return self.manifest.record(kind="dns-deny", target=target, before=None,
                                    after="blocked", undo=f"remove {target}")

    def test_restore_walks_changes_newest_first_and_skips_reverted(self):
        first = self._record("api-logsdk.vidaahub.com")
        second = self._record("rpt-ads.vidaahub.com")
        self._record("recommend-ui.vidaahub.com")
        self.manifest.mark(first, "applied")
        self.manifest.mark(second, "reverted")
        # third stays pending: it may or may not have reached the TV, so restore must still visit it

        targets = [e["target"] for e in self.manifest.to_restore()]

        self.assertEqual(targets, ["recommend-ui.vidaahub.com", "api-logsdk.vidaahub.com"])

    def test_marking_an_unknown_entry_fails_loudly(self):
        with self.assertRaises(KeyError):
            self.manifest.mark("999-menu", "applied")

    def test_rejects_unknown_status(self):
        entry = self._record("x.vidaahub.com")
        with self.assertRaises(ValueError):
            self.manifest.mark(entry, "done-ish")
