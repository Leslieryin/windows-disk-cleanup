# -*- coding: utf-8 -*-
"""只测纯逻辑与安全边界。测试不触碰真实文件，不会删任何东西。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cleanup
import report
import rules as R


class TestLevels(unittest.TestCase):
    def test_order_is_increasing(self):
        self.assertLess(R.Level.SAFE.order, R.Level.CAUTION.order)
        self.assertLess(R.Level.CAUTION.order, R.Level.RISKY.order)

    def test_rules_up_to_is_inclusive(self):
        safe = R.rules_up_to(R.Level.SAFE)
        caution = R.rules_up_to(R.Level.CAUTION)
        risky = R.rules_up_to(R.Level.RISKY)
        self.assertTrue(all(r.level is R.Level.SAFE for r in safe))
        self.assertIn(R.Level.CAUTION, {r.level for r in caution})
        self.assertNotIn(R.Level.RISKY, {r.level for r in caution})
        self.assertEqual(len(risky), len(R.RULES))
        self.assertLess(len(safe), len(caution))
        self.assertLess(len(caution), len(risky))

    def test_rule_keys_unique(self):
        keys = [r.key for r in R.RULES]
        self.assertEqual(len(keys), len(set(keys)), "规则 key 不能重复")


class TestExpandAndClassify(unittest.TestCase):
    def test_env_var_expanded(self):
        os.environ["WDCTEST_ROOT"] = r"C:\fake\root"
        try:
            self.assertEqual(R.expand(r"%WDCTEST_ROOT%\sub"),
                             os.path.normpath(r"C:\fake\root\sub"))
        finally:
            del os.environ["WDCTEST_ROOT"]

    def test_unknown_var_kept(self):
        # 展开失败的变量要原样保留，便于报错时定位
        self.assertIn("%NO_SUCH_VAR_XYZ%", R.expand(r"%NO_SUCH_VAR_XYZ%\x"))

    def test_kind_of(self):
        self.assertEqual(R.kind_of("a/b/电影.MKV"), "视频")   # 大小写不敏感
        self.assertEqual(R.kind_of("model.gguf"), "模型/权重")
        self.assertEqual(R.kind_of("backup.7z"), "镜像/安装包")
        self.assertEqual(R.kind_of("unknownext.xyz"), "其他")
        self.assertEqual(R.kind_of("无扩展名"), "其他")

    def test_filtered_rule_keeps_directory(self):
        thumb = next(r for r in R.RULES if r.key == "thumbcache")
        self.assertTrue(thumb.is_filtered)
        self.assertTrue(any("thumbcache" in p for p in thumb.patterns))

    def test_unfiltered_rule_has_no_patterns(self):
        temp = next(r for r in R.RULES if r.key == "user_temp")
        self.assertFalse(temp.is_filtered)


class TestGuard(unittest.TestCase):
    """guard 是最后一道闸：路径不合格就拒绝执行。"""

    def test_reject_git_path(self):
        self.assertIsNotNone(cleanup.guard(os.path.join("C:\\proj", ".git", "objects")))

    def test_reject_drive_root(self):
        self.assertIsNotNone(cleanup.guard("C:\\"))

    def test_reject_home_dir(self):
        self.assertIsNotNone(cleanup.guard(os.path.expanduser("~")))

    def test_reject_outside_allowed_roots(self):
        # 用户数据目录不在白名单内
        self.assertIsNotNone(cleanup.guard("C:\\Users\\Public\\Documents\\secret"))

    def test_accept_localappdata_child(self):
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            self.skipTest("非 Windows 或缺少 LOCALAPPDATA")
        self.assertIsNone(cleanup.guard(os.path.join(base, "Temp")))


class TestHuman(unittest.TestCase):
    def test_bytes(self):
        self.assertEqual(report.human(0), "0 B")
        self.assertEqual(report.human(999), "999 B")

    def test_units(self):
        self.assertEqual(report.human(1024), "1.0 KB")
        self.assertEqual(report.human(1024 ** 2), "1.0 MB")
        self.assertEqual(report.human(1024 ** 3 * 1.5), "1.5 GB")
        self.assertEqual(report.human(1024 ** 4 * 2), "2.0 TB")

    def test_float_carry(self):
        # 1023.9 KB 应显示为 1023.9 KB 而不是溢出的 0.9 MB
        self.assertEqual(report.human(1024 * 1023.9), "1023.9 KB")


class TestTable(unittest.TestCase):
    def test_alignment_markers(self):
        md = report._table(["a", "b", "c"], [[1, 2, 3]], ["l", "r", "c"])
        lines = md.splitlines()
        self.assertIn(":---", lines[1])
        self.assertIn("---:", lines[1])
        self.assertIn(":---:", lines[1])
        self.assertEqual(lines[2], "| 1 | 2 | 3 |")


class TestWalkStats(unittest.TestCase):
    def test_missing_dir_returns_zero(self):
        files, size = report.walk_stats(r"Z:\definitely\not\here")
        self.assertEqual((files, size), (0, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
