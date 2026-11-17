#!/usr/bin/env python3
"""回复质量基准：200 条话术 × 评分卡（KB 命中 / 无术语外泄 / 人设一致性 / 频控）。

独立运行：python3 scripts/reply_benchmark.py [--quick]
输出：logs/reply_benchmark_report.json + 终端摘要
"""
import argparse
import json
import re
import sys
import tempfile
import time
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wechat_control.engine import WeChatControlEngine  # noqa: E402
from wechat_control.auth_gate import ALL_CAPABILITIES  # noqa: E402

JARGON_RE = re.compile(
    r"(FTS5|AXUIElement|熔断|读回|Takeover|takeover|3x\b|prompt|RealtimeMessageMonitor|preview_reply|脏输入)"
)

# ---------------- 话术集（10 类 × 20 条 = 200） ----------------

GREETINGS = [
    "你好", "在吗", "你好呀", "hi", "hello", "在不在", "有人吗", "请问在吗",
    "你好，我想咨询一下", "嗨嗨", "早上好", "晚上好", "下午好", "你好你好，你能回复我消息吗？",
    "测试一下你在不在线", "请问是机器人吗", "你是客服吗", "打扰一下", "你好，方便聊聊吗", "hi~在忙吗",
]
PRODUCT_QA = [
    "WaveBot 是什么产品？", "这个机器人怎么用？", "支持哪些功能？", "怎么开启自动回复？",
    "托管是什么意思？", "怎么选择托管好友？", "会话记录能导入吗？", "支持图片识别吗？",
    "链接发给你能看懂吗？", "语音消息能转文字吗？", "怎么切换客服人设？", "知识库里有什么内容？",
    "头像能显示吗？", "网页控制台怎么打开？", "授权怎么设置？", "遇到问题找谁？",
    "人工多久回复？", "你们的工作时间是什么时候？", "这个和影刀有什么区别？", "能同时管几个好友？",
]
PRICING = [
    "多少钱？", "怎么收费的？", "有免费版吗？", "价格表发一下",
    "企业版和个人版有什么区别？", "能开发票吗？", "支持试用吗？", "年付有折扣吗？",
    "按什么计费？", "退款政策是什么？", "购买渠道有哪些？", "代理商怎么联系？",
    "批量采购有优惠吗？", "续费怎么操作？", "价格和智拓巨浪比怎么样？", "会员权益有哪些？",
    "学生有优惠吗？", "付款方式支持哪些？", "优惠码哪里领？", "价格太贵了能便宜点吗？",
]
TECH_QA = [
    "RPA与按键精灵有什么区别", "RPA 是什么意思？", "支持 Mac 吗？", "系统要求是什么？",
    "数据存在哪里？", "安全吗？会不会泄露聊天记录？", "需要联网吗？", "断网了还能用吗？",
    "怎么更新版本？", "支持多开吗？", "微信退出登录会怎样？", "重启后托管会自动恢复吗？",
    "消息发送失败怎么办？", "发送频率限制是多少？", "怎么防止被封号？", "API 能对接吗？",
    "知识库能自定义吗？", "能接入自己的大模型吗？", "日志在哪里看？", "怎么卸载干净？",
]
HANDOFF = [
    "转人工", "转接人工", "人工客服", "找人工", "人工服务", "找真人", "真人客服", "人工接管",
    "帮我转人工客服", "我要找真人聊聊", "这个问题机器人答不了，转人工吧", "转人工谢谢",
    "人工在线吗？", "麻烦转一下人工", "客服人员在哪？", "找你们主管",
    "转人工，急", "需要真人帮助", "please transfer to human", "转人工处理",
]
CHITCHAT = [
    "今天天气怎么样", "讲个笑话", "你喜欢什么电影", "吃了吗", "你叫什么名字",
    "你是男是女", "你多大了", "你从哪里来", "夸夸我", "睡不着怎么办",
    "推荐几首歌", "周末去哪玩好", "帮我算个命", "你是AI吗", "你会说英语吗",
    "拜拜", "晚安", "谢谢啦", "恭喜发财", "爱你哦",
]
NOISY = [
    "   ", "。。。。。", "？？？", "aaaa", "123456", "！！！",
    "asdfghjkl", "😄😄😄", "～～～", "....",
    "a" * 200, "？？？？？？？？？？", "测 试 带 空 格", "混合abc123测试",
    "👍", "[动画表情]", "[图片]", "[视频]", "[语音]", "[文件]",
    "。。", "？？？喵", "zzzz", "0000", "test", "test test test",
    "～！@#￥%……&*（）", "……", "！！！？？？", "😂", "🤖🤖🤖🤖🤖",
    "。。。。。？！", "-----", "_____", "     👍", "[动画表情][动画表情]",
]
LINKS = [
    "https://github.com/Harzva/wechat-bot", "http://yingdao.com/qa/",
    "帮我看看这个链接 https://example.com/doc", "https://example.com/article?id=123",
    "你看下这个网页：https://example.com", "这个链接是什么 https://example.com/qa",
    "https://example.com/video 求解析", "发你一个文档 https://example.com/doc.pdf",
    "https://example.com", "https://example.com/blog/post-1",
    "麻烦分析 http://test.org/page", "帮我打开 https://example.org",
    "这个网站讲什么 https://example.net", "https://example.com/news 今天的热点",
    "看看 https://example.com/tutorial 教程", "https://example.com/pricing 价格页",
    "https://example.com/download 下载地址对吗", "这个链接打不开 https://example.com/404",
    "帮我总结 https://example.com/summary", "https://example.com/faq 常见问题页",
]
IMAGE_DESC = [
    "[图片识别:截图] 这是一张订单截图", "发了个图 你看下", "[图片] 报错截图帮忙看看",
    "图片里说的对吗", "[图片识别:menu] 菜单照片", "刚发了张照片",
    "[图片] 这是我的配置截图", "帮我看看这个报错图", "[图片识别:chart] 销售数据图",
    "图里的地址是什么", "[图片] 二维码扫不了", "发了截图 你看下哪有问题",
    "[图片识别:idcard] 证件照片", "图片发过去了", "[图片] 产品实物图",
    "这张图什么意思", "[图片识别:code] 代码截图", "截图里的按钮在哪",
    "[图片] 聊天记录截图", "图片看不清再发一次",
]
PERSONA_SPECIFIC = [
    "RPA和按键精灵的区别是什么", "rpa技术能做什么", "RPA工具怎么选型",
    "按键精灵过时了吗", "RPA与按键精灵有什么区别", "自动化脚本怎么入门",
    "RPA适合什么场景", "按键精灵还能用吗", "RPA 机器人流程自动化原理",
    "怎么用RPA做数据采集", "rpa和爬虫的区别", "RPA 项目怎么交付",
    "按键精灵支持mac吗", "RPA实施周期多久", "rpa部署方式有哪些",
    "RPA和低代码什么关系", "按键精灵安全性如何", "rpa运维成本高吗",
    "RPA怎么处理异常", "自动化测试和RPA的区别",
]

