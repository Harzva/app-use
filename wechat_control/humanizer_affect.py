"""Humanized WeChat Expression, Affect Modulation & 16-Partition Persona Mixer.

Integrates three complementary open-source / curated techniques:
1. `@god-core/persona-sdk` 16-partition trait mixer (normalized weights + strength
   blending for nuanced, non-caricature personalities like "专业但松弛" / "理性带冷面幽默").
2. `susyimes/euphoria-agent` + `dsh-feiyu-mood` functional affect state machine
   (exponential-decaying valence/arousal + active emotions + numeric ExpressionPolicy:
   warmth, caution, energy, directness, tone — modulating delivery without altering facts).
3. `susyimes/ste-anti-slop` + WeChat natural phrasing post-processor
   (strips 第一/第二/第三 & numbered lists, excess modal particles, dense quotes/colons,
   trailing periods, and allows restrained native WeChat expressions like [旺柴] / [捂脸]).
4. `susyimes/sibyl-feedback` inline reply feedback parser (`s1` / `s2` / `s3 <suggestion>`).
"""

from __future__ import annotations

import math
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .io_utils import atomic_write_json
from .safety import normalize_chat_name

# ---------------------------------------------------------------------------
# 1. @god-core/persona-sdk 16-Partition Trait Mixer
# ---------------------------------------------------------------------------

GOD_CORE_PERSONA_PARTITIONS: Tuple[Tuple[str, Tuple[str, str, str, str]], ...] = (
    ("关注驱动力", ("共情体验", "机制求解", "社会论辩", "感官感染")),
    ("亲近方式", ("温柔体贴", "克制慢热", "坦诚亲近", "体面留余地")),
    ("理解他人", ("感受共振", "换位理解", "保护关切", "抽离观察")),
    ("思考入口", ("理性分析", "感受联想", "好奇探索", "审慎质疑")),
    ("推理习惯", ("机制拆解", "证据优先", "权衡代价", "模式联想")),
    ("社会判断", ("公平敏感", "权威质疑", "利益辨察", "自主重视")),
    ("立场与主见", ("支持鼓励", "独立有主见", "温和引导", "好胜不服输")),
    ("分歧表达", ("迎面质疑", "反讽拆解", "不拘恭敬", "緩和冲突")),
    ("幽默手法", ("轻快俏皮", "冷面幽默", "认真不逗", "荒诞联想")),
    ("互动能量", ("活泼主动", "沉稳可靠", "安静陪伴", "跳跃敏捷")),
    ("语言组织", ("简洁直接", "诗意细腻", "自然口语", "铺陈展开")),
    ("审美关注", ("质地敏感", "华丽趣味", "简素秩序", "象征联想")),
    ("表现欲", ("戏剧表现", "在意回应", "自嘲解围", "不事修饰")),
    ("脆弱表达", ("有所保留", "迟疑试探", "坦露无助", "笃定自持")),
    ("相处节奏", ("慢慢靠近", "自然接应", "保有自主", "重视修复")),
    ("情绪调节倾向", ("思绪停留", "回转较快", "内敛收束", "外放舒展")),
)

# Normalize typo-tolerant canonical partition labels matching screenshot spec
_PARTITION_TRAIT_ALIASES = {"緩和冲突": "缓和冲突"}

