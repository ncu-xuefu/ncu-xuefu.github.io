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

RULE_TITLES = {
    "S1": u"页面存在",
    "S2": u"根目录无多余 .html",
    "S3": u"零外链",
    "S4": u"引用存在 + 大小写",
    "S5": u"占位计数",
    "S6": u"同步块一致",
    "S7": u"编码",
    "S8": u"每页 meta",
    "S9": u"标题层级",
    "S10": u"缓存串",
    "S11": u"img 五属性",
    "S12": u"图片与清单一致",
    "S13": u"JS 断言",
    "S14": u"禁用特性",
    "S15": u"id 体系",
    "S16": u"对比度验算",
    "S17": u"首页同步 / 空状态",
    "S18": u"表格",
    "S19": u"class 封闭清单",
    "S20": u"密钥/口令扫描",
    "S21": u"noindex 规则",
    "S22": u"404 专项",
    "S23": u"隐私词",
    "S24": u"体积预算",
}

# 全局：--release 时施工期豁免项转为 FAIL（E3）
RELEASE = False


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
    u"""收集断言结果。FAIL/WARN 进汇总；INFO 只报事实（体积、计数），不影响退出码。"""

    def __init__(self):
        self.rows = []

    def fail(self, rule, where, message):
        self.rows.append((rule, "FAIL", where, message))

    def warn(self, rule, where, message):
        self.rows.append((rule, "WARN", where, message))

    def info(self, message):
        self.rows.append(("", "INFO", "", message))

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
def s1_pages(rep, ctx):
    for page in PAGES:
        if not exists_exact_case(page):
            rep.fail("S1", page, u"页面缺失")


def s2_no_extra_html(rep, ctx):
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


COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def strip_comments(text):
    u"""把 HTML 注释挖空（保留其中的换行，行号不变）。

    为什么：注释里的示例代码不是页面内容。activities.html 就有一段"M4 怎么上活动卡"
    的说明注释，里面写着 `<article class="activity">` 与示例图片名——不挖掉的话，
    S17 会以为活动页已经有条目、S12 会去找一张不存在的示例图，全是假报警。
    """
    return COMMENT_RE.sub(lambda m: u"\n" * m.group(0).count(u"\n"), text)


def clean_for_scan(text):
    u"""扫描前的统一清理：先挖注释，再抠 data-URI 载荷。"""
    return strip_data_payloads(strip_comments(text))


def strip_css_comments(text):
    return re.sub(r"/\*.*?\*/", lambda m: u"\n" * m.group(0).count(u"\n"), text, flags=re.S)


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


def s3_no_external(rep, ctx):
    abs_urls = 0
    for page in existing_pages():
        text = clean_for_scan(read_text(os.path.join(ROOT, page)))
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


def s4_refs_exist(rep, ctx):
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
        text = clean_for_scan(read_text(os.path.join(ROOT, page)))
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


def s7_encoding(rep, ctx):
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


def s20_scan_credentials(rep, ctx):
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
# S11 —— 图片五属性（E26 的姊妹项：分辨率与懒加载都要在源码里看得见）
# --------------------------------------------------------------------------
IMG_RE = re.compile(r"<img\b[^>]*>", re.I)
ATTR_ONE_RE = re.compile(r'([a-zA-Z-]+)\s*=\s*"([^"]*)"')

# loading="eager" 的白名单：只有这两个"首屏图"可以不等懒加载（§6.1-S11）
EAGER_CLASSES = ("brand-mark", "hero-mascot")

# 只要求"四属性"的例外：这两个 <img> 躺在逐字节冻结的 COMMON 块里（§3.1 的字面量
# 只给了 src/width/height/alt），而附录 E-3 明令 COMMON/SYNC 模板不得改。
# 计划书里真正有验收判据的是 R4（alt + width + height）与 P3（首屏外 lazy）——
# 这两条它们都满足；decoding 属方案自加的收紧项，冲突时让位于冻结块。
# 详见台账的 Ruling（T18）。
FROZEN_BLOCK_IMGS = ("assets/img/logo-emblem-120.png", "assets/img/logo-emblem-64.png")


def parse_attrs(tag):
    return dict((k.lower(), v) for k, v in ATTR_ONE_RE.findall(tag))