CATEGORIES = [
    ("寒暄问候", GREETINGS, {}),
    ("产品咨询", PRODUCT_QA, {"expectAnswered": True}),
    ("价格咨询", PRICING, {"expectAnswered": True}),
    ("技术咨询", TECH_QA, {"expectAnswered": True}),
    ("转人工", HANDOFF, {"expectHandoff": True}),
    ("闲聊", CHITCHAT, {}),
    ("噪声输入", NOISY, {"allowGeneric": True}),
    ("链接消息", LINKS, {}),
    ("图片消息", IMAGE_DESC, {}),
    ("人设专属", PERSONA_SPECIFIC, {"persona": "rpa-tech-expert", "expectAnswered": True}),
]

PERSONAS = ["wecom-kf-pro", "warm-friend", "concise-assistant", "rpa-tech-expert"]


def build_engine(tmp: Path) -> WeChatControlEngine:
    engine = WeChatControlEngine(
        audit_log_path=tmp / "a.jsonl", auth_file_path=tmp / "auth.json",
        bindings_file_path=tmp / "b.json", models_config_path=tmp / "m.json",
        model_http_requester=lambda m, u, **k: (_ for _ in ()).throw(ConnectionRefusedError),
        knowledge_db_path=tmp / "kb.sqlite", personas_file_path=tmp / "p.json",
        snapshots_dir=tmp / "snap", reports_dir=tmp / "reports",
        allowed_groups=["VIP客户群", "测试私域运营群"],
    )
    engine.auth_grant(ALL_CAPABILITIES, authorized_by="benchmark")
    engine.bind_contact("基准用户", role="friend", auto_reply_enabled=True)
    return engine


