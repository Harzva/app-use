"""Tests for TenantProfileStore and general_sales L1 sales pack."""

import json
import tempfile
import unittest
from pathlib import Path

from wechat_control.sales_crm_hub import STAGES as CRM_STAGES
from wechat_control.tenant_profile import (
    CUSTOMER_BUILD_MARKER,
    TENANT_PROFILE_SCHEMA,
    TenantProfileStore,
    list_sales_packs,
    load_sales_pack,
)


class TenantProfileStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bundle_root = self.root / "bundle"
        self.bundle_root.mkdir()
        self.config_path = self.root / "config" / "tenant_profile.json"

    def test_defaults_legacy_on_dev_repo(self) -> None:
        store = TenantProfileStore(self.config_path, bundle_root=self.bundle_root)
        prof = store.get_profile()
        self.assertEqual(prof["schema"], TENANT_PROFILE_SCHEMA)
        self.assertEqual(prof["mode"], "legacy")
        self.assertEqual(prof["industryPack"], "general_sales")
        self.assertFalse(prof["onboardingCompleted"])
        self.assertEqual(prof["adminContacts"], ["文件传输助手"])
        self.assertEqual(prof["testContacts"], [])
        self.assertFalse(store.is_customer_mode())

    def test_auto_customer_mode_when_marker_exists(self) -> None:
        (self.bundle_root / CUSTOMER_BUILD_MARKER).write_text("1\n", encoding="utf-8")
        store = TenantProfileStore(self.config_path, bundle_root=self.bundle_root)
        prof = store.get_profile()
        self.assertEqual(prof["mode"], "customer")
        self.assertTrue(store.is_customer_mode())

    def test_update_and_complete_onboarding_persists_atomically(self) -> None:
        store = TenantProfileStore(self.config_path, bundle_root=self.bundle_root)
        updated = store.update_profile(
            ownerName="张明",
            ownerAliases=["明哥", " 张明 ", "明哥"],
            businessName="明远茶业",
            productSummary="高端乌龙茶礼盒与企业茶礼定制",
        )
        self.assertEqual(updated["ownerName"], "张明")
        self.assertEqual(updated["ownerAliases"], ["明哥", "张明"])
        self.assertEqual(updated["mode"], "legacy")
        self.assertTrue(self.config_path.is_file())

        done = store.complete_onboarding(
            owner_name="张明",
            business_name="明远茶业",
            product_summary="企业茶礼定制",
            industry_pack="general_sales",
        )
        self.assertEqual(done["mode"], "customer")
        self.assertTrue(done["onboardingCompleted"])
        self.assertTrue(store.is_customer_mode())
        self.assertTrue(bool(done["updatedAt"]))

        reloaded = TenantProfileStore(self.config_path, bundle_root=self.bundle_root).load()
        self.assertEqual(reloaded["businessName"], "明远茶业")
        self.assertEqual(reloaded["mode"], "customer")

    def test_contact_management_methods(self) -> None:
        store = TenantProfileStore(self.config_path, bundle_root=self.bundle_root)
        store.add_test_contact("测试客户A")
        store.add_test_contact("测试客户A (3)")
        store.add_test_contact("测试客户B")
        prof = store.get_profile()
        self.assertEqual(prof["testContacts"], ["测试客户A", "测试客户B"])

        prof = store.remove_test_contact("测试客户A")
        self.assertEqual(prof["testContacts"], ["测试客户B"])

        prof = store.add_admin_contact("老板微信")
        self.assertEqual(prof["adminContacts"], ["文件传输助手", "老板微信"])

        with self.assertRaises(ValueError):
            store.add_test_contact("   ")
        with self.assertRaises(ValueError):
            store.add_admin_contact("")
        with self.assertRaises(ValueError):
            store.update_profile(mode="invalid_mode")


class SalesPackLoaderTest(unittest.TestCase):
    def test_general_sales_pack_structure_and_purity(self) -> None:
        packs_dir = Path("/Volumes/SanDisk/WeChatBot/config_templates/sales_packs")
        packs = list_sales_packs(packs_dir)
        self.assertTrue(any(p["packId"] == "general_sales" for p in packs))

        pack = load_sales_pack("general_sales", packs_dir)
        self.assertEqual(pack["packId"], "general_sales")
        self.assertEqual(pack["name"], "通用私域与顾问式销售")
        self.assertTrue(bool(pack["description"]))

        stage_names = [s["stage"] for s in pack["stages"]]
        expected_stages = [
            "新线索",
            "初步接触",
            "沟通中",
            "深入沟通",
            "已报价",
            "方案推进",
            "已成交",
            "暂缓",
            "高风险转人工",
        ]
        self.assertEqual(stage_names, expected_stages)
        for crm_stage in CRM_STAGES[:-1]:
            self.assertIn(crm_stage, stage_names)
        for stage_obj in pack["stages"]:
            self.assertTrue(stage_obj["goal"].strip())
            self.assertTrue(stage_obj["strategy"].strip())

        entries = pack["entries"]
        self.assertGreaterEqual(len(entries), 14)
        kinds = {e["kind"] for e in entries}
        self.assertEqual(kinds, {"script", "faq", "terminology", "knowledge"})

        serialized = json.dumps(pack, ensure_ascii=False).lower()
        for forbidden in ("wavebot", "openbot", "wechatbot", "安晓心", "心安", "郝哥", "magpie", "fts5", "rpa"):
            self.assertNotIn(forbidden, serialized)

    def test_missing_or_invalid_pack_raises(self) -> None:
        packs_dir = Path("/Volumes/SanDisk/WeChatBot/config_templates/sales_packs")
        with self.assertRaises(FileNotFoundError):
            load_sales_pack("nonexistent_pack", packs_dir)
        with self.assertRaises(ValueError):
            load_sales_pack("../secret", packs_dir)


if __name__ == "__main__":
    unittest.main()