def s11_img_attrs(rep, ctx):
    # 只查 7 个页面：404 的两张图是 data-URI **内联**的（E6），
    # 没有网络请求，lazy/async 无意义；而 §3.11 是逐字冻结块，不得为它改 HTML。
    for page in [p for p in MAIN_PAGES if exists_exact_case(p)]:
        text = clean_for_scan(read_text(os.path.join(ROOT, page)))
        for m in IMG_RE.finditer(text):
            attrs = parse_attrs(m.group(0))
            where = u"%s:%d" % (page, line_of(text, m.start()))
            needed = ["src", "alt", "width", "height"]
            if attrs.get("src", u"") not in FROZEN_BLOCK_IMGS:
                needed += ["loading", "decoding"]
            for need in needed:
                if need not in attrs:
                    rep.fail("S11", where, u"<img> 缺属性 %s" % need)
            loading = attrs.get("loading", u"")
            classes = attrs.get("class", u"").split()
            if loading == "eager":
                if not any(c in classes for c in EAGER_CLASSES):
                    rep.fail("S11", where,
                             u'loading="eager" 只允许 .brand-mark / .hero-mascot（R4/P3）')
            elif loading and loading != "lazy":
                rep.fail("S11", where, u'loading 只能 "lazy"，首屏白名单内才可 "eager"'
                         u'（收到 "%s"）' % loading)
            dec = attrs.get("decoding")
            if dec is not None and dec != "async":
                rep.fail("S11", where, u'decoding 应为 "async"，收到 "%s"' % dec)


# --------------------------------------------------------------------------
# S12 —— 图片与清单一致（E31）
# --------------------------------------------------------------------------
MANIFEST_REL = "assets/img/image-manifest.tsv"


def load_manifest():
    path = os.path.join(ROOT, MANIFEST_REL.replace("/", os.sep))
    if not os.path.isfile(path):
        return None
    out = {}
    lines = read_text(path).split(u"\n")
    for line in lines[1:]:
        parts = line.split(u"\t")
        if len(parts) != 4:
            continue
        try:
            out[parts[0]] = (int(parts[1]), int(parts[2]), int(parts[3]))
        except ValueError:
            continue
    return out


def byte_cap(rel):
    u"""单图体积上限（§1.2：任何图 ≤300 KB；活动封面 ≤150 KB；OG ≤200 KB）。"""
    if rel.endswith("og-cover.png"):
        return 200 * 1024
    if "/activities/" in rel and os.path.basename(rel).startswith("cover-"):
        return 150 * 1024
    return 300 * 1024


def s12_img_manifest(rep, ctx):
    man = load_manifest()
    if man is None:
        rep.warn("S12", MANIFEST_REL, u"清单不存在，跳过图片交叉断言（先跑 make_images.py）")
        return
    for page in [p for p in MAIN_PAGES if exists_exact_case(p)]:
        text = clean_for_scan(read_text(os.path.join(ROOT, page)))
        for m in IMG_RE.finditer(text):
            attrs = parse_attrs(m.group(0))
            src = attrs.get("src", u"")
            where = u"%s:%d" % (page, line_of(text, m.start()))
            if not src or src.startswith("data:"):
                continue
            if src not in man:
                rep.fail("S12", where, u"src 不在图片清单内：%s" % src)
                continue
            fw, fh, fbytes = man[src]
            try:
                aw, ah = int(attrs["width"]), int(attrs["height"])
            except (KeyError, ValueError):
                continue          # 属性缺失/非数字已由 S11 报过，此处不重复刷屏
            if ah and fh and abs(aw / float(ah) - fw / float(fh)) > 0.01:
                rep.fail("S12", where,
                         u"属性宽高比与文件不符（属性 %d×%d / 文件 %d×%d）" % (aw, ah, fw, fh))
            # §5.4 "只缩不放"：显示尺寸不得大于文件自然尺寸
            if aw > fw or ah > fh:
                rep.fail("S12", where,
                         u"放大引用（属性 %d×%d > 文件 %d×%d）" % (aw, ah, fw, fh))
            cap = byte_cap(src)
            if fbytes > cap:
                rep.fail("S12", src, u"体积 %d B 超上限 %d" % (fbytes, cap))


# --------------------------------------------------------------------------
# S5 —— 占位三重计数（E2/E3；施工期 WARN、上线门禁 FAIL）
# --------------------------------------------------------------------------
PLACEHOLDER_PREFIX = u"【待填"


def s5_placeholders(rep, ctx):
    total = 0
    for page in existing_pages():
        raw = read_text(os.path.join(ROOT, page))
        n_text = raw.count(PLACEHOLDER_PREFIX)
        n_span = raw.count(u'class="ph"')
        n_todo = len(re.findall(r"<!--\s*TODO", raw))
        total += n_text
        if n_text != n_span:
            # 对账失败 = 有占位没被 .ph 包住 → 页面上不显眼 → 迟早被带上线。
            # 计划书原来的"S5 计数 = 0"是假绿（实际占位是【待填·xx】，"【待填】"字面永为 0，E2）。
            rep.fail("S5", page,
                     u'占位对账失败：`【待填` %d 处，`class="ph"` %d 处' % (n_text, n_span))
        if n_todo:
            rep.warn("S5", page, u"`<!-- TODO` %d 处" % n_todo)
    if total == 0:
        rep.info(u"占位计数：0（可以上线了）")
        return
    msg = u"全站仍有 %d 处占位（施工期 WARN；--release 下为 FAIL）" % total
    if ctx.get("release"):
        rep.fail("S5", u"全站", msg)
    else:
        rep.warn("S5", u"全站", msg)


