import base64
import json
import os
import tempfile
import unittest

from helper.account_profiles import (
    AccountProfileError,
    AccountProfileStore,
    profile_cache_dir,
)


class FakeProtector:
    @staticmethod
    def protect(value):
        return base64.b64encode(("test-protected:" + value).encode("utf-8")).decode("ascii")

    @staticmethod
    def unprotect(value):
        raw = base64.b64decode(value).decode("utf-8")
        prefix = "test-protected:"
        if not raw.startswith(prefix):
            raise ValueError("bad test secret")
        return raw[len(prefix):]


class AccountProfileStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = self.temp.name
        self.data_dir = os.path.join(self.root, "wxid_alpha")
        self.db_dir = os.path.join(self.data_dir, "db_storage")
        os.makedirs(self.db_dir)
        self.path = os.path.join(self.root, "accounts.json")
        self.store = AccountProfileStore(self.path, protector=FakeProtector)

    def tearDown(self):
        self.temp.cleanup()

    def test_secrets_are_not_persisted_as_plaintext(self):
        self.store.save_profile(
            {
                "wxid": "wxid_alpha",
                "display_name": "测试账号",
                "wechat_version": "4.x",
                "account_dir": self.data_dir,
                "db_storage": self.db_dir,
                "process_ids": [1234, "2345"],
            },
            {
                "sns_db_key": "A" * 64,
                "contact_db_key": "B" * 64,
                "image_key": "manual-image-secret",
            },
        )
        raw = open(self.path, "r", encoding="utf-8").read()
        self.assertNotIn("A" * 64, raw)
        self.assertNotIn("B" * 64, raw)
        self.assertNotIn("manual-image-secret", raw)
        self.assertEqual(self.store.get_secrets("wxid_alpha")["sns_db_key"], "A" * 64)
        self.assertEqual(self.store.get_secrets("wxid_alpha")["image_key"], "manual-image-secret")

    def test_profile_metadata_does_not_expose_secret_fields(self):
        self.store.save_profile(
            {
                "wxid": "wxid_alpha",
                "display_name": "测试账号",
                "wechat_version": "4.x",
                "account_dir": self.data_dir,
                "db_storage": self.db_dir,
            },
            {"sns_db_key": "A" * 64, "contact_db_key": "B" * 64},
        )
        profile = self.store.get_profile("wxid_alpha")
        self.assertNotIn("protected_secrets", profile)
        self.assertEqual(profile["process_ids"], [])

    def test_saving_metadata_keeps_existing_protected_secrets(self):
        profile = {
            "wxid": "wxid_alpha",
            "display_name": "旧名称",
            "wechat_version": "4.x",
            "account_dir": self.data_dir,
            "db_storage": self.db_dir,
        }
        self.store.save_profile(profile, {"sns_db_key": "A" * 64, "contact_db_key": "B" * 64})
        profile["display_name"] = "新名称"
        self.store.save_profile(profile, {})
        self.assertEqual(self.store.get_secrets("wxid_alpha")["sns_db_key"], "A" * 64)
        self.assertEqual(self.store.get_profile("wxid_alpha")["display_name"], "新名称")

    def test_each_wxid_gets_a_separate_cache_folder(self):
        first = profile_cache_dir("wxid_alpha", os.path.join(self.root, "cache"))
        second = profile_cache_dir("wxid_beta", os.path.join(self.root, "cache"))
        self.assertNotEqual(first, second)
        self.assertTrue(os.path.isdir(first))
        self.assertTrue(os.path.isdir(second))

    def test_weixin4_requires_existing_database_storage(self):
        with self.assertRaises(AccountProfileError):
            self.store.save_profile(
                {
                    "wxid": "wxid_missing",
                    "wechat_version": "4.x",
                    "account_dir": self.data_dir,
                    "db_storage": os.path.join(self.root, "not-found"),
                },
                {"sns_db_key": "A" * 64, "contact_db_key": "B" * 64},
            )

    def test_legacy_profile_does_not_require_db_storage(self):
        self.store.save_profile(
            {
                "wxid": "wxid_legacy",
                "display_name": "旧版微信",
                "wechat_version": "3.x",
                "account_dir": self.data_dir,
            },
            {"legacy_db_key": "legacy-user-supplied-key"},
        )
        self.assertEqual(
            self.store.get_secrets("wxid_legacy")["legacy_db_key"],
            "legacy-user-supplied-key",
        )


if __name__ == "__main__":
    unittest.main()