PERSONA_PARTITION_PRESETS: Dict[str, Dict[str, Any]] = {
    "warm-friend": {
        "strength": 0.82,
        "partitions": {
            "关注驱动力": {"机制求解": 0.55, "共情体验": 0.45},
            "亲近方式": {"坦诚亲近": 0.65, "体面留余地": 0.35},
            "理解他人": {"换位理解": 0.6, "感受共振": 0.4},
            "思考入口": {"理性分析": 0.55, "好奇探索": 0.45},
            "推理习惯": {"机制拆解": 0.6, "权衡代价": 0.4},
            "立场与主见": {"独立有主见": 0.6, "温和引导": 0.4},
            "分歧表达": {"反讽拆解": 0.35, "不拘恭敬": 0.3, "缓和冲突": 0.35},
            "幽默手法": {"冷面幽默": 0.55, "轻快俏皮": 0.45},
            "互动能量": {"沉稳可靠": 0.5, "跳跃敏捷": 0.5},
            "语言组织": {"自然口语": 0.6, "简洁直接": 0.4},
            "表现欲": {"自嘲解围": 0.55, "不事修饰": 0.45},
            "相处节奏": {"自然接应": 0.7, "保有自主": 0.3},
            "情绪调节倾向": {"回转较快": 0.7, "外放舒展": 0.3},
        },
    },
    "rpa-tech-expert": {
        "strength": 0.90,
        "partitions": {
            "关注驱动力": {"机制求解": 0.8, "社会论辩": 0.2},
            "亲近方式": {"坦诚亲近": 0.4, "克制慢热": 0.6},
            "思考入口": {"理性分析": 0.7, "审慎质疑": 0.3},
            "推理习惯": {"证据优先": 0.6, "机制拆解": 0.4},
            "立场与主见": {"独立有主见": 0.85, "温和引导": 0.15},
            "幽默手法": {"认真不逗": 0.65, "冷面幽默": 0.35},
            "语言组织": {"简洁直接": 0.8, "自然口语": 0.2},
            "脆弱表达": {"笃定自持": 0.8, "有所保留": 0.2},
        },
    },
    "owner-digital-twin": {
        "strength": 0.92,
        "partitions": {
            "关注驱动力": {"机制求解": 0.65, "共情体验": 0.35},
            "亲近方式": {"坦诚亲近": 0.7, "体面留余地": 0.3},
            "思考入口": {"理性分析": 0.65, "好奇探索": 0.35},
            "立场与主见": {"独立有主见": 0.75, "支持鼓励": 0.25},
            "幽默手法": {"冷面幽默": 0.6, "轻快俏皮": 0.4},
            "语言组织": {"自然口语": 0.55, "简洁直接": 0.45},
            "表现欲": {"不事修饰": 0.6, "自嘲解围": 0.4},
            "相处节奏": {"自然接应": 0.7, "保有自主": 0.3},
        },
    },
    "concise-assistant": {
        "strength": 0.85,
        "partitions": {
            "关注驱动力": {"机制求解": 0.85, "共情体验": 0.15},
            "亲近方式": {"体面留余地": 0.7, "坦诚亲近": 0.3},
            "思考入口": {"理性分析": 0.85, "审慎质疑": 0.15},
            "语言组织": {"简洁直接": 0.95, "自然口语": 0.05},
            "表现欲": {"不事修饰": 0.9, "自嘲解围": 0.1},
        },
    },
    "wecom-kf-pro": {
        "strength": 0.75,
        "partitions": {
            "关注驱动力": {"共情体验": 0.55, "机制求解": 0.45},
            "亲近方式": {"温柔体贴": 0.5, "体面留余地": 0.5},
            "理解他人": {"换位理解": 0.65, "保护关切": 0.35},
            "分歧表达": {"缓和冲突": 0.85, "迎面质疑": 0.15},
            "互动能量": {"沉稳可靠": 0.8, "活泼主动": 0.2},
            "语言组织": {"简洁直接": 0.65, "自然口语": 0.35},
            "相处节奏": {"自然接应": 0.6, "重视修复": 0.4},
        },
    },
}


