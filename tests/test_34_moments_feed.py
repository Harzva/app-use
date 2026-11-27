"""朋友圈解析与本地档案的单元测试。

只用合成数据：不把真实好友的昵称、正文写进代码库。帧构造函数按微信 4.2.0 实测的版式摆放坐标：
左栏第二列是「发现」页入口，正文列从 x=827 开始，页脚时间戳与「··」按钮在同一行。
"""
import json
import tempfile
import time
import unittest
from pathlib import Path

from wechat_control import moments_feed as mf
from wechat_control import moments_store as ms

COL = 827.0          # 正文列左边缘
WIN = {"x": 0, "y": 30, "width": 1579, "height": 1320}


def el(text, x, y, width=None):
    w = float(width if width is not None else max(14.0, 13.0 * len(text)))
    return {"text": text, "confidence": 1.0,
            "bbox": {"x": float(x), "y": float(y) - 8, "width": w, "height": 16},
            "center": {"x": float(x) + w / 2.0, "y": float(y)}}


def discover_pane(sticky):
    items = [el("发现", 78, 29, 26), el("朋友圈", 98, 77, 52), el("视频号", 98, 123, 52),
             el("搜一搜", 98, 173, 52), el("游戏", 84, 222, 40), el("小程序", 84, 267, 52)]
    if sticky:
        items.append(el("朋友圈", 1010, 29, 46))   # 滚动后右上角的吸顶标题
    return items


def post_rows(*, author, lines=(), time_text="3天前", likes="", comments=(), y=360, dots=True,
              avatar_noise=False, extra=()):
    """摆出一条帖子的各行，返回 (elements, next_y)。"""
    items = []
    if avatar_noise:
        items.append(el("C Lorv", 780, y + 10))      # 头像里的文字被读出来了
    items.append(el(author, COL, y))
    y += 24
    for line in lines:
        items.append(el(line, COL, y, width=440))
        y += 24
    items.append(el(time_text, COL, y, width=55))
    if dots:
        items.append(el("••", 1262, y, width=18))
    y += 30
    if likes:
        items.append(el(likes, 840, y))
        y += 28
    for comment in comments:
        items.append(el(comment, 835, y, width=400))
        y += 28
    items.extend(extra)
    return items, y + 14


def frame(*posts, sticky=False, owner="号主小号", scale=1.0):
    """组装一帧 capture-ocr 的结果。`posts` 是 post_rows 返回的 (elements, next_y) 元组。"""
    elements = list(discover_pane(sticky))
    if not sticky and owner:
        elements.append(el(owner, 1431, 295, 48))      # 封面右下角的号主昵称
    for items, _ in posts:
        elements.extend(items)
    if scale != 1.0:
        for item in elements:
            item["bbox"] = {k: v * scale for k, v in item["bbox"].items()}
            item["center"] = {k: v * scale for k, v in item["center"].items()}
    return {"ok": True, "imageWidth": WIN["width"] * scale, "imageHeight": WIN["height"] * scale,
            "windowBounds": dict(WIN), "elements": elements}


