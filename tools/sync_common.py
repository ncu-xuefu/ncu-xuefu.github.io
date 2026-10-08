# -*- coding: utf-8 -*-
u"""sync_common.py —— 7 页公共块一致性（检查 / 修复 / 缓存串）。

为什么要它
----------
这个站有 7 个手写的 HTML 文件，页头导航、`<head>` 公共段、页脚在三者之间逐字节相同。
"改 7 处必出事故"（漏一处没人看得见）。本工具把重复内容变成**单源同步**：

    改 index.html（唯一真源）→ 跑 --fix → 其余页被覆盖成一致

它同时解决另外两个必然会来的麻烦：7 处 `?v=` 缓存串、换域名时要改 7 处 `og:image`。

**它是修复工具，不是构建步骤。** 忘了跑，网站照常运行——只是各页可能不一致。
不引入任何"隐性状态"，符合本项目的"零构建"底线（§0.2-2）。

块表（§1.4；源文件是该块唯一真源）
--------------------------------
    COMMON:HEAD           index.html  → 其余 6 页
    COMMON:NAV            index.html  → 其余 6 页   （除恰好一处 aria-current 外逐字节一致，E19）
    COMMON:FOOT           index.html  → 其余 6 页
    SYNC:SERVICES-CARDS   index.html  → services.html、about.html
    SYNC:OFFICE-HOURS     services.html → index.html、contact.html

用法
----
    python tools/sync_common.py --check           # 只读比较（默认即 --check）
    python tools/sync_common.py --fix             # 用源文件覆盖目标；NAV 按页面文件名重挂 aria-current
    python tools/sync_common.py --bump 20261015   # 先改 ?v=（css/js 同值）再 --fix

404.html **不在块表内**（E5：它必须自包含，不吃同步）。
退出码：0 = 一致 / 已修复；1 = 有不一致；2 = 用法错误。
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = ["index.html", "about.html", "services.html", "notices.html",
         "team.html", "activities.html", "contact.html"]

INNER = [p for p in PAGES if p != "index.html"]

# (块名, 源文件, 目标文件, NAV 是否按页重挂 aria-current)
BLOCK_TABLE = [
    ("COMMON:HEAD", "index.html", INNER, False),
    ("COMMON:NAV", "index.html", INNER, True),
    ("COMMON:FOOT", "index.html", INNER, False),
    ("SYNC:SERVICES-CARDS", "index.html", ["services.html", "about.html"], False),
    ("SYNC:OFFICE-HOURS", "services.html", ["index.html", "contact.html"], False),
]

ARIA = u' aria-current="page"'
VERSION_RE = re.compile(r"\?v=(\d{8})")


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


def read_text(path):
    with io.open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def write_text(path, text):
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def block_span(text, name):
    u"""返回 (start, end, body)：BEGIN 标记开头 → END 标记末尾，body 是两标记之间的内容。"""
    pattern = (r"<!-- " + re.escape(name) + r" BEGIN -->\n(.*?)\n<!-- "
               + re.escape(name) + r" END -->")
    m = re.search(pattern, text, re.S)
    if not m:
        return None
    return (m.start(), m.end(), m.group(1))


def normalize_nav(body):
    u"""比较前抹掉 aria-current —— 它必须逐页不同，否则真源没法共用（E19）。"""
    return body.replace(ARIA, u"")


def attach_aria(body, page):
    u"""把 aria-current 挂到本页对应的导航条目上（先抹干净再加，幂等）。"""
    body = body.replace(ARIA, u"")
    old = u'<a href="%s">' % page
    if old not in body:
        raise ValueError(u"导航里没有指向 %s 的链接" % page)
    return body.replace(old, u'<a href="%s"%s>' % (page, ARIA), 1)


def block_body_for(text, name, page):
    span = block_span(text, name)
    if span is None:
        return None
    return span[2]


def first_diff(target_body, source_body):
    u"""返回首个差异的 (行号, 目标行, 源行)；完全相同则 None。行号从 1 起。"""
    lt = target_body.split(u"\n")
    ls = source_body.split(u"\n")
    for i in range(max(len(lt), len(ls))):
        t = lt[i] if i < len(lt) else None
        s = ls[i] if i < len(ls) else None
        if t != s:
            return (i + 1, t, s)
    return None


def snippet(value, limit=60):
    if value is None:
        return u"（无此行）"
    return value if len(value) <= limit else value[:limit] + u"…"


# --------------------------------------------------------------------------
# --check
# --------------------------------------------------------------------------
def cmd_check():
    problems = 0
    checked = 0
    pending = 0

    for name, source, targets, is_nav in BLOCK_TABLE:
        spath = os.path.join(ROOT, source)
        if not os.path.isfile(spath):
            print(u"✗ %s：源文件 %s 不存在" % (name, source))
            problems += 1
            continue
        sbody = block_body_for(read_text(spath), name, source)
        if sbody is None:
            # 「源里还没有这个块」≠「目标与源不一致」。
            # 施工期的不完整按 WARN 处理（E3 原则：施工期允许的不完整 = WARN；
            # 上线后必须成立的 = FAIL）。源一旦建起该块，本项立刻转为强制。
            print(u"! %s：源 %s 尚未建立该块（施工期 WARN；建块后转为强制）"
                  % (name, source))
            pending += 1
            continue
        expect = normalize_nav(sbody) if is_nav else sbody

        for target in targets:
            tpath = os.path.join(ROOT, target)
            if not os.path.isfile(tpath):
                print(u"✗ %s / %s：目标文件不存在" % (target, name))
                problems += 1
                continue
            ttext = read_text(tpath)
            span = block_span(ttext, name)
            if span is None:
                print(u"✗ %s：文件里找不到块 %s" % (target, name))
                problems += 1
                continue
            tbody = span[2]
            cmp_body = normalize_nav(tbody) if is_nav else tbody
            checked += 1

            if cmp_body != expect:
                diff = first_diff(cmp_body, expect)
                line_no = ttext.count(u"\n", 0, span[0]) + 1 + (diff[0] if diff else 0)
                print(u"✗ %s / %s 与源不一致（首个差异行 %d：目标「%s」/ 源「%s」）"
                      % (target, name, line_no, snippet(diff[1]), snippet(diff[2])))
                problems += 1
                continue

            if is_nav:
                hits = tbody.count(u'aria-current="page"')
                want = u'<a href="%s"%s>' % (target, ARIA)
                if hits != 1 or want not in tbody:
                    print(u"✗ %s / %s：aria-current 应恰好一处且落在本页条目上（当前 %d 处）"
                          % (target, name, hits))
                    problems += 1
                    continue

            print(u"✓ %s / %s" % (target, name))

    print(u"")
    if problems:
        print(u"FAIL %d（已比较 %d 个块）；修复：python tools/sync_common.py --fix"
              % (problems, checked))
        return 1
    if pending:
        print(u"OK 全部一致（已比较 %d 个块；另有 %d 个块尚未建立，见上）"
              % (checked, pending))
        return 0
    print(u"OK 全部一致（已比较 %d 个块）" % checked)
    return 0


# --------------------------------------------------------------------------
# --fix
# --------------------------------------------------------------------------
def cmd_fix():
    # ① 先把所有源块的 body 快照下来。
    #    必须快照：SYNC:OFFICE-HOURS 的源是 services.html，而它又是 COMMON 块的目标——
    #    边读边写会让后读的块拿到被改过一半的文件。
    snapshot = {}
    for name, source, _targets, is_nav in BLOCK_TABLE:
        spath = os.path.join(ROOT, source)
        if not os.path.isfile(spath):
            print(u"✗ %s：源文件 %s 不存在" % (name, source))
            return 1
        body = block_body_for(read_text(spath), name, source)
        if body is None:
            print(u"! %s：源 %s 尚未建立该块，跳过（施工期 WARN；建块后转为强制）"
                  % (name, source))
            continue
        snapshot[name] = body

    # ② 按文件归集要写的块，逐文件重写（保留块外内容原样）。
    pending = {}
    for name, _source, targets, is_nav in BLOCK_TABLE:
        if name not in snapshot:
            continue          # 源里尚未建立该块，跳过（与 --check 的 WARN 同一口径）
        body = snapshot[name]
        for target in targets:
            want = attach_aria(body, target) if is_nav else body
            pending.setdefault(target, []).append((name, want))

    changed_files = 0
    changed_blocks = 0
    for target in PAGES:
        wanted = pending.get(target)
        if not wanted:
            continue
        path = os.path.join(ROOT, target)
        text = read_text(path)
        original = text
        for name, want in wanted:
            span = block_span(text, name)
            if span is None:
                print(u"✗ %s：文件里找不到块 %s，跳过" % (target, name))
                continue
            current = span[2]
            replacement = (u"<!-- " + name + u" BEGIN -->\n" + want
                           + u"\n<!-- " + name + u" END -->")
            if text[span[0]:span[1]] == replacement:
                continue
            text = text[:span[0]] + replacement + text[span[1]:]
            changed_blocks += 1
            print(u"✓ %s / %s 已同步" % (target, name))
        if text != original:
            write_text(path, text)
            changed_files += 1

    print(u"")
    if changed_blocks:
        print(u"OK 已改写 %d 个块 / %d 个文件" % (changed_blocks, changed_files))
    else:
        print(u"OK 无需改动（全部已一致）")
    return 0


# --------------------------------------------------------------------------
# --bump
# --------------------------------------------------------------------------
def cmd_bump(version):
    if not re.match(r"^\d{8}$", version or u""):
        print(u"✗ 缓存串必须是 8 位日期，例如 20261015（收到 %r）" % version)
        return 2

    touched = 0
    for page in PAGES:
        path = os.path.join(ROOT, page)
        if not os.path.isfile(path):
            continue
        text = read_text(path)
        new_text, n = VERSION_RE.subn(lambda m: u"?v=" + version, text)
        if n:
            write_text(path, new_text)
            touched += n
            print(u"✓ %s：%d 处 ?v= → %s" % (page, n, version))

    # css 与 js 必须同值：改完立刻复核（E9）
    values = set()
    for page in PAGES:
        path = os.path.join(ROOT, page)
        if os.path.isfile(path):
            values.update(VERSION_RE.findall(read_text(path)))
    if len(values) != 1:
        print(u"✗ 全站 ?v= 不唯一：%s" % sorted(values))
        return 1

    print(u"")
    print(u"OK 已改 %d 处，全站 ?v=%s；接着执行 --fix" % (touched, version))
    return cmd_fix()


def usage():
    print(__doc__.strip())


def main(argv):
    soften_stdout()
    if not argv:
        return cmd_check()
    head = argv[0]
    if head == "--check":
        return cmd_check()
    if head == "--fix":
        return cmd_fix()
    if head == "--bump":
        if len(argv) < 2:
            print(u"✗ --bump 需要日期参数，例如 --bump 20261015")
            return 2
        return cmd_bump(argv[1])
    if head in ("-h", "--help"):
        usage()
        return 0
    print(u"未知参数：%s\n" % head)
    usage()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
