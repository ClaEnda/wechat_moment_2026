import os
import tempfile
import unittest

from helper.db_snapshot import copy_sqlite_snapshot


class DatabaseSnapshotTests(unittest.TestCase):
    def test_copies_database_and_wal_sidecars(self):
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "source.db")
            with open(source, "wb") as handle:
                handle.write(b"db-content")
            with open(source + "-wal", "wb") as handle:
                handle.write(b"wal-content")
            with open(source + "-shm", "wb") as handle:
                handle.write(b"shm-content")

            destination = os.path.join(root, "cache", "account.db")
            copy_sqlite_snapshot(source, destination)
            self.assertEqual(open(destination, "rb").read(), b"db-content")
            self.assertEqual(open(destination + "-wal", "rb").read(), b"wal-content")
            self.assertEqual(open(destination + "-shm", "rb").read(), b"shm-content")

    def test_removes_stale_sidecars_when_source_has_none(self):
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "source.db")
            destination = os.path.join(root, "cache", "account.db")
            os.makedirs(os.path.dirname(destination))
            with open(source, "wb") as handle:
                handle.write(b"db-content")
            with open(destination + "-wal", "wb") as handle:
                handle.write(b"old-wal")
            copy_sqlite_snapshot(source, destination)
            self.assertFalse(os.path.exists(destination + "-wal"))
            self.assertTrue(os.path.isfile(destination))


if __name__ == "__main__":
    unittest.main()