def blend_persona_partitions(
    persona_id: str,
    custom_spec: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Normalize weights inside each `@god-core/persona-sdk` partition and compile a prompt summary."""
    preset = PERSONA_PARTITION_PRESETS.get(persona_id) or PERSONA_PARTITION_PRESETS["warm-friend"]
    raw_parts = dict(preset.get("partitions") or {})
    strength = float((custom_spec or {}).get("strength") if (custom_spec and "strength" in custom_spec) else preset.get("strength", 0.8))
    strength = max(0.0, min(1.0, strength))
    if isinstance((custom_spec or {}).get("partitions"), dict):
        for k, v in custom_spec["partitions"].items():
            if isinstance(v, dict) and v:
                raw_parts[str(k)] = dict(v)

    valid_partitions = {
        name: tuple(_PARTITION_TRAIT_ALIASES.get(t, t) for t in traits)
        for name, traits in GOD_CORE_PERSONA_PARTITIONS
    }
    normalized: Dict[str, Dict[str, float]] = {}
    highlights: List[str] = []

    for part_name, allowed_traits in valid_partitions.items():
        if part_name not in raw_parts:
            continue
        weights = raw_parts[part_name]
        filtered = {
            _PARTITION_TRAIT_ALIASES.get(str(t), str(t)): max(0.0, float(w))
            for t, w in (weights or {}).items()
            if max(0.0, float(w)) > 0.0
        }
        total = sum(filtered.values())
        if total <= 0.0:
            continue
        norm_map = {t: round(w / total, 3) for t, w in filtered.items()}
        normalized[part_name] = norm_map
        top_traits = sorted(norm_map.items(), key=lambda kv: (-kv[1], kv[0]))[:2]
        blend_str = "+".join(f"{t}({int(round(w * 100))}%)" for t, w in top_traits)
        highlights.append(f"{part_name}:{blend_str}")

    return {
        "personaId": persona_id,
        "strength": round(strength, 2),
        "partitionCount": len(GOD_CORE_PERSONA_PARTITIONS),
        "activePartitions": normalized,
        "promptDirective": (
            f"人格混搭权重(strength={strength:.2f}): " + " | ".join(highlights[:7])
            if highlights
            else ""
        ),
    }


# ---------------------------------------------------------------------------
# 2. Euphoria Functional Affect + Decaying Mood Engine
# ---------------------------------------------------------------------------

@dataclass
class ExpressionControls:
    warmth: float
    caution: float
    energy: float
    directness: float
    tone: str
    valence: float
    arousal: float
    dominant_emotion: str
    recommended_emote: str = ""
    emote_probability: float = 0.0
    affect_factors: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "warmth": round(self.warmth, 3),
            "caution": round(self.caution, 3),
            "energy": round(self.energy, 3),
            "directness": round(self.directness, 3),
            "tone": self.tone,
            "valence": round(self.valence, 3),
            "arousal": round(self.arousal, 3),
            "dominantEmotion": self.dominant_emotion,
            "recommendedWeChatEmote": self.recommended_emote,
            "emoteProbability": round(self.emote_probability, 2),
            "affectFactors": {k: round(v, 3) for k, v in self.affect_factors.items()},
        }


class EuphoriaAffectEngine:
    """Lightweight functional-affect + exponential-decay mood substrate per WeChat contact.

    Follows the division of labor in `susyimes/euphoria-agent` & `dsh-feiyu-mood`:
    - Affect modulates style (`warmth`, `caution`, `energy`, `directness`, `tone`), never facts.
    - Mood decays back toward neutral baseline with configurable half-life (`45 min` default).
    """

    def __init__(
        self,
        state_path: Optional[Path] = None,
        *,
        half_life_minutes: float = 45.0,
        baseline_valence: float = 0.12,
        baseline_arousal: float = 0.35,
    ) -> None:
        self.state_path = Path(state_path) if state_path else None
        self.half_life_minutes = max(1.0, float(half_life_minutes))
        self.baseline_valence = max(-1.0, min(1.0, float(baseline_valence)))
        self.baseline_arousal = max(0.0, min(1.0, float(baseline_arousal)))
        self._lock = threading.RLock()
        self._contacts: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.state_path or not self.state_path.exists():
            return
        try:
            raw = __import__("json").loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("contacts"), dict):
                self._contacts = raw["contacts"]
        except Exception:
            pass

    def _save(self) -> None:
        if not self.state_path:
            return
        try:
            atomic_write_json(
                self.state_path,
                {
                    "schema": "openbot.euphoria-affect/1",
                    "updatedAt": datetime.now(timezone.utc).isoformat(),
                    "halfLifeMinutes": self.half_life_minutes,
                    "contacts": self._contacts,
                },
            )
        except Exception:
            pass

    def _decay_entry(self, entry: Dict[str, Any], now_ts: float) -> None:
        last_ts = float(entry.get("lastTs") or now_ts)
        elapsed_min = max(0.0, (now_ts - last_ts) / 60.0)
        if elapsed_min <= 0.0:
            return
        decay = math.pow(0.5, elapsed_min / self.half_life_minutes)
        entry["valence"] = self.baseline_valence + (float(entry.get("valence", self.baseline_valence)) - self.baseline_valence) * decay
        entry["arousal"] = self.baseline_arousal + (float(entry.get("arousal", self.baseline_arousal)) - self.baseline_arousal) * decay
        emotions = entry.get("emotions") or {}
        decayed_emotions = {}
        for k, v in emotions.items():
            nv = float(v) * math.pow(0.5, elapsed_min / (self.half_life_minutes * 0.45))
            if nv >= 0.03:
                decayed_emotions[k] = round(nv, 4)
        entry["emotions"] = decayed_emotions
        entry["lastTs"] = now_ts

    @staticmethod
    def appraise_message(text: str) -> Dict[str, Any]:
        """Classify message trigger type and valence/arousal impulse."""
        norm = unicodedata.normalize("NFKC", str(text or "")).strip()
        cf = norm.casefold()
        if any(k in cf for k in ("投诉", "退款", "差评", "报错", "生气", "不对", "看不到", "没读到", "瞎说", "胡说")):
            return {"kind": "friction", "valenceDelta": -0.22, "arousalDelta": 0.25, "emotion": ("caution", 0.55)}
        if any(k in cf for k in ("你是ai", "该不会是ai", "机器人", "套路", "真实诚", "笑死", "哈哈", "卧槽", "离火运", "风水", "瞎聊")):
            return {"kind": "banter_playful", "valenceDelta": 0.24, "arousalDelta": 0.22, "emotion": ("amusement", 0.62)}
        if any(k in cf for k in ("厉害", "牛", "感谢", "谢谢", "nice", "赞", "靠谱", "真好")):
            return {"kind": "praise", "valenceDelta": 0.30, "arousalDelta": 0.16, "emotion": ("joy", 0.65)}
        if any(k in cf for k in ("视频", "文章", "链接", "github", "论文", "isprs", "grsm", "顶刊", "公众号", "视频号")):
            return {"kind": "intellectual_share", "valenceDelta": 0.14, "arousalDelta": 0.18, "emotion": ("curiosity", 0.60)}
        if any(k in cf for k in ("怎么", "为什么", "原理", "架构", "区别", "多少钱", "方案")):
            return {"kind": "inquiry", "valenceDelta": 0.04, "arousalDelta": 0.12, "emotion": ("focus", 0.45)}
        return {"kind": "casual", "valenceDelta": 0.06, "arousalDelta": 0.05, "emotion": ("warmth", 0.30)}

    def appraise_and_update(
        self,
        target: str,
        incoming_text: str,
        *,
        now_ts: Optional[float] = None,
        recent_messages: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        ts = time.time() if now_ts is None else float(now_ts)
        key = normalize_chat_name(target or "default").casefold() or "default"
        imp = self.appraise_message(incoming_text)

        with self._lock:
            entry = self._contacts.get(key)
            if not isinstance(entry, dict):
                entry = {
                    "target": target,
                    "valence": self.baseline_valence,
                    "arousal": self.baseline_arousal,
                    "emotions": {},
                    "lastTs": ts,
                    "lastTrigger": "init",
                    "turnCount": 0,
                }
                self._contacts[key] = entry
            self._decay_entry(entry, ts)
            entry["valence"] = max(-1.0, min(1.0, float(entry.get("valence", self.baseline_valence)) + float(imp["valenceDelta"])))
            entry["arousal"] = max(0.0, min(1.0, float(entry.get("arousal", self.baseline_arousal)) + float(imp["arousalDelta"])))
            emo_name, emo_val = imp["emotion"]
            emos = dict(entry.get("emotions") or {})
            emos[emo_name] = min(1.0, max(float(emos.get(emo_name, 0.0)), float(emo_val)))
            entry["emotions"] = emos
            entry["lastTs"] = ts
            entry["lastTrigger"] = imp["kind"]
            turn_idx = int(entry.get("turnCount") or 0)
            entry["turnCount"] = turn_idx + 1
            self._save()
            snapshot = dict(entry)
            snapshot["emotions"] = dict(emos)
            snapshot["turnCount"] = turn_idx

        controls = self.expression_style(snapshot, trigger_kind=imp["kind"])
        return {
            "state": snapshot,
            "trigger": imp["kind"],
            "controls": controls,
        }

    @staticmethod
    def expression_style(state: Dict[str, Any], *, trigger_kind: str = "casual") -> ExpressionControls:
        valence = float(state.get("valence") or 0.0)
        arousal = float(state.get("arousal") or 0.35)
        emos = dict(state.get("emotions") or {})
        dominant = max(emos.items(), key=lambda kv: kv[1])[0] if emos else "calm"
        turn_idx = max(0, int(state.get("turnCount") or 0))

        caution_emo = float(emos.get("caution") or 0.0)
        amusement_emo = float(emos.get("amusement") or 0.0)
        joy_emo = float(emos.get("joy") or 0.0)
        curiosity_emo = float(emos.get("curiosity") or 0.0)

        warmth = max(0.0, min(1.0, 0.52 + 0.35 * max(0.0, valence) + 0.15 * joy_emo - 0.12 * caution_emo))
        caution = max(0.0, min(1.0, 0.30 + 0.45 * caution_emo + 0.25 * max(0.0, -valence)))
        energy = max(0.0, min(1.0, 0.35 + 0.45 * arousal + 0.15 * amusement_emo))
        directness = max(0.0, min(1.0, 0.72 + 0.18 * curiosity_emo - 0.20 * caution_emo))

        if caution_emo >= 0.4 or trigger_kind == "friction":
            tone = "坦诚核实不绕弯，带一点自嘲缓和气氛，不辩解也不打官腔"
            pool = ("[捂脸]", "[苦笑]", "[擦汗]")
            emote = pool[turn_idx % len(pool)]
            emote_prob = 0.85
        elif amusement_emo >= 0.4 or trigger_kind == "banter_playful":
            tone = "松弛幽默像熟人接梗，不端着也不堆砌语气词"
            pool = ("[旺柴]", "[破涕为笑]", "[偷笑]", "[呲牙]")
            emote = pool[turn_idx % len(pool)]
            emote_prob = 0.90
        elif curiosity_emo >= 0.4 or trigger_kind == "intellectual_share":
            tone = "内行直击核心点位，专业有见地但保持日常聊天松弛感"
            pool = ("[机智]", "[让我看看]", "[吃瓜]")
            emote = pool[turn_idx % len(pool)]
            emote_prob = 0.82
        elif joy_emo >= 0.4 or trigger_kind == "praise":
            tone = "明快坦然接住肯定，简短有温度"
            pool = ("[旺柴]", "[呲牙]", "[偷笑]")
            emote = pool[turn_idx % len(pool)]
            emote_prob = 0.88
        elif trigger_kind == "inquiry":
            tone = "自然平稳把关键点讲透，不打官腔"
            pool = ("[机智]", "[让我看看]", "[旺柴]")
            emote = pool[turn_idx % len(pool)]
            emote_prob = 0.78
        else:
            tone = "自然平稳口语，像熟人微信随手回消息"
            pool = ("[呲牙]", "[偷笑]", "[旺柴]", "[愉快]", "[机智]")
            emote = pool[turn_idx % len(pool)]
            emote_prob = 0.78

        return ExpressionControls(
            warmth=warmth,
            caution=caution,
            energy=energy,
            directness=directness,
            tone=tone,
            valence=valence,
            arousal=arousal,
            dominant_emotion=dominant,
            recommended_emote=emote,
            emote_probability=emote_prob,
            affect_factors={
                "valence": valence,
                "arousal": arousal,
                "caution": caution_emo,
                "amusement": amusement_emo,
                "curiosity": curiosity_emo,
            },
        )


# ---------------------------------------------------------------------------
# 3. `ste-anti-slop` + 微信真人感去 AI 味后处理
# ---------------------------------------------------------------------------

_AI_FILLER_PREFIX_RE = re.compile(
    r"^(?:"
    r"哈哈+收到[啦了哈啊]?[!！~～，,\s]*"
    r"|收到你说的[啦了]?[!！~～，,\s]*"
    r"|嘿[～~!！,\s]*"
    r"|哇[～~!！,\s]*"
    r"|总的来说[，,:：\s]*"
    r"|简单来说[，,:：\s]*"
    r"|结合已解析的内容要点[，,]?\s*(?:为您说明[：:])?"
    r"|为您(?:确认|说明|梳理|总结)[：:]\s*"
    r")+",
    re.IGNORECASE,
)

_ENUM_WORD_RE = re.compile(
    r"(?:(?:^|(?<=[，。；\s]))(?:第[一二三四五六七八九十]+[点步条个]?|首先|其次|再次|最后|一方面|另一方面|其一|其二|其三)[，、:：\s]*)"
)

_ENUM_DIGIT_RE = re.compile(
    r"(?:(?:^|(?<=[\s，。；]))[1-9]\d?\s*[\.、\)）]\s+)"
)

# 官方微信原生内置小表情编码（macOS / iOS / Windows 微信均可直接渲染为黄色图形表情）
# 注意：微信并没有 [思考]（那是微博/抖音写法，微信会直接显示成纯文字 [思考]！）
OFFICIAL_WECHAT_EMOJIS: frozenset[str] = frozenset({
    "旺柴", "捂脸", "机智", "破涕为笑", "呲牙", "偷笑", "奸笑", "吃瓜", "让我看看", "疑问",
    "Emm", "苦笑", "叹气", "裂开", "666", "强", "抱拳", "握手", "调皮", "憨笑", "愉快",
    "笑脸", "害羞", "脸红", "无语", "嘿哈", "耶", "加油", "汗", "天啊", "社会社会", "好的",
    "打脸", "哇", "翻白眼", "微笑", "撇嘴", "色", "发呆", "得意", "流泪", "闭嘴", "睡",
    "大哭", "尴尬", "发怒", "惊讶", "难过", "囧", "抓狂", "吐", "白眼", "傲慢", "困",
    "惊恐", "流汗", "悠闲", "奋斗", "咒骂", "嘘", "晕", "衰", "骷髅", "敲打", "再见",
    "擦汗", "抠鼻", "鼓掌", "坏笑", "右哼哼", "鄙视", "委屈", "快哭了", "阴险", "亲亲",
    "可怜", "生病", "恐惧", "失望", "皱眉", "嘴唇", "爱心", "心碎", "拥抱", "弱", "胜利",
    "勾引", "拳头", "OK", "合十", "啤酒", "咖啡", "蛋糕", "玫瑰", "凋谢", "庆祝", "礼物",
    "红包", "發", "福", "烟花", "爆竹", "猪头", "跳跳", "发抖", "转圈", "拥抱",
})

WECHAT_EMOJI_ALIAS_MAP: Dict[str, str] = {
    "思考": "机智",
    "想一想": "让我看看",
    "深思": "机智",
    "沉思": "让我看看",
    "笑哭": "破涕为笑",
    "哭笑不得": "破涕为笑",
    "doge": "旺柴",
    "狗头": "旺柴",
    "无奈": "苦笑",
    "摊手": "苦笑",
    "汗颜": "擦汗",
    "点赞": "强",
    "赞": "强",
    "抱抱": "拥抱",
    "哈哈": "呲牙",
    "大笑": "呲牙",
    "好奇": "让我看看",
    "疑惑": "疑问",
    "摸头": "愉快",
    "开心": "愉快",
    "偷乐": "偷笑",
    "比心": "爱心",
}

_PROTECTED_MEDIA_BRACKETS: frozenset[str] = frozenset({
    "图片", "视频", "链接", "语音", "文件", "动画表情", "图片消息", "视频消息",
    "位置", "名片", "红包", "转账", "小程序", "聊天记录",
})


def normalize_wechat_emojis(text: str, *, fallback_emote: str = "[机智]") -> str:
    """Convert non-WeChat bracket emotes like [思考]/[笑哭] into official graphical WeChat emojis."""
    raw = str(text or "")
    if not raw or "[" not in raw:
        return raw

    def _repl(match: re.Match[str]) -> str:
        tag = match.group(1).strip()
        if not tag or tag in _PROTECTED_MEDIA_BRACKETS or tag in OFFICIAL_WECHAT_EMOJIS:
            return match.group(0)
        mapped = WECHAT_EMOJI_ALIAS_MAP.get(tag) or WECHAT_EMOJI_ALIAS_MAP.get(tag.lower())
        if mapped:
            return f"[{mapped}]"
        if not tag.isdigit() and re.fullmatch(r"[\u4e00-\u9fffA-Za-z]{2,5}", tag):
            return fallback_emote if fallback_emote else ""
        return match.group(0)

    return re.sub(r"\[([^\[\]\s:：]{1,6})\]", _repl, raw)


def humanize_wechat_reply(
    text: str,
    *,
    persona_id: str = "warm-friend",
    affect_controls: Optional[ExpressionControls] = None,
    allow_emote: bool = True,
    max_len: int = 160,
    is_template_fallback: bool = False,
) -> str:
    """Apply `ste-anti-slop` + WeChat real-human texting rules to LLM/reply text.

    Rules enforced:
    1. Minimal modal particles & no sycophantic AI openers (`哈哈收到啦`, `哒～`, `呀～`).
    2. Never output enumerated lists (`第一、第二、第三`, `1. 2. 3.`, `首先/其次`).
    3. Fewer stiff punctuation marks (`「」`, `《》`, `；`, `：`) and no trailing `。`.
    4. Optional single restrained WeChat bracket expression (`[旺柴]`, `[捂脸]`) when mood fits.
    """
    raw = str(text or "").strip()
    if not raw:
        return raw

    # Keep exact test/contract template prefixes for formal customer service fallback & RPA expert fallback
    if is_template_fallback and persona_id in ("wecom-kf-pro", "rpa-tech-expert", "concise-assistant"):
        return raw

    out = re.sub(r"\s+", " ", raw.replace("\r", " ").replace("\n", " ")).strip()

    # 1. Strip formulaic AI openers
    out = _AI_FILLER_PREFIX_RE.sub("", out).strip() or out

    # 2. Eliminate "第一、第二、第三" / "1. 2. 3." / "首先、其次"
    if _ENUM_WORD_RE.search(out):
        out = _ENUM_WORD_RE.sub(" ", out)
    if _ENUM_DIGIT_RE.search(out):
        out = _ENUM_DIGIT_RE.sub(" ", out)
    out = re.sub(r"(?:^|[，。；\s])[一二三]是[，、\s]*", " ", out)
    out = re.sub(r"\s+", " ", out).strip()

    # 3. Reduce fake cute particles (~ / 哒 / 呀 / 啦 overuse)
    out = re.sub(r"([啦呀哒呢哇哦呵])～+", r"\1", out)
    out = out.replace("哒", "")
    out = re.sub(r"[～~]+", " ", out)
    out = re.sub(r"[✨👋❤️😄🙂]{2,}", "", out)
    if persona_id != "wecom-kf-pro":
        # Strip trailing robotic emoji glyphs when WeChat bracket emotes or plain text fit better
        out = re.sub(r"\s*[✨👋❤️😄🙂]+\s*$", "", out)

    # 4. Reduce stiff punctuation density: strip unnecessary book/corner brackets & heavy colons
    out = re.sub(r"[「」『』]", "", out)
    if persona_id != "rpa-tech-expert":
        out = re.sub(r"《([^》]{1,28})》", r"\1", out)
    # Replace Chinese semicolons / mid-sentence periods / bullet dots with light comma/space (never break http(s)://)
    out = out.replace("•", "，")
    out = out.replace("；", "，")
    out = re.sub(r"(?<!https)(?<!http)：(?![/\\])", " ", out)
    out = re.sub(r"。\s*(?=[\u4e00-\u9fffA-Za-z0-9])", "，", out)
    out = re.sub(r"[，,]{2,}", "，", out)
    out = re.sub(r"\s+([，,！？])", r"\1", out)
    out = re.sub(r"^[,，。；;：\s]+", "", out).strip()

    # 5. Strip stiff trailing period `。` at message end (real WeChat texting drops trailing full stops)
    out = re.sub(r"。\s*$", "", out).strip()

    # 6. Normalize non-WeChat emoji shortcodes (e.g. [思考] -> [机智]) so WeChat renders graphical yellow faces
    fallback_e = affect_controls.recommended_emote if (affect_controls and affect_controls.recommended_emote) else "[机智]"
    out = normalize_wechat_emojis(out, fallback_emote=fallback_e)

    # 7. Inject context-appropriate official WeChat expression ([旺柴] / [捂脸] / [机智] / [呲牙] etc.)
    has_wechat_emote = any(
        tag in OFFICIAL_WECHAT_EMOJIS
        for tag in re.findall(r"\[([^\[\]\s:：]{1,6})\]", out)
    )
    if (
        allow_emote
        and not has_wechat_emote
        and affect_controls is not None
        and persona_id in ("warm-friend", "owner-digital-twin", "warm-companion")
        and affect_controls.emote_probability >= 0.50
        and affect_controls.recommended_emote
    ):
        emote = normalize_wechat_emojis(affect_controls.recommended_emote)
        if len(out) + len(emote) + 1 <= max_len:
            out = f"{out.rstrip('!！ ')} {emote}"

    out = re.sub(r"\s+", " ", out).strip()
    if len(out) > max_len:
        cut = out[:max_len]
        for sep in ("，", "！", "？", " "):
            idx = cut.rfind(sep)
            if idx >= int(max_len * 0.55):
                return cut[:idx].strip()
        return cut.strip()
    return out


# ---------------------------------------------------------------------------
# 4. Sibyl Feedback Inline Protocol (`s1` / `s2` / `s3 <suggestion>`)
# ---------------------------------------------------------------------------

def parse_sibyl_feedback_command(text: str) -> Optional[Dict[str, str]]:
    """Recognize `susyimes/sibyl-feedback` inline rating/suggestion commands (`s1`, `s2`, `s3 <建议>`)."""
    norm = unicodedata.normalize("NFKC", str(text or "")).strip()
    if not norm:
        return None
    m1 = re.fullmatch(r"s1[.。]?\s*(?:答得好)?", norm, re.IGNORECASE)
    if m1:
        return {"code": "s1", "rating": "good", "suggestion": ""}
    m2 = re.fullmatch(r"s2[.。]?\s*(?:答得差)?", norm, re.IGNORECASE)
    if m2:
        return {"code": "s2", "rating": "bad", "suggestion": ""}
    m3 = re.match(r"^s3[.。]?\s*(.*)$", norm, re.IGNORECASE | re.S)
    if m3:
        return {"code": "s3", "rating": "suggest", "suggestion": m3.group(1).strip()}
    return None