class FeedParsingTests(unittest.TestCase):
    NOW = 1_800_000_000.0

    def parse(self, cap, owner=""):
        return mf.parse_feed_page(cap, owner_name=owner, now_ts=self.NOW)

    def test_small_helpers(self):
        self.assertEqual(mf.parse_likes_line("V 心安"), ["心安"])
        self.assertEqual(mf.parse_likes_line("⑦ 心安，苏文璐"), ["心安", "苏文璐"])
        self.assertEqual(mf.parse_likes_line("• 苏文璐18591926087"), ["苏文璐18591926087"])
        self.assertEqual(mf.parse_likes_line("Victor, Bob"), ["Victor", "Bob"])
        self.assertEqual(mf.parse_likes_line("❤️ 王五"), ["王五"])
        self.assertEqual(mf.parse_comment_line("苏文璐：好的好的"), {"author": "苏文璐", "replyTo": "", "text": "好的好的"})
        self.assertEqual(mf.parse_comment_line("心安 回复 苏文璐：哈哈哈哈"),
                         {"author": "心安", "replyTo": "苏文璐", "text": "哈哈哈哈"})
        self.assertIsNone(mf.parse_comment_line("早安。"))
        self.assertEqual(mf.parse_relative_seconds("20小时前"), 72000.0)
        self.assertIsNone(mf.parse_relative_seconds("10:23"))
        self.assertEqual(mf.estimate_published_ts("3天前", self.NOW), self.NOW - 3 * 86400)
        self.assertIsNotNone(mf.estimate_published_ts("2024年10月23日", self.NOW))

    def test_top_page_parses_posts_likes_and_comments(self):
        cap = frame(
            post_rows(author="张三", lines=["今天爬山很开心，风景特别好"], likes="V 心安",
                      comments=["李四：真不错", "张三 回复 李四：下次一起"], time_text="5小时前"),
            post_rows(author="李四", lines=["分享一篇文章"], time_text="昨天", y=700),
        )
        page = self.parse(cap)
        self.assertTrue(page["isMomentsView"])
        self.assertTrue(page["topPage"])
        self.assertEqual(page["ownerName"], "号主小号")
        posts = page["posts"]
        self.assertEqual([p["author"] for p in posts], ["张三", "李四"])
        first, second = posts
        self.assertEqual(first["text"], "今天爬山很开心，风景特别好")
        self.assertEqual(first["timeText"], "5小时前")
        self.assertEqual(first["likes"], ["心安"])
        self.assertEqual([c["author"] for c in first["comments"]], ["李四", "张三"])
        self.assertEqual(first["comments"][1]["replyTo"], "李四")
        self.assertFalse(first["partial"] if "partial" in first else first["topCut"] or first["bottomCut"])
        self.assertAlmostEqual(first["footer"]["x"], 1271.0)
        self.assertEqual(second["timeText"], "昨天")
        self.assertEqual(second["likes"], [])

    def test_footer_with_icon_noise_is_still_a_footer(self):
        # 可见范围、删除图标常被读成一两个杂字（实测「774天前 2面」）
        cap = frame(post_rows(author="张三", lines=["第一章"], time_text="774天前 2面", dots=False),
                    post_rows(author="李四", time_text="775天前", y=520), sticky=True)
        posts = self.parse(cap)["posts"]
        self.assertEqual([(p["author"], p["timeText"]) for p in posts], [("张三", "774天前"), ("李四", "775天前")])
        self.assertEqual(posts[0]["source"], "2面")

    def test_body_line_starting_with_a_time_word_is_not_a_footer(self):
        cap = frame(post_rows(author="张三", lines=["昨天去了公园", "走了一下午"], time_text="3天前"))
        post = self.parse(cap)["posts"][0]
        self.assertEqual(post["text"].splitlines(), ["昨天去了公园", "走了一下午"])
        self.assertEqual(post["timeText"], "3天前")

    def test_folded_row_is_not_mistaken_for_a_new_author(self):
        first, y = post_rows(author="张三", likes="V 心安, 李四", time_text="136天前")
        cap = frame((first + [el("余下1条＞", 826, y)], y),
                    post_rows(author="王五", lines=["下一条"], time_text="619天前", y=y + 40))
        page = self.parse(cap)
        self.assertEqual([p["author"] for p in page["posts"]], ["张三", "王五"])
        self.assertTrue(page["posts"][0].get("foldedAfter"))
        self.assertEqual(page["posts"][1]["text"], "下一条")

    def test_comment_input_rows_are_not_likes(self):
        extra = [el("评论", 845, 456, width=30), el("0 日囚发送", 1122, 514, width=133)]
        cap = frame(post_rows(author="张三", time_text="619天前", extra=extra), sticky=True)
        post = self.parse(cap)["posts"][0]
        self.assertEqual(post["likes"], [])
        self.assertTrue(post.get("commentInputOpen"))

    def test_avatar_noise_and_ad_label(self):
        cap = frame(post_rows(author=" LibTV-official", avatar_noise=True, extra=[el("广告", 1246, 360, width=28)],
                              time_text="65天前", dots=False))
        page = self.parse(cap)
        post = page["posts"][0]
        self.assertEqual(post["author"].strip(), "LibTV-official")
        self.assertTrue(post["isAd"])
        self.assertEqual(post["text"], "")

    def test_first_post_of_a_scrolled_frame_is_treated_as_cut(self):
        # 吸顶标题下第一行的作者被裁掉了：这一行可能只是正文，不能当作者
        cut = [el("情绪指纹并没有被证明存在", COL, 83, width=440), el("774天前", COL, 130, width=55), el("••", 1262, 130, width=18)]
        whole, _ = post_rows(author="李四", lines=["下一条"], time_text="775天前", y=300)
        page = self.parse(frame((cut, 200), (whole, 600), sticky=True))
        first, second = page["posts"]
        self.assertTrue(first["topCut"])
        self.assertFalse(first["authorConfident"])
        self.assertTrue(second["authorConfident"])
        self.assertFalse(second["topCut"])

    def test_same_author_same_day_posts_stay_separate(self):
        a, y = post_rows(author="张三", lines=["reading"], time_text="762天前", likes="V 李四")
        b, _ = post_rows(author="张三", lines=["早起打卡", "11点上床"], time_text="762天前", y=y)
        page = self.parse(frame((a, y), (b, 900)))
        self.assertEqual(len(page["posts"]), 2)
        self.assertNotEqual(page["posts"][0]["key"], page["posts"][1]["key"])
        self.assertEqual(page["posts"][1]["text"].splitlines(), ["早起打卡", "11点上床"])

    def test_own_post_and_liked_by_me_flags(self):
        rows, _ = post_rows(author="号主小号", lines=["新项目上线"], likes="V 张三, 李四",
                            comments=["张三：恭喜"], time_text="1小时前")
        post = self.parse(frame((rows, 360)), owner="号主小号")["posts"][0]
        self.assertTrue(post["isOwn"])
        self.assertFalse(post["likedByMe"])
        rows, _ = post_rows(author="张三", likes="V 号主小号", time_text="1小时前")
        post = self.parse(frame((rows, 360)), owner="号主小号")["posts"][0]
        self.assertTrue(post["likedByMe"])

    def test_garbled_frame_is_not_recognized_as_the_feed(self):
        cap = {"ok": True, "imageWidth": 1579, "imageHeight": 1320, "windowBounds": dict(WIN),
               "elements": [el("图¥脂", 1010, 30), el("◎", 1418, 30), el("Hs9", 826, 310)]}
        page = self.parse(cap)
        self.assertFalse(page["isMomentsView"])
        self.assertFalse(page["isDiscoverList"])

    def test_retina_coordinates_are_normalized_to_points(self):
        rows, _ = post_rows(author="张三", lines=[" Retina 帧也能解析"], time_text="2小时前")
        page = self.parse(frame((rows, 360), scale=2.0))
        post = page["posts"][0]
        self.assertEqual(post["author"], "张三")
        self.assertAlmostEqual(post["footer"]["x"], 1271.0)
        self.assertAlmostEqual(page["colLeft"], COL, delta=1.0)


