import os
import tempfile
import unittest
from datetime import date

from helper.media_cache import snapshot_sns_media_cache


class MediaCacheTests(unittest.TestCase):
    def test_snapshot_copies_only_selected_months_into_profile_cache(self):
        with tempfile.TemporaryDirectory() as root:
            account_dir = os.path.join(root, "wxid_alpha")
            source = os.path.join(account_dir, "FileStorage", "Sns", "Cache")
            os.makedirs(os.path.join(source, "2025-01"))
            os.makedirs(os.path.join(source, "2025-02"))
            os.makedirs(os.path.join(source, "2025-03"))
            for month, name in [("2025-01", "a.dat"), ("2025-02", "b.dat"), ("2025-03", "c.dat")]:
                with open(os.path.join(source, month, name), "wb") as handle:
                    handle.write(month.encode("ascii"))

            cache = os.path.join(root, "account_cache", "wxid_alpha", "media_cache")
            copied = snapshot_sns_media_cache(
                account_dir, cache, date(2025, 2, 1), date(2025, 2, 28)
            )
            self.assertEqual(copied, 1)
            self.assertTrue(os.path.isfile(os.path.join(cache, "2025-02", "b.dat")))
            self.assertFalse(os.path.exists(os.path.join(cache, "2025-01", "a.dat")))
            self.assertFalse(os.path.exists(os.path.join(cache, "2025-03", "c.dat")))

    def test_snapshot_is_incremental(self):
        with tempfile.TemporaryDirectory() as root:
            account_dir = os.path.join(root, "wxid_alpha")
            source = os.path.join(account_dir, "FileStorage", "Sns", "Cache", "2025-02")
            os.makedirs(source)
            source_file = os.path.join(source, "asset.bin")
            with open(source_file, "wb") as handle:
                handle.write(b"media")
            cache = os.path.join(root, "cache")
            first = snapshot_sns_media_cache(
                account_dir, cache, date(2025, 2, 1), date(2025, 2, 28)
            )
            second = snapshot_sns_media_cache(
                account_dir, cache, date(2025, 2, 1), date(2025, 2, 28)
            )
            self.assertEqual(first, 1)
            self.assertEqual(second, 0)


if __name__ == "__main__":
    unittest.main()