# --------------------------------------------------------------------------
# S6 —— 同步块一致（复用 sync_common）
# --------------------------------------------------------------------------
def s6_sync_blocks(rep, ctx):
    tool = os.path.join(ROOT, "tools", "sync_common.py")
    if not os.path.isfile(tool):
        rep.warn("S6", u"sync_common.py", u"工具不存在，跳过")
        return
    try:
        subprocess.check_output([sys.executable, tool, "--check"],
                                cwd=ROOT, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as exc:
        text = exc.output.decode("utf-8", "replace")
        for line in text.split(u"\n"):
            if line.startswith(u"✗"):
                rep.fail("S6", u"sync_common", line.lstrip(u"✗ ").strip())
    except Exception as exc:                      # noqa: BLE001 —— 工具跑不起来只降级为 WARN
        rep.warn("S6", u"sync_common.py", u"无法运行：%s" % exc)


# --------------------------------------------------------------------------
# S8 —— 每页 meta 齐全且 description 互异
# --------------------------------------------------------------------------
REQUIRED_META = [
    (r'<meta\s+charset\s*=\s*"utf-8"\s*>', u"charset"),
    (r'<meta\s+name="viewport"', u"viewport"),
    (r'<meta\s+name="theme-color"', u"theme-color"),
    (r'<meta\s+name="format-detection"', u"format-detection"),
    (r'<meta\s+name="description"\s+content="[^"]+"', u"description"),
    (r'<meta\s+property="og:title"', u"og:title"),
    (r'<meta\s+property="og:description"', u"og:description"),
    (r'<meta\s+property="og:url"', u"og:url"),
    (r'<meta\s+property="og:type"', u"og:type"),
    (r'<meta\s+property="og:site_name"', u"og:site_name"),
    (r'<meta\s+property="og:image"', u"og:image"),
    (r'<meta\s+property="og:locale"', u"og:locale"),
]
DESC_RE = re.compile(r'<meta\s+name="description"\s+content="([^"]*)"', re.I)


def s8_meta(rep, ctx):
    seen = {}
    for page in [p for p in MAIN_PAGES if exists_exact_case(p)]:
        text = strip_comments(read_text(os.path.join(ROOT, page)))
        for pattern, label in REQUIRED_META:
            if not re.search(pattern, text, re.I):
                rep.fail("S8", page, u"缺 %s" % label)
        m = DESC_RE.search(text)
        if m:
            d = m.group(1)
            if d in seen:
                rep.fail("S8", page, u"description 与 %s 完全相同（复制忘改）" % seen[d])
            seen[d] = page


# --------------------------------------------------------------------------
# S9 —— 标题层级：每页唯一 h1、无跳级
# --------------------------------------------------------------------------
HEADING_RE = re.compile(r"<h([1-6])\b", re.I)


def s9_headings(rep, ctx):
    for page in existing_pages():
        text = clean_for_scan(read_text(os.path.join(ROOT, page)))
        seq = [int(x) for x in HEADING_RE.findall(text)]
        if seq.count(1) != 1:
            rep.fail("S9", page, u"<h1> 有 %d 个（应恰好 1 个）" % seq.count(1))
        seen = set()
        for lvl in seq:
            if lvl > 1 and (lvl - 1) not in seen:
                rep.fail("S9", page, u"标题跳级：出现 h%d，但前面还没有 h%d" % (lvl, lvl - 1))
                break
            seen.add(lvl)


# --------------------------------------------------------------------------
# S10 —— 缓存串：css 与 js 同值，且为 8 位日期（E9）
# --------------------------------------------------------------------------
def s10_cache_version(rep, ctx):
    values = set()
    for page in [p for p in MAIN_PAGES if exists_exact_case(p)]:
        text = read_text(os.path.join(ROOT, page))
        css = re.findall(r'assets/css/site\.css\?v=([^"&]*)', text)
        js = re.findall(r'assets/js/site\.js\?v=([^"&]*)', text)
        if len(css) != 1:
            rep.fail("S10", page, u"site.css 的 ?v= 有 %d 处（应 1 处）" % len(css))
        if len(js) != 1:
            rep.fail("S10", page, u"site.js 的 ?v= 有 %d 处（应 1 处）" % len(js))
        values.update(css)
        values.update(js)
    for v in sorted(values):
        if not re.match(r"^\d{8}$", v):
            rep.fail("S10", u"全站", u"?v=%s 不是 8 位日期" % v)
    if len(values) > 1:
        rep.fail("S10", u"全站", u"css 与 js 的 ?v= 不一致：%s（E9 要求同值）" % sorted(values))


# --------------------------------------------------------------------------
# S13 —— JS 断言（§4.3）
# --------------------------------------------------------------------------
BANNED_JS = [u"innerHTML", u"document.write", u"eval(", u"fetch(", u"localStorage", u"closest("]
SITE_SCRIPT_RE = re.compile(r'^<script src="assets/js/site\.js\?v=\d{8}" defer>$')
NAV_TARGETS = ["index.html", "about.html", "services.html", "notices.html",
               "team.html", "activities.html", "contact.html"]


def s13_js(rep, ctx):
    js_rel = "assets/js/site.js"
    js_path = os.path.join(ROOT, js_rel.replace("/", os.sep))
    if not os.path.isfile(js_path):
        rep.fail("S13", js_rel, u"不存在")
        return
    size = os.path.getsize(js_path)
    if size > 2048:
        rep.fail("S13", js_rel, u"体积 %d B 超 2 KB（§4.1）" % size)

    # 必须在**剔除注释**后判禁用 API：§4.1 的 site.js 是逐字冻结块，它开头的
    # docstring 恰好逐字列着这几个词，朴素 grep 会把冻结块自己判红。
    code = strip_css_comments(read_text(js_path))
    code = re.sub(r"//[^\n]*", u"", code)
    for bad in BANNED_JS:
        if bad in code:
            rep.fail("S13", js_rel, u"出现禁用 API：%s（§4.3）" % bad)

    js_files = [f for f in published_files() if f.lower().endswith(".js")]
    if len(js_files) != 1:
        rep.fail("S13", u"全站", u"应只有一个 .js，实际：%s" % js_files)

    for page in [p for p in MAIN_PAGES if exists_exact_case(p)]:
        text = strip_comments(read_text(os.path.join(ROOT, page)))
        tags = re.findall(r"<script\b[^>]*>", text)
        if len(tags) != 1:
            rep.fail("S13", page, u"<script> 有 %d 个（应 1 个）" % len(tags))
        elif not SITE_SCRIPT_RE.match(tags[0]):
            rep.fail("S13", page, u"<script> 形式不符：%s" % tags[0])
        # 导航必须在 HTML 源码里——这是"无 JS 也能导航"的机械证明（R7/R5）
        for name in NAV_TARGETS:
            if u'href="%s"' % name not in text:
                rep.fail("S13", page, u"源码里缺导航链接 %s" % name)


# --------------------------------------------------------------------------
# S14 —— 禁用特性（§2.9）：对 site.css 与全部 HTML 做 grep 断言
# --------------------------------------------------------------------------
BANNED_CSS = [":has(", ":is(", ":where(", "@container", "subgrid", "aspect-ratio",
              "margin-inline", "padding-inline", "inset:", "::marker", "text-wrap:balance",
              "scroll-behavior", "backdrop-filter", "transition:all", "min(", "max("]


def s14_banned_features(rep, ctx):
    css_path = os.path.join(ROOT, "assets", "css", "site.css")
    targets = []
    if os.path.isfile(css_path):
        targets.append(("assets/css/site.css", strip_css_comments(read_text(css_path))))
    for page in existing_pages():
        targets.append((page, strip_comments(read_text(os.path.join(ROOT, page)))))
    for name, text in targets:
        for bad in BANNED_CSS:
            for m in re.finditer(re.escape(bad), text):
                rep.fail("S14", u"%s:%d" % (name, line_of(text, m.start())),
                         u"出现禁用特性 %s（§2.9）" % bad)
    # flex 的 gap 无法用 grep 区分（Grid 的 gap 是允许的），§2.9 明确列为人工核对项。
    if os.path.isfile(css_path):
        css = strip_css_comments(read_text(css_path))
        props = re.findall(r"([a-z-]+)\s*:[^;{}]*clamp\(", css)
        if len(re.findall(r"clamp\(", css)) > 4:
            rep.fail("S14", "assets/css/site.css", u"clamp() 超过 4 处（E12）")
        for prop in props:
            if prop != "font-size":
                rep.fail("S14", "assets/css/site.css",
                         u"clamp() 只能用于 font-size，出现在 %s（E12）" % prop)


# --------------------------------------------------------------------------
# S15 —— id 体系（E16）
# --------------------------------------------------------------------------
ID_ATTR_RE = re.compile(r'id="([^"]+)"')
NOTICE_ID_RE = re.compile(r"^n-\d{8}-[a-z0-9-]+$")
ACT_ID_RE = re.compile(r"^act-\d{8}-[a-z0-9-]+$")
SVC_ID_RE = re.compile(r"^svc-[a-z0-9-]+$")


def collect_ids():
    u"""返回 {id: [(page, 行号)]}。"""
    out = {}
    for page in existing_pages():
        text = clean_for_scan(read_text(os.path.join(ROOT, page)))
        for m in ID_ATTR_RE.finditer(text):
            out.setdefault(m.group(1), []).append((page, line_of(text, m.start())))
    return out


def s15_ids(rep, ctx):
    ids = collect_ids()
    for i, spots in sorted(ids.items()):
        if i.startswith("n-") and not NOTICE_ID_RE.match(i):
            rep.fail("S15", u"%s:%d" % spots[0], u"公告 id 不合规：%s" % i)
        if i.startswith("act-") and not ACT_ID_RE.match(i):
            rep.fail("S15", u"%s:%d" % spots[0], u"活动 id 不合规：%s" % i)
        if i.startswith("svc-") and not SVC_ID_RE.match(i):
            rep.fail("S15", u"%s:%d" % spots[0], u"服务锚点不合规：%s" % i)
        if len(spots) > 1:
            pages = [s[0] for s in spots]
            if i.startswith(("n-", "act-", "svc-")):
                # 内容 id 是分享锚点，全站只能有一次（§1.5 冻结接口）
                rep.fail("S15", u"全站", u"内容 id 重复：%s（%s）"
                         % (i, u"、".join(u"%s:%d" % s for s in spots)))
            elif len(set(pages)) != len(pages):
                rep.fail("S15", u"%s:%d" % spots[0], u"同一页内 id 重复：%s" % i)
            # 结构 id（main / site-nav / foot-year）逐页各有一份，是天经地义的

    # 活动 id 的 slug 必须与照片 slug 一致（E16），否则首页卡片会指向一张不存在的封面
    man = load_manifest() or {}
    photo_slugs = set()
    for rel in man:
        base = os.path.basename(rel)
        if base.startswith("cover-"):
            photo_slugs.add(base[len("cover-"):-len(".jpg")])
    for i in sorted(ids):
        if not i.startswith("act-"):
            continue
        parts = i.split("-", 2)
        if len(parts) < 3:
            continue
        slug = parts[2]
        if photo_slugs and slug not in photo_slugs:
            rep.fail("S15", u"%s:%d" % ids[i][0],
                     u"活动 id 的 slug「%s」在照片里找不到对应封面（E16）" % slug)


def print_ids():
    ids = collect_ids()
    print(u"全站 id 清单（归档用；冻结接口，发布后不可改，§1.5）")
    print(u"")
    for i, spots in sorted(ids.items()):
        kind = u"内容"
        if i.startswith("n-"):
            kind = u"公告"
        elif i.startswith("act-"):
            kind = u"活动"
        elif i.startswith("svc-"):
            kind = u"服务锚点"
        elif i in ("main", "site-nav", "foot-year"):
            kind = u"结构"
        print(u"%-34s %-6s %s" % (i, kind, u"、".join(u"%s:%d" % s for s in spots)))
    print(u"")
    print(u"共 %d 个" % len(ids))
    return 0


# --------------------------------------------------------------------------
# S16 —— 对比度静态验算（计划书 §9.2 R3）
# --------------------------------------------------------------------------
def _srgb(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_value):
    h = hex_value.strip().lstrip(u"#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return 0.2126 * _srgb(r) + 0.7152 * _srgb(g) + 0.0722 * _srgb(b)


def contrast_ratio(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# (说明, 前景变量, 背景变量, 要求)
CONTRAST_CHECKS = [
    (u"正文墨字于白面", "--ink", "--panel", 7.0),
    (u"次要灰字于白面", "--dim", "--panel", 4.5),
    (u"按钮白字于学服蓝", "--panel", "--accent", 4.5),
    (u"选中态蓝字于浅蓝面", "--accent", "--accent-soft", 4.5),
    (u"占位墨字于奶黄底", "--ink", "--cream", 4.5),
    (u"芯片墨字于冰蓝底", "--ink", "--ice", 4.5),
    (u"页脚白字于深蓝底", "--panel", "--accent-deep", 4.5),
    (u"次要灰字于页底", "--dim", "--bg", 4.5),
]


def parse_design_vars():
    css_path = os.path.join(ROOT, "assets", "css", "site.css")
    if not os.path.isfile(css_path):
        return {}
    css = read_text(css_path)
    m = re.search(r":root\s*\{(.*?)\n\}", css, re.S)
    if not m:
        return {}
    out = {}
    for name, value in re.findall(r"(--[a-z-]+)\s*:\s*([^;]+);", m.group(1)):
        v = value.strip()
        if re.match(r"^#[0-9A-Fa-f]{6}$", v):
            out[name] = v
    return out


def contrast_rows():
    design_vars = parse_design_vars()
    rows = []
    for label, fg, bg, need in CONTRAST_CHECKS:
        if fg not in design_vars or bg not in design_vars:
            rows.append((label, None, None, need, False))
            continue
        r = contrast_ratio(design_vars[fg], design_vars[bg])
        rows.append((label, design_vars[fg], design_vars[bg], need, r >= need, r))
    return rows


def print_contrast():
    print(u"对比度静态验算（WCAG 2.1；从 site.css 的设计变量直接算，不经浏览器）")
    print(u"")
    bad = 0
    for row in contrast_rows():
        if len(row) == 5:
            print(u"! %-22s 变量缺失" % row[0])
            bad += 1
            continue
        label, fg, bg, need, okr, r = row
        if not okr:
            bad += 1
        print(u"%s %-22s %s on %s  %5.2f:1（需 ≥%.1f）"
              % (u"✓" if okr else u"✗", label, fg, bg, r, need))
    print(u"")
    print(u"全部达标" if not bad else u"有 %d 项不达标" % bad)
    return 1 if bad else 0


def s16_contrast(rep, ctx):
    rows = contrast_rows()
    worst = None
    for row in rows:
        if len(row) == 5:
            rep.fail("S16", row[0], u"对比度验算所需变量缺失")
            continue
        label, fg, bg, need, okr, r = row
        if not okr:
            rep.fail("S16", label, u"%s on %s 仅 %.2f:1（需 ≥%.1f）" % (fg, bg, r, need))
        if worst is None or r < worst[1]:
            worst = (label, r)
    if worst:
        rep.info(u"对比度最低项：%s %.2f:1（--contrast 可看全表）" % worst)


# --------------------------------------------------------------------------
# S17 —— 首页与列表页同步、空状态与条目互斥（E17/E30；默认 WARN、--release FAIL）
# --------------------------------------------------------------------------
HOME_NOTICE_RE = re.compile(
    r'<li><a href="notices\.html#([^"]+)"><time datetime="([^"]+)">([^<]*)</time>(.*?)</a></li>',
    re.S)
NOTICE_ENTRY_RE = re.compile(
    r'<article class="notice" id="([^"]+)">\s*<p class="notice-meta"><time datetime="([^"]+)">'
    r'([^<]*)</time></p>\s*<h2>(.*?)</h2>', re.S)
ACT_ENTRY_RE = re.compile(r'<article class="activity" id="([^"]+)"', re.S)


def _strip_tags(s):
    return re.sub(r"<[^>]+>", u"", s).strip()


def s17_home_sync(rep, ctx):
    level = "FAIL" if ctx.get("release") else "WARN"

    def note(where, msg):
        if level == "FAIL":
            rep.fail("S17", where, msg)
        else:
            rep.warn("S17", where, msg)

    for page in ("notices.html", "activities.html"):
        if not exists_exact_case(page):
            continue
        t = clean_for_scan(read_text(os.path.join(ROOT, page)))
        if re.search(r"<article\b", t) and u'class="empty"' in t:
            rep.fail("S17", page, u"空状态与条目并存（两者互斥）")

    index = clean_for_scan(read_text(os.path.join(ROOT, "index.html")))
    if exists_exact_case("notices.html"):
        cards = HOME_NOTICE_RE.findall(index)
        entries = NOTICE_ENTRY_RE.findall(
            clean_for_scan(read_text(os.path.join(ROOT, "notices.html"))))
        want = entries[:min(3, len(entries))]
        if not entries and u'class="empty"' not in index:
            note("index.html", u"公告页无条目，首页「最新公告」应显示空状态")
        if len(cards) != len(want):
            note("index.html", u"首页公告卡 %d 张，公告页首 %d 条（N<3 取 min(3,N)）"
                 % (len(cards), len(want)))
        for card, entry in zip(cards, want):
            ci, cd, _ct, ctitle = card
            ei, ed, _et, etitle = entry
            if ci != ei or cd != ed or _strip_tags(ctitle) != _strip_tags(etitle):
                note("index.html",
                     u"首页公告卡与公告页不一致：卡(%s / %s / %s) vs 页(%s / %s / %s)"
                     % (ci, cd, _strip_tags(ctitle), ei, ed, _strip_tags(etitle)))

    if exists_exact_case("activities.html"):
        act_ids = ACT_ENTRY_RE.findall(
            clean_for_scan(read_text(os.path.join(ROOT, "activities.html"))))
        index_act_ids = re.findall(r'activities\.html#([^"]+)"', index)
        if set(index_act_ids) != set(act_ids[:min(3, len(act_ids))]):
            note("index.html", u"首页活动卡与活动页首 min(3,N) 条不一致：首页 %s / 活动页 %s"
                 % (sorted(index_act_ids), sorted(act_ids[:min(3, len(act_ids))])))


# --------------------------------------------------------------------------
# S18 —— 表格（E18）
# --------------------------------------------------------------------------
TABLE_RE = re.compile(r"<table\b.*?</table>", re.S)


def s18_tables(rep, ctx):
    for page in [p for p in MAIN_PAGES if exists_exact_case(p)]:
        text = clean_for_scan(read_text(os.path.join(ROOT, page)))
        for m in TABLE_RE.finditer(text):
            where = u"%s:%d" % (page, line_of(text, m.start()))
            before = text[:m.start()]
            idx = before.rfind(u'class="table-scroll"')
            if idx < 0:
                rep.fail("S18", where, u"<table> 不在 .table-scroll 容器内")
                continue
            div_start = before.rfind(u"<div", 0, idx + 1)
            tag_end = before.find(u">", div_start)
            container = before[div_start:tag_end + 1]     # 整个开标签，不靠固定窗口
            for attr, label in ((u'tabindex="0"', u'tabindex="0"'),
                                (u'role="region"', u'role="region"'),
                                (u'aria-label=', u"aria-label")):
                if attr not in container:
                    rep.fail("S18", where, u"滚动容器缺 %s（Firefox 下无法键盘滚动）" % label)
            between = before[idx:]
            if u'class="hint"' not in between:
                rep.fail("S18", where, u"滚动容器缺滑动提示行（.hint）")
            body = m.group(0)
            if u"<caption" not in body:
                rep.fail("S18", where, u"<table> 缺 <caption>")
            if u'scope="col"' not in body:
                rep.fail("S18", where, u"<th> 缺 scope=\"col\"")


# --------------------------------------------------------------------------
# S19 —— class 封闭清单（附录 B；未登记 = WARN）
# --------------------------------------------------------------------------
CLASS_ATTR_RE = re.compile(r'class="([^"]*)"')


def registry_classes():
    css_path = os.path.join(ROOT, "assets", "css", "site.css")
    if not os.path.isfile(css_path):
        return None
    css = read_text(css_path)
    m = re.search(r"class 登记表（BEGIN）(.*?)class 登记表（END）", css, re.S)
    if not m:
        return None
    return set(w for w in m.group(1).split() if re.match(r"^[a-z][a-z0-9-]*$", w))


def s19_classes(rep, ctx):
    reg = registry_classes()
    if reg is None:
        rep.warn("S19", "assets/css/site.css", u"找不到 class 登记表（BEGIN/END 标记），跳过")
        return
    used = {}
    # 404 的样式类是刻意自包含的（不进 site.css），附录 B 已声明排除
    for page in [p for p in MAIN_PAGES if exists_exact_case(p)]:
        text = clean_for_scan(read_text(os.path.join(ROOT, page)))
        for m in CLASS_ATTR_RE.finditer(text):
            for cls in m.group(1).split():
                used.setdefault(cls, set()).add(page)
    for cls in sorted(set(used) - reg):
        rep.warn("S19", u"、".join(sorted(used[cls])),
                 u"class 未登记：%s" % cls)


# --------------------------------------------------------------------------
# S21 —— noindex 规则（E26，双向断言）
# --------------------------------------------------------------------------
def s21_noindex(rep, ctx):
    for page in [p for p in MAIN_PAGES if exists_exact_case(p)]:
        text = strip_comments(read_text(os.path.join(ROOT, page)))
        has = u'content="noindex"' in text
        if ctx.get("release"):
            if has:
                rep.fail("S21", page, u"上线版不得含 noindex（E26：M5 上线时移除）")
        elif not has:
            rep.fail("S21", page, u"施工期应含 noindex（防占位内容被搜索引擎收录）")
    if exists_exact_case("404.html"):
        if u'content="noindex"' not in read_text(os.path.join(ROOT, "404.html")):
            rep.fail("S21", "404.html", u"404 必须**恒**含 noindex")


# --------------------------------------------------------------------------
# S22 —— 404 专项（E5）
# --------------------------------------------------------------------------
def s22_404(rep, ctx):
    if not exists_exact_case("404.html"):
        return
    text = strip_comments(read_text(os.path.join(ROOT, "404.html")))
    for m in ATTR_RE.finditer(text):
        v = m.group(1).strip()
        if v.startswith("data:") or v.startswith(u"/") or v.startswith(u"#"):
            continue
        rep.fail("S22", u"404.html:%d" % line_of(text, m.start()),
                 u"除 data: 与根绝对路径外不得有引用：%s" % v)
    links = set(re.findall(r'href="/([a-z0-9-]+\.html)"', text))
    want = set(MAIN_PAGES)
    if links != want:
        rep.fail("S22", "404.html",
                 u"链接集合与页面文件名集合不符：缺 %s，多 %s"
                 % (sorted(want - links) or u"无", sorted(links - want) or u"无"))
    for m in re.finditer(r'href="([^"]*)"', text):
        v = m.group(1)
        if not v.startswith(u"/") and not v.startswith(u"#"):
            rep.fail("S22", u"404.html:%d" % line_of(text, m.start()),
                     u"内链应写根绝对路径（Pages 下相对路径必挂）：%s" % v)


# --------------------------------------------------------------------------
# S23 —— 隐私词（E36）
# --------------------------------------------------------------------------
PRIVACY_HARD = [u"学号", u"身份证", u"宿舍", u"手机号", u"QQ号", u"微信号"]
PRIVACY_SOFT = [u"专业", u"班级", u"年级"]


def s23_privacy(rep, ctx):
    for page in existing_pages():
        text = read_text(os.path.join(ROOT, page))      # 注释也算：源码也是公开的
        for w in PRIVACY_HARD:
            for m in re.finditer(re.escape(w), text):
                around = text[max(0, m.start() - 3):m.end() + 3]
                if w == u"微信号" and u"公众号" in around:
                    continue                            # E36 豁免"微信公众号"
                rep.fail("S23", u"%s:%d" % (page, line_of(text, m.start())),
                         u"隐私硬词命中：%s（上下文「%s」）" % (w, around.replace(u"\n", u" ")))
        for w in PRIVACY_SOFT:
            for m in re.finditer(re.escape(w), text):
                rep.warn("S23", u"%s:%d" % (page, line_of(text, m.start())),
                         u"隐私软词命中：%s（确认无害再放行）" % w)


# --------------------------------------------------------------------------
# S24 —— 体积预算（P1/P2）
# --------------------------------------------------------------------------
FIRST_PAINT = ["index.html", "assets/css/site.css", "assets/js/site.js",
               "assets/img/logo-emblem-120.png", "assets/img/mascot-girl.png"]
FIRST_PAINT_CAP = 500 * 1024
PAGE_IMG_CAP = 4 * 1024 * 1024


def s24_budget(rep, ctx):
    total = 0
    missing = []
    for rel in FIRST_PAINT:
        p = os.path.join(ROOT, rel.replace("/", os.sep))
        if os.path.isfile(p):
            total += os.path.getsize(p)
        else:
            missing.append(rel)
    if missing:
        rep.fail("S24", u"首页首屏", u"文件缺失：%s" % u"、".join(missing))
    if total > FIRST_PAINT_CAP:
        rep.fail("S24", u"首页首屏", u"%d B 超 500 KB（P1）" % total)
    else:
        rep.info(u"首页首屏 %d B / 上限 %d B" % (total, FIRST_PAINT_CAP))

    man = load_manifest() or {}
    for page in [p for p in MAIN_PAGES if exists_exact_case(p)]:
        text = clean_for_scan(read_text(os.path.join(ROOT, page)))
        seen = set()
        tot = 0
        for m in IMG_RE.finditer(text):
            src = parse_attrs(m.group(0)).get("src", u"")
            if not src or src.startswith("data:") or src in seen:
                continue
            seen.add(src)
            if src in man:
                tot += man[src][2]
        if tot > PAGE_IMG_CAP:
            rep.fail("S24", page, u"图片总量 %d B 超 4 MB（P2）" % tot)

    og = man.get(u"assets/img/og-cover.png")
    if og and og[2] > 200 * 1024:
        rep.fail("S24", u"og-cover.png", u"%d B 超 200 KB（微信可能不显示卡片图）" % og[2])


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
RULES = [
    ("S1", s1_pages),
    ("S2", s2_no_extra_html),
    ("S3", s3_no_external),
    ("S4", s4_refs_exist),
    ("S5", s5_placeholders),
    ("S6", s6_sync_blocks),
    ("S7", s7_encoding),
    ("S8", s8_meta),
    ("S9", s9_headings),
    ("S10", s10_cache_version),
    ("S11", s11_img_attrs),
    ("S12", s12_img_manifest),
    ("S13", s13_js),
    ("S14", s14_banned_features),
    ("S15", s15_ids),
    ("S16", s16_contrast),
    ("S17", s17_home_sync),
    ("S18", s18_tables),
    ("S19", s19_classes),
    ("S20", s20_scan_credentials),
    ("S21", s21_noindex),
    ("S22", s22_404),
    ("S23", s23_privacy),
    ("S24", s24_budget),
]


def dump(rep):
    # 逐条明细按规则限流：施工期"图片还没生成"会一次刷出几十条同因 FAIL，
    # 全打出来反而淹没了真正的异类。汇总行的计数始终是完整的。
    problems = [r for r in rep.rows if r[1] in ("FAIL", "WARN")]
    infos = [r for r in rep.rows if r[1] == "INFO"]

    per_rule_shown = {}
    for rule, level, where, message in sorted(problems):
        shown = per_rule_shown.get(rule, 0)
        per_rule_shown[rule] = shown + 1
        if shown >= MAX_DETAIL_PER_RULE:
            continue
        mark = u"✗" if level == "FAIL" else u"!"
        print(u"%s [%s] %-8s %s: %s" % (mark, level, rule, where, message))
    for rule, shown in sorted(per_rule_shown.items()):
        if shown > MAX_DETAIL_PER_RULE:
            print(u"  … %s 另有 %d 条同类明细未展开" % (rule, shown - MAX_DETAIL_PER_RULE))
    print(u"")
    for _rule, _level, _where, message in infos:
        print(u"· %s" % message)
    if infos:
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
    global RELEASE
    soften_stdout()
    release = False
    modes = []
    for arg in argv:
        if arg == "--release":
            release = True
        elif arg in ("--contrast", "--ids"):
            modes.append(arg)
        elif arg in ("-h", "--help"):
            usage()
            return 0
        else:
            print(u"未知参数：%s\n" % arg)
            usage()
            return 2

    RELEASE = release
    if "--contrast" in modes:
        return print_contrast()
    if "--ids" in modes:
        return print_ids()

    rep = Report()
    ctx = {"release": release}
    for _rule, fn in RULES:
        fn(rep, ctx)
    dump(rep)
    if release:
        print(u"（--release 模式：施工期豁免项已按 FAIL 判——占位清零、摘掉 noindex 后才可能全绿）")
    return 1 if rep.total("FAIL") else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
