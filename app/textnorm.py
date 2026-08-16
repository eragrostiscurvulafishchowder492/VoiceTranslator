"""中文文本预处理：数字/字母/时间/百分比/单位/Emoji/网络缩写。

- normal 模式：常规读法（4060 → 四千零六十）
- gaming 模式：保留 FPS/HP/DPS/A/B/C/GG 等游戏术语
"""
import re

from app.common import get_logger

log = get_logger("textnorm")

CN_NUM = {"0": "零", "1": "一", "2": "二", "3": "三", "4": "四", "5": "五",
          "6": "六", "7": "七", "8": "八", "9": "九"}
CN_UNIT = ["", "十", "百", "千", "万", "十万", "百万", "千万", "亿"]

GAMING_TERMS = {"FPS", "HP", "MP", "DPS", "GG", "MVP", "ADC", "AP", "AD", "CD", "BUFF",
                "DEBUFF", "AOE", "KDA", "PK", "PVP", "PVE", "AFK", "OT", "RNG", "T", "N",
                "MMR", "SR", "OP", "GGWP"}

EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u2190-\u21FF\u2B00-\u2BFF\uD83C\uDF00-\uDFFF]+")
URL_RE = re.compile(r"(https?://|www\.)\S+", re.IGNORECASE)
NUM_RE = re.compile(r"\d+(?:\.\d+)?")
PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")
DATE_RE = re.compile(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?")
YEAR_RE = re.compile(r"(\d{4})年")
EN_WORD_RE = re.compile(r"[A-Za-z]+")
MIXED_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([A-Za-z]+)")


def _num_to_cn(n: float, keep_decimal: bool = True) -> str:
    """数字 → 中文（支持整数/小数）。"""
    if n == int(n):
        n = int(n)
    else:
        int_part, dec_part = str(n).split(".")
        out = _int_to_cn(int(int_part))
        return out + "点" + "".join(CN_NUM.get(c, c) for c in dec_part)
    return _int_to_cn(n)


def _int_to_cn(n: int) -> str:
    if n < 0:
        return "负" + _int_to_cn(-n)
    if n == 0:
        return "零"
    if n < 10:
        return CN_NUM[str(n)]
    if n < 20:
        return "十" + (CN_NUM[str(n % 10)] if n % 10 else "")
    if n < 100:
        t, r = divmod(n, 10)
        return CN_NUM[str(t)] + "十" + (CN_NUM[str(r)] if r else "")
    if n < 10000:
        out = ""
        unit = 0
        zero = False
        while n > 0:
            n, d = divmod(n, 10)
            if d == 0:
                if out and not zero:
                    out = "零" + out
                    zero = True
            else:
                out = CN_NUM[str(d)] + CN_UNIT[unit] + out
                zero = False
            unit += 1
        return out
    # 万以上
    wan, rem = divmod(n, 10000)
    out = _int_to_cn(wan) + "万"
    if rem:
        out += _int_to_cn(rem)
    return out


def normalize_chinese_text(text: str, mode: str = "gaming") -> str:
    """核心归一化入口。"""
    if not text:
        return text
    t = text
    t = EMOJI_RE.sub("", t)
    t = URL_RE.sub("链接", t)
    t = t.replace("\u3000", " ")

    # 日期/年份
    t = DATE_RE.sub(lambda m: f"{_int_to_cn(int(m.group(1)))}年{_int_to_cn(int(m.group(2)))}月{_int_to_cn(int(m.group(3)))}日", t)
    t = YEAR_RE.sub(lambda m: f"{_int_to_cn(int(m.group(1)))}年", t)
    # 时间 HH:MM
    t = TIME_RE.sub(lambda m: f"{_int_to_cn(int(m.group(1)))}点{_int_to_cn(int(m.group(2)))}分", t)
    # 百分比
    t = PCT_RE.sub(lambda m: f"百分之{_num_to_cn(float(m.group(1)))}", t)

    # 数字+单位（如 10 秒 → 十秒）
    def _unit_sub(m):
        num = float(m.group(1))
        unit = m.group(2)
        if mode == "gaming" and unit.upper() in GAMING_TERMS:
            return f"{m.group(1)}{unit}"
        return f"{_num_to_cn(num)}{unit}"
    t = MIXED_RE.sub(_unit_sub, t)

    # 裸数字
    t = NUM_RE.sub(lambda m: _num_to_cn(float(m.group(0))), t)

    # 英文单词
    def _en_sub(m):
        w = m.group(0)
        if mode == "gaming" and w.upper() in GAMING_TERMS:
            return w
        # 逐字母读出（英文缩写）
        return " ".join(_letter_zh(c) for c in w)
    t = EN_WORD_RE.sub(_en_sub, t)
    return t


def _letter_zh(c: str) -> str:
    c = c.upper()
    m = {"A": "诶", "B": "比", "C": "西", "D": "迪", "E": "伊", "F": "艾弗", "G": "吉",
         "H": "艾尺", "I": "艾", "J": "杰", "K": "开", "L": "艾勒", "M": "艾姆", "N": "恩",
         "O": "欧", "P": "屁", "Q": "扣", "R": "阿", "S": "艾斯", "T": "提", "U": "优",
         "V": "维", "W": "达不溜", "X": "艾克斯", "Y": "歪", "Z": "贼"}
    return m.get(c, c)


def split_sentences(text: str) -> list[str]:
    """按中文标点切句（保留标点）。"""
    parts = re.split(r"([。！？；……])", text)
    out = []
    buf = ""
    for p in parts:
        buf += p
        if p and p in "。！？；……":
            out.append(buf)
            buf = ""
    if buf.strip():
        out.append(buf)
    return [s for s in out if s.strip()]