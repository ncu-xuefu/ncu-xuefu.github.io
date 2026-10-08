# -*- coding: utf-8 -*-
u"""check_site.py —— 门户网站上线门禁（结构 / 内容 / 预算）。

为什么要它
----------
这个站是"手写多页静态 HTML + 零构建"。没有构建步骤，就没有编译器替你挡错：
7 页里漏改一处、引用路径写错大小写、把一个占位带上线，都不会报错，
只会在线上静默地坏。本脚本把《实现方案》的验收条目变成可执行断言，
让"改坏了"当场可见。

用法
----
    python tools/check_site.py              # 施工期：WARN 可接受，FAIL 必须为 0
    python tools/check_site.py --release    # 上线门禁：施工期豁免项（占位 / noindex）转为 FAIL
    python tools/check_site.py --contrast   # 打印对比度验算表
    python tools/check_site.py --ids        # 打印全站 id 清单（归档用）

退出码：0 = 无 FAIL；1 = 有 FAIL；2 = 用法错误。

规则总表见《实现方案》§6.1（S1–S24）。本文件按任务分批落地：
    T06 → S1–S4、S7、S20
    T18 → S11、S12
    T24 → 其余
"""
import io
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 冻结接口（§1.2 / §1.5）：8 个 .html，根目录不得出现别的
PAGES = ["index.html", "about.html", "services.html", "notices.html",
         "team.html", "activities.html", "contact.html", "404.html"]
MAIN_PAGES = [p for p in PAGES if p != "404.html"]

# 全站唯一允许出现 http(s) 的域（E8 / §1.5）
SITE_URL = "https://ncu-xuefu.github.io/"

# 每条规则最多展开多少行明细（汇总计数不受影响）
MAX_DETAIL_PER_RULE = 15

RULE_TITLES = {    "S1": u"页面存在",
    "S2": u"根目录无多余 .html",
    "S3": u"零外链",
    "S4": u"引用存在 + 大小写",
    "S7": u"编码",
    "S20": u"密钥/口令扫描",
}