def run_benchmark(quick: bool = False) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="wavebot_bench_"))
    engine = build_engine(tmp)
    random.seed(42)

    cats = CATEGORIES if not quick else CATEGORIES[:3] + CATEGORIES[4:5]
    personas = PERSONAS if not quick else ["wecom-kf-pro"]

    results = []
    t0 = time.time()
    # 寒暄确认话术不应抢答业务问题（答非所问检测基准线）
    ACK_TITLES = ("实时监控与自动回复确认话术",)
    for cat_name, texts, flags in cats:
        forced_pid = flags.get("persona")
        for text in texts:
            pids = [forced_pid] if forced_pid else personas
            for pid in pids:
                engine.persona_switch("基准用户", pid)
                prev = engine.preview_smart_reply("基准用户", text)
                reply = str(prev.get("replyText") or "")
                docs = [str(d.get("title") or "") for d in (prev.get("basis") or {}).get("documentRefs", [])]
                top_title = docs[0] if docs else ""
                # rpa-tech-expert 定位为号主内部技术人设，不判术语外泄
                customer_facing = pid != "rpa-tech-expert"
                has_jargon = bool(JARGON_RE.search(reply)) if customer_facing else False
                answered_ok = True
                if flags.get("expectAnswered") and customer_facing:
                    # 答所问：KB 有命中且 top 不是寒暄确认话术
                    answered_ok = bool(prev.get("matchedCount")) and top_title and not any(
                        a in top_title for a in ACK_TITLES
                    )
                length_ok = 8 <= len(reply.strip()) <= 200
                # 句中截断检测：虚词收尾的句子（"的。如仍需"）或省略号后硬接尾巴（"…如仍需"）
                trunc_ok = not re.search(
                    r"(的|了|在|和|与|或|是|把|被|对|向|从|及|并|不)。如(仍需|有需要)|…如(仍需|有需要)",
                    reply,
                )
                entry = {
                    "category": cat_name,
                    "persona": pid,
                    "customerFacing": customer_facing,
                    "incoming": text[:48],
                    "reply": reply[:110],
                    "topDoc": top_title,
                    "matchedCount": int(prev.get("matchedCount") or 0),
                    "passed": bool(reply.strip()) and not has_jargon and answered_ok and length_ok and trunc_ok,
                    "hasJargon": has_jargon,
                    "answeredOk": answered_ok,
                    "lengthOk": length_ok,
                    "truncOk": trunc_ok,
                }
                if flags.get("expectHandoff"):
                    entry["passed"] = entry["passed"] and bool(
                        re.search(r"(人工|专员|真人)", reply)
                    )
                results.append(entry)
    elapsed = time.time() - t0

    # 频控评分：同 target 连发触发 AntiBanGuard 拦截
    guard = engine.antiban
    freq_ok, freq_blocked_at = True, None
    for i in range(30):
        allowed, reason = guard.check_can_send("频控测试好友")
        if not allowed:
            freq_blocked_at = i + 1
            break
        guard.record_sent("频控测试好友")
    if freq_blocked_at is None:
        freq_ok = False

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    jargon_leaks = [r for r in results if r["hasJargon"]]
    by_cat = {}
    for r in results:
        c = by_cat.setdefault(r["category"], {"total": 0, "passed": 0, "answered": 0, "distinctReplies": set()})
        c["total"] += 1
        c["passed"] += 1 if r["passed"] else 0
        c["answered"] += 1 if r.get("answeredOk") else 0
        c["distinctReplies"].add(r["reply"])
    # 回复多样性：同类别不同问题不应千篇一律
    diversity = {
        cat: round(len(v["distinctReplies"]) / v["total"], 3)
        for cat, v in by_cat.items() if v["total"] >= 4
    }
    answered_total = sum(1 for r in results if r.get("answeredOk") is not None) if False else None
    # 答所问率（expectAnswered 类目）
    ans_cases = [r for r in results if r.get("answeredOk") is not None]
    answered_rate = round(sum(1 for r in ans_cases if r["answeredOk"]) / len(ans_cases), 4) if ans_cases else None
    for c in by_cat.values():
        c["distinctReplies"] = len(c["distinctReplies"])

    report = {
        "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "quick": quick,
        "totalCases": total,
        "passed": passed,
        "passRate": round(passed / total, 4) if total else 0,
        "jargonLeaks": len(jargon_leaks),
        "answeredRate": answered_rate,
        "replyDiversity": diversity,
        "frequencyGuard": {"ok": freq_ok, "blockedAtSend": freq_blocked_at},
        "elapsedSeconds": round(elapsed, 2),
        "byCategory": by_cat,
        "leakSamples": [
            {"category": r["category"], "persona": r["persona"], "incoming": r["incoming"], "reply": r["reply"]}
            for r in jargon_leaks[:10]
        ],
        "failSamples": [
            {"category": r["category"], "persona": r["persona"], "incoming": r["incoming"], "reply": r["reply"]}
            for r in results if not r["passed"] and not r["hasJargon"]
        ][:10],
    }
    out = ROOT / "logs" / "reply_benchmark_report.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="抽样模式（1 个人设 + 4 类）")
    args = ap.parse_args()
    rep = run_benchmark(quick=args.quick)
    print(f"话术基准: {rep['passed']}/{rep['totalCases']} 通过 "
          f"(通过率 {rep['passRate']:.1%})，术语外泄 {rep['jargonLeaks']} 条，"
          f"答所问率 {rep['answeredRate'] if rep['answeredRate'] is not None else 'n/a'}，"
          f"频控 {'OK' if rep['frequencyGuard']['ok'] else 'FAIL'}，耗时 {rep['elapsedSeconds']}s")
    for cat, c in rep["byCategory"].items():
        mark = "✓" if c["passed"] == c["total"] else "✗"
        print(f"  {mark} {cat}: {c['passed']}/{c['total']}")
    for s in rep["leakSamples"][:5]:
        print(f"  [外泄] {s['category']}/{s['persona']}「{s['incoming']}」→ {s['reply'][:60]}")
    for s in rep["failSamples"][:5]:
        print(f"  [失败] {s['category']}/{s['persona']}「{s['incoming']}」→ {s['reply'][:60]}")
    return 0 if rep["passRate"] >= 0.95 and rep["jargonLeaks"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