class FeedMergingTests(unittest.TestCase):
    NOW = 1_800_000_000.0

    def page(self, cap, owner="号主小号"):
        return mf.parse_feed_page(cap, owner_name=owner, now_ts=self.NOW)

    def test_overlapping_frames_merge_into_complete_posts(self):
        long_lines = ["第" + str(i) + "行内容足够长用来对齐两帧" for i in range(9)]
        head, y = post_rows(author="张三", lines=long_lines[:4], time_text="", dots=False)  # 只看到上半，没有页脚
        tail = [el(line, COL, 70 + 24 * i, width=440) for i, line in enumerate(long_lines[2:9])]
        tail += [el("3天前", COL, 70 + 24 * 7 + 24, width=55), el("••", 1262, 70 + 24 * 7 + 24, width=18)]
        whole, _ = post_rows(author="李四", lines=["下一条"], time_text="4天前", y=600)
        merger = mf.FeedMerger()
        merger.add_page(self.page(frame((head, y))))
        merger.add_page(self.page(frame((tail, 300), (whole, 600), sticky=True)))
        merged = [p for p in merger.posts if not p["partial"]]
        self.assertEqual([p["author"] for p in merged], ["张三", "李四"])
        self.assertEqual(len(merged[0]["text"].splitlines()), 9)
        self.assertEqual(merged[0]["timeText"], "3天前")

    def test_scrolled_overlapping_frames_with_single_edge_line_merge(self):
        long_lines = ["第" + str(i) + "行内容足够长用来对齐两帧" for i in range(7)]
        above = [el("1天前", COL, 90, width=55), el("••", 1262, 90, width=18)]
        head, y = post_rows(author="张三", lines=long_lines[:3], time_text="", dots=False, y=150)
        tail = [el(line, COL, 70 + 24 * i, width=440) for i, line in enumerate(long_lines[2:7])]
        tail += [el("3天前", COL, 70 + 24 * 5 + 24, width=55), el("••", 1262, 70 + 24 * 5 + 24, width=18)]
        merger = mf.FeedMerger()
        merger.add_page(self.page(frame((above, 120), (head, y), sticky=True)))
        merger.add_page(self.page(frame((tail, 400), sticky=True)))
        merged = [p for p in merger.posts if not p["partial"]]
        self.assertEqual([p["author"] for p in merged], ["张三"])
        self.assertEqual(merged[0]["text"].splitlines(), long_lines)
        self.assertEqual(merged[0]["timeText"], "3天前")

    def test_unmatched_halves_are_flagged_partial(self):
        head, y = post_rows(author="张三", time_text="")                 # 没读到页脚
        orphan = [el("9天前", COL, 80, width=55)]                          # 没读到作者
        merger = mf.FeedMerger()
        merger.add_page(self.page(frame((head, y), sticky=True)))
        merger.add_page(self.page(frame((orphan, 200), sticky=True)))
        self.assertEqual(len(merger.posts), 2)
        self.assertTrue(all(p["partial"] for p in merger.posts))

    def test_same_post_rules(self):
        base = {"key": "mom_a", "author": "张三", "authorConfident": True, "text": "今天爬山很开心风景特别好",
                "timeText": "3天前", "publishedEstimate": "2027-01-15T00:00:00+00:00"}
        self.assertTrue(mf.same_post(base, dict(base)))
        ocr_slip = dict(base, key="mom_b", text="今天爬山很开心,风景特别好", timeText="4天前",
                        publishedEstimate="2027-01-16T00:00:00+00:00")
        # 同一次读取里时间刻度不同就不是同一条；隔了几天再读（允许漂移）才算
        self.assertFalse(mf.same_post(base, ocr_slip))
        self.assertTrue(mf.same_post(base, ocr_slip, max_drift_days=3))
        other_author = dict(base, key="mom_c", author="李四")
        self.assertFalse(mf.same_post(base, other_author))
        no_text = dict(base, key="mom_d", text="")
        self.assertFalse(mf.same_post(no_text, dict(no_text, key="mom_e")))

    def test_post_key_ignores_spacing_and_punctuation(self):
        a = mf.post_key("张三", "今天 爬山，很开心！风景\t特别好", "3天前", self.NOW - 86400)
        b = mf.post_key("张三", "今天爬山很开心 风景特别好", "4天前", self.NOW)
        self.assertEqual(a, b)
        self.assertNotEqual(a, mf.post_key("李四", "今天爬山很开心 风景特别好", "3天前", self.NOW))


if __name__ == "__main__":
    unittest.main()