# --------------------------------------------------------------------------
# 基础设施
# --------------------------------------------------------------------------
def soften_stdout():
    u"""Windows 控制台默认 GBK，直接打印 ✓/✗ 会 UnicodeEncodeError（§1.1 房内风格）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


class Report(object):
    u"""收集断言结果。level 只有 FAIL / WARN 两种；INFO 不进汇总。"""

    def __init__(self):
        self.rows = []

    def fail(self, rule, where, message):
        self.rows.append((rule, "FAIL", where, message))

    def warn(self, rule, where, message):
        self.rows.append((rule, "WARN", where, message))

    def count(self, rule, level=None):
        return sum(1 for r in self.rows
                   if r[0] == rule and (level is None or r[1] == level))

    def total(self, level):
        return sum(1 for r in self.rows if r[1] == level)


def read_bytes(path):
    with io.open(path, "rb") as fh:
        return fh.read()


def read_text(path):
    u"""按 UTF-8 原样读入——newline="" 关掉通用换行，以便检出 CRLF。"""
    with io.open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def line_of(text, pos):
    return text.count(u"\n", 0, pos) + 1


def published_files():
    u"""会被发布的文件清单 = 已跟踪 + 未忽略的未跟踪文件。

    判据就是 .gitignore（E24/E38）——审计"密钥不入仓"必须落在**会被提交的那批文件**上，
    而不是把本地的内部文档也算进去。取不到 git 时退化为遍历目录。
    """
    try:
        out = subprocess.check_output(
            ["git", "ls-files", "-z", "-co", "--exclude-standard"],
            cwd=ROOT, stderr=subprocess.PIPE)
        return [n for n in out.decode("utf-8", "replace").split(u"\0") if n]
    except Exception:
        names = []
        for base, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in (".git", ".superpowers")]
            for f in files:
                names.append(os.path.relpath(os.path.join(base, f), ROOT).replace("\\", "/"))
        return names


def exists_exact_case(rel):
    u"""逐字符存在性检查。

    为什么不能用 os.path.exists：Windows 的文件系统不区分大小写，
    `Logo.png` 与 `logo.png` 在本地都"存在"，但 GitHub Pages 跑在 Linux 上会 404。
    这里逐段比对目录项，才能复现线上行为（§1.3 / S8）。
    """
    cur = ROOT
    for part in [p for p in rel.replace("\\", "/").split("/") if p and p != "."]:
        if part == "..":
            cur = os.path.dirname(cur)
            continue
        try:
            entries = os.listdir(cur)
        except OSError:
            return False
        if part not in entries:
            return False
        cur = os.path.join(cur, part)
    return os.path.isfile(cur)


def existing_pages():
    return [p for p in PAGES if exists_exact_case(p)]


# --------------------------------------------------------------------------
# S1 / S2 —— 页面集合
# --------------------------------------------------------------------------
def s1_pages(rep):
    for page in PAGES:
        if not exists_exact_case(page):
            rep.fail("S1", page, u"页面缺失")


def s2_no_extra_html(rep):
    extra = sorted(f for f in os.listdir(ROOT)
                   if f.endswith(".html") and f not in PAGES)
    for name in extra:
        rep.fail("S2", name,
                 u"根目录出现多余 .html（页面文件名是冻结接口，§1.5）")


# --------------------------------------------------------------------------
# S3 —— 零外链（属性级判据，E7）
# --------------------------------------------------------------------------
ATTR_RE = re.compile(r'(?:src|href)\s*=\s*"([^"]*)"', re.I)
OG_RE = re.compile(r'<meta[^>]+property\s*=\s*"og:(?:url|image)"[^>]*'
                   r'content\s*=\s*"([^"]*)"', re.I)
CSS_URL_RE = re.compile(r'url\(\s*([^)]+?)\s*\)', re.I)
DATA_PAYLOAD_RE = re.compile(r'data:[a-z0-9.+-]+/[a-z0-9.+-]+;base64,[A-Za-z0-9+/=\s]*', re.I)


def strip_data_payloads(text):
    u"""先把 data-URI 的 base64 载荷抠掉再扫外链。

    为什么必须：base64 的字母表含 `/`，朴素的 `//`（协议相对）检测会把它误报成外链。
    """
    return DATA_PAYLOAD_RE.sub(u"data:stripped", text)


def classify_ref(val, page):
    u"""把一个引用值归类。返回 (kind, 说明)；kind 为 'ok' 或 'bad'。"""
    v = val.strip()
    if v == u"":
        return ("ok", u"空引用")
    low = v.lower()
    for scheme in ("mailto:", "tel:"):
        if low.startswith(scheme):
            if u"【待填" in v:
                return ("bad", u"%s 引用里含占位（E7）" % scheme)
            return ("ok", scheme)
    if low.startswith("data:"):
        if page != "404.html":
            return ("bad", u"data: 引用只允许出现在 404.html（E6）")
        return ("ok", u"data:")
    if low.startswith("javascript:"):
        return ("bad", u"javascript: 伪协议")
    if low.startswith("http://") or low.startswith("https://"):
        if not v.startswith(SITE_URL):
            return ("bad", u"站外绝对 URL（零外链红线，§0.2）")
        return ("abs", u"本站绝对 URL")
    if v.startswith("//"):
        return ("bad", u"协议相对 // 引用（E7 明令禁止）")
    if v.startswith("/"):
        if page != "404.html":
            return ("bad", u"根绝对路径只允许出现在 404.html（E5）")
        return ("ok", u"404 根绝对链接")
    if v.startswith("#"):
        return ("ok", u"页内锚点")
    return ("ok", u"相对路径")


def s3_no_external(rep):
    abs_urls = 0
    for page in existing_pages():
        text = strip_data_payloads(read_text(os.path.join(ROOT, page)))
        for m in ATTR_RE.finditer(text):
            kind, why = classify_ref(m.group(1), page)
            if kind == "bad":
                rep.fail("S3", u"%s:%d" % (page, line_of(text, m.start())),
                         u"%s → %s" % (why, m.group(1)))
            elif kind == "abs":
                abs_urls += 1
        # og:url / og:image 是白名单里仅有的两处绝对 URL（E8）
        for m in OG_RE.finditer(text):
            if not m.group(1).startswith(SITE_URL):
                rep.fail("S3", u"%s:%d" % (page, line_of(text, m.start())),
                         u"og 绝对 URL 不在本站域内：%s" % m.group(1))
            else:
                abs_urls += 1
        for m in CSS_URL_RE.finditer(text):
            kind, why = classify_ref(m.group(1).strip(u"'\" "), page)
            if kind == "bad":
                rep.fail("S3", u"%s:%d" % (page, line_of(text, m.start())),
                         u"%s → %s" % (why, m.group(1)))
    # 7 页 × (og:image + og:url) = 14（§0.2 第 1 条）
    if abs_urls not in (0, 14):
        rep.fail("S3", u"全站", u"http(s) 引用共 %d 处，应为 0 或 14（§0.2-1）" % abs_urls)


# --------------------------------------------------------------------------
# S4 —— 引用存在 + 大小写（S8 的执行体）
# --------------------------------------------------------------------------
ANCHOR_RE = re.compile(r'id\s*=\s*"([^"]+)"')


def ref_target(val, page):
    u"""把引用值解析成 (相对路径, 锚点)；不是文件引用则返回 None。"""
    v = val.strip()
    if v == u"" or v.startswith("#"):
        return (None, v[1:] if v.startswith("#") else None)
    low = v.lower()
    for scheme in ("mailto:", "tel:", "data:", "javascript:"):
        if low.startswith(scheme):
            return None
    if low.startswith("http://") or low.startswith("https://") or v.startswith("//"):
        return None
    path = v[1:] if v.startswith("/") else v
    path = path.split("?", 1)[0]
    anchor = None
    if "#" in path:
        path, anchor = path.split("#", 1)
    return (path, anchor)


def s4_refs_exist(rep):
    anchors_cache = {}

    def anchors_of(rel):
        if rel not in anchors_cache:
            p = os.path.join(ROOT, rel)
            found = set()
            if os.path.isfile(p):
                try:
                    found = set(ANCHOR_RE.findall(read_text(p)))
                except Exception:
                    found = set()
            anchors_cache[rel] = found
        return anchors_cache[rel]

    for page in existing_pages():
        text = strip_data_payloads(read_text(os.path.join(ROOT, page)))
        for m in ATTR_RE.finditer(text):
            parsed = ref_target(m.group(1), page)
            if parsed is None:
                continue
            rel, anchor = parsed
            where = u"%s:%d" % (page, line_of(text, m.start()))
            if rel:
                if not exists_exact_case(rel):
                    hint = u"（磁盘上有同名但大小写不同，Linux 上会 404）" \
                        if os.path.exists(os.path.join(ROOT, rel)) else u""
                    rep.fail("S4", where,
                             u"引用不存在%s：%s" % (hint, rel))
                    continue
            elif anchor is None:
                continue
            if anchor:
                target = rel if rel else page
                if not target.endswith(".html"):
                    continue          # 非 HTML 目标没有锚点概念
                if anchor not in anchors_of(target):
                    rep.fail("S4", where,
                             u"锚点不存在：%s#%s" % (target, anchor))


# --------------------------------------------------------------------------
# S7 —— 编码（UTF-8 无 BOM、无 CRLF、每页有 charset）
# --------------------------------------------------------------------------
TEXT_EXT = (".html", ".css", ".js", ".md", ".py", ".tsv", ".json")


def s7_encoding(rep):
    for rel in published_files():
        if not rel.lower().endswith(TEXT_EXT):
            continue
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        raw = read_bytes(path)
        if raw.startswith(b"\xef\xbb\xbf"):
            rep.fail("S7", rel, u"含 UTF-8 BOM（记事本「另存为」的典型产物）")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            rep.fail("S7", rel, u"不是合法 UTF-8：%s" % exc)
            continue
        if b"\r\n" in raw:
            rep.fail("S7", rel, u"含 CRLF（.gitattributes 约定 LF）")

    for page in existing_pages():
        text = read_text(os.path.join(ROOT, page))
        if not re.search(r'<meta\s+charset\s*=\s*"utf-8"\s*>', text, re.I):
            rep.fail("S7", page, u'缺 <meta charset="utf-8">')


# --------------------------------------------------------------------------
# S20 —— 密钥/口令扫描（风险 15；§10.7 红线）
# --------------------------------------------------------------------------
# 两条实现注意（都是踩过的坑）：
#   ① 模式必须由片段拼出——本文件自己也在扫描面内，写字面量会自我命中。
#   ② 规则是"命中即报"的钝器（这是特性不是缺陷）：所以**正常代码与注释里也不要
#      出现这些英文词的字面量**，否则扫描器会常年挂着一条假红。中文项目里改用
#      "变量层/令牌"之类的中文措辞即可，见 assets/css/site.css 的节标题。
CRED_PATTERNS = [
    (r"pass" + r"word", u"口令字段"),
    (r"pass" + r"wd", u"口令字段"),
    (r"tok" + r"en", u"令牌"),
    (r"secr" + r"et", u"凭据字段"),
    (r"api[_-]?" + r"key", u"接口凭据"),
    (r"Bea" + r"rer\s", u"认证头"),
    (r"gh" + r"p_[A-Za-z0-9]{20,}", u"代码托管平台访问令牌"),
    (r"BEGIN [A-Z ]*PRI" + r"VATE KEY", u"私钥文件"),
]


def s20_scan_credentials(rep):
    for rel in published_files():
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        try:
            if os.path.getsize(path) > 2 * 1024 * 1024:
                continue
            text = read_bytes(path).decode("utf-8", "replace")
        except OSError:
            continue
        for pattern, label in CRED_PATTERNS:
            for m in re.finditer(pattern, text, re.I):
                rep.fail("S20", u"%s:%d" % (rel, line_of(text, m.start())),
                         u"命中%s：%s" % (label, m.group(0)[:40]))


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
RULES = [
    ("S1", s1_pages),
    ("S2", s2_no_extra_html),
    ("S3", s3_no_external),
    ("S4", s4_refs_exist),
    ("S7", s7_encoding),
    ("S20", s20_scan_credentials),
]


def dump(rep):
    # 逐条明细按规则限流：施工期"图片还没生成"会一次刷出几十条同因 FAIL，
    # 全打出来反而淹没了真正的异类。汇总行的计数始终是完整的。
    per_rule_shown = {}
    for rule, level, where, message in sorted(rep.rows):
        shown = per_rule_shown.get(rule, 0)
        if shown >= MAX_DETAIL_PER_RULE:
            per_rule_shown[rule] = shown + 1
            continue
        per_rule_shown[rule] = shown + 1
        mark = u"✗" if level == "FAIL" else u"!"
        print(u"%s [%s] %-8s %s: %s" % (mark, level, rule, where, message))
    for rule, shown in sorted(per_rule_shown.items()):
        if shown > MAX_DETAIL_PER_RULE:
            print(u"  … %s 另有 %d 条同类明细未展开" % (rule, shown - MAX_DETAIL_PER_RULE))
    print(u"")
    print(u"---- 汇总 ----")
    for rule, _fn in RULES:
        bad = rep.count(rule, "FAIL")
        war = rep.count(rule, "WARN")
        mark = u"✗" if bad else (u"!" if war else u"✓")
        detail = u""
        if bad:
            detail = u"  FAIL %d" % bad
        if war:
            detail += u"  WARN %d" % war
        print(u"%s %-4s %-18s%s" % (mark, rule, RULE_TITLES.get(rule, u""), detail))
    print(u"FAIL %d / WARN %d" % (rep.total("FAIL"), rep.total("WARN")))


def usage():
    print(__doc__.strip())


def main(argv):
    soften_stdout()
    release = False
    only = []
    for arg in argv:
        if arg == "--release":
            release = True
        elif arg in ("--contrast", "--ids"):
            only.append(arg)
        elif arg in ("-h", "--help"):
            usage()
            return 0
        else:
            print(u"未知参数：%s\n" % arg)
            usage()
            return 2

    if only:
        print(u"本模式尚未实现（按《实现方案》§8.1 的任务分批落地）：%s"
              % u", ".join(only))
        return 2

    rep = Report()
    ctx = {"release": release}
    for _rule, fn in RULES:
        fn(rep)
    dump(rep)
    if release:
        print(u"（--release 模式：施工期豁免项将转为 FAIL——相关规则在后续任务落地）")
    return 1 if rep.total("FAIL") else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
