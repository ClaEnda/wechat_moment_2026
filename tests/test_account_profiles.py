import os
import tempfile
import unittest

from account_profiles import AccountProfileStore


class AccountProfileStoreTests(unittest.TestCase):
    def test_profile_ids_are_stable_for_same_account_path(self):
        with tempfile.TemporaryDirectory() as temp:
            account_dir = os.path.join(temp, "xwechat_files", "wxid_demo")
            first = AccountProfileStore.profile_id_for_path(account_dir)
            second = AccountProfileStore.profile_id_for_path(account_dir)
            other = AccountProfileStore.profile_id_for_path(account_dir + "_other")
            self.assertEqual(first, second)
            self.assertNotEqual(first, other)

    def test_profile_workspaces_are_separated_by_profile_id(self):
        with tempfile.TemporaryDirectory() as temp:
            store = AccountProfileStore(root=temp)
            first = store.workspace_for({"profile_id": "account_one"})
            second = store.workspace_for({"profile_id": "account_two"})
            self.assertNotEqual(first, second)
            self.assertTrue(first.is_dir())
            self.assertTrue(second.is_dir())

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI is required")
    def test_secret_round_trip_uses_protected_blob(self):
        with tempfile.TemporaryDirectory() as temp:
            store = AccountProfileStore(root=temp)
            profile = store.save_profile({
                "account_dir": os.path.join(temp, "wxid_demo"),
                "wxid": "wxid_demo",
                "display_name": "测试账号",
            })
            secret = "ab" * 32
            store.save_secrets(profile["profile_id"], {"sns_db_key": secret})
            restored = store.load_secrets(profile["profile_id"])
            self.assertEqual(restored["sns_db_key"], secret)

            protected_file = store.profile_dir / profile["profile_id"] / "secrets.dpapi"
            self.assertTrue(protected_file.is_file())
            self.assertNotIn(secret.encode("ascii"), protected_file.read_bytes())


if __name__ == "__main__":
    unittest.main()
