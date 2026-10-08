# -*- coding: utf-8 -*-
u"""make_images.py —— 门户图片全套生成 + 照片管线。

为什么要它
----------
页面上的每一张图都必须满足四条硬规则：没有 EXIF 定位、体积在预算内、
宽高与 HTML 属性一致、换图必须换文件名（微信按 URL 缓存）。靠手工导出，
这四条迟早有一条会破——而且破了没人看得见。于是把整条链路写成可复现的脚本。

它是**生成器**，不是构建步骤：跑一次产出文件，此后网站不再依赖它（§0.2-2）。
可反复重跑（幂等）：写完再跑一次，`git status --porcelain` 必须为空。

一个实测坑（Pillow 的行为）
--------------------------
JPEG/PNG 保存后，Pillow **恒定带一个 20 字节的空 EXIF 段**。所以"没有 EXIF"的断言
不能写成"段不存在"，只能写成 **`len(Image.open(out).getexif()) == 0`**（标签数为 0）。
写成前者的话，断言永远失败（§0.4-8 / E33）。

用法
----
    python tools/make_images.py                    # 生成全套（幂等）
    python tools/make_images.py --check            # 只校验，不改盘
    python tools/make_images.py --photos DIR --slug fun-games-2026 [--cover 文件] [--crop center|top|bottom] [--thumbs] [--auto-quality]
    python tools/make_images.py --contact-sheet DIR --out FILE

退出码：0 = 全绿 / 已生成；1 = 任一断言失败；2 = 用法错误。
"""
from io import BytesIO
import base64
import io
import os
import re
import sys

try:
    from PIL import Image, ImageChops, ImageFilter, ImageFont, ImageDraw, ImageOps
except ImportError:
    sys.stderr.write(u"✗ 需要 Pillow：python -m pip install pillow\n")
    raise

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAND_SRC = os.path.join(ROOT, "brand-src")
IMG = os.path.join(ROOT, "assets", "img")

# 品牌蓝：会徽外环同色。用于"外扩"清洗与主屏族铺底（计划书 §6.1/§6.2）
BRAND_BLUE = (46, 94, 163)
BRAND_BLUE_HEX = u"#2E5EA3"

MASTER = os.path.join(BRAND_SRC, "logo-emblem-1308.png")

# 单图体积预算（§1.2）：任何图 ≤300 KB；这里给出各族的更紧上限
CAP_PNG = 300 * 1024

PNG_SUFFIX = ".png"


def soften_stdout():
    u"""Windows 控制台默认 GBK，直接打印 ✓/✗ 会 UnicodeEncodeError（§1.1 房内风格）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


# --------------------------------------------------------------------------
# 会徽：清洗与缩放
# --------------------------------------------------------------------------
def clean_transparent(im):
    u"""把全透明像素的 RGB 统一为品牌蓝，像素本身与 alpha 一律不动。

    "外扩"而非"填白"：填白在深色底（页脚）上拍平同样出问题；外扩品牌蓝则在任何
    底色上都是徽章的自然外沿。Pillow 缩放本身已正确处理 alpha，这一步是防御
    **第三方工具**（在线 favicon 生成器 / canvas / 导出 JPEG / ImageMagick）把
    透明区拍平成黑边（计划书摘要修正 3 / 决策 D8）。
    """
    alpha = im.getchannel("A")
    bleed = Image.new("RGBA", im.size, BRAND_BLUE + (255,))
    out = Image.composite(im, bleed, alpha.point(lambda v: 255 if v else 0))
    out.putalpha(alpha)
    return out


def load_master():
    im = Image.open(MASTER).convert("RGBA")
    return clean_transparent(im)


def step_resize(im, target):
    u"""逐级减半到 ≤2×目标，再落到目标值。

    为什么不能一步 resize：1308→16 一步下去，火焰中心的细节会被采样丢光，
    16px 只剩一个模糊的蓝点。逐级 LANCZOS 每次只降一半，保留的结构多得多。
    """
    w, h = im.size
    while max(w, h) > target * 2:
        w, h = max(1, int(round(w / 2.0))), max(1, int(round(h / 2.0)))
        im = im.resize((w, h), Image.LANCZOS)
    return im.resize((target, target), Image.LANCZOS) if im.size != (target, target) else im


def sharpen(im, percent):
    u"""小尺寸补一点锐度——LANCZOS 缩到 16/32px 后边缘会发糊。"""
    return im.filter(ImageFilter.UnsharpMask(radius=0.8, percent=percent, threshold=2))


def flatten_on_blue(im):
    u"""铺品牌蓝底并保持 RGBA（alpha 全 255）。

    保留 RGBA 而不是转 RGB：断言写的是"alpha 全 255"，需要通道还在。
    环与底同色 ⇒ 系统怎么裁圆角都不露馅（计划书 §6.2）。
    """
    bg = Image.new("RGBA", im.size, BRAND_BLUE + (255,))
    return Image.alpha_composite(bg, im)


# --------------------------------------------------------------------------
# 规格表：这里是"要产出什么"的唯一真源，--check 与生成共用
# --------------------------------------------------------------------------
# (输出名, 尺寸, 类型, 锐化百分比)
EMBLEM_SPECS = [
    (u"logo-emblem-256.png", 256, "clean", 0),
    (u"logo-emblem-120.png", 120, "clean", 0),
    (u"logo-emblem-64.png", 64, "clean", 0),
    (u"favicon-32.png", 32, "clean", 80),
    (u"favicon-16.png", 16, "clean", 100),
]
ICO_NAME = u"favicon.ico"
ICO_FRAMES = (16, 32, 48)

# 主屏族：铺品牌蓝底、满幅（计划书 §6.2）。环与底同色 ⇒ 系统裁圆角不露馅。
ICON_SPECS = [
    (u"apple-touch-icon.png", 180),
    (u"icon-192.png", 192),
    (u"icon-512.png", 512),
]

# 吉祥物（§5.4）：**原像素不动**，只做 256 色量化压体积。源图实测透明区无深色残留，
# 无需清洗。全管线通行"只缩不放"，所以这里绝不 resize。
MASCOT_SPECS = [
    (u"mascot-girl.png", u"mascot-girl-222x282.png"),
    (u"mascot-boy.png", u"mascot-boy-121x321.png"),
]
MASCOT_CAP = 25 * 1024

# OG 分享卡（§5.3）。文案不依赖 A1——M2 就要产出；日后要换文案就**换文件名**
# （og-cover-2.png）并 sync_common --fix，以绕开微信按 URL 的分享卡缓存（E8）。
OG_NAME = u"og-cover.png"
OG_W, OG_H = 1200, 630
OG_BG = (234, 239, 247)          # #EAEFF7
OG_BAR_H = 12                    # 底部火焰横条：分享卡实际约 455px 宽渲染 ≈0.38 倍，12→4.6px
OG_EMBLEM = 320
OG_EMBLEM_X = 80
OG_TEXT_X = 460
OG_CAP = 200 * 1024
FLAME_STOPS = [(217, 36, 25), (220, 140, 15), (227, 194, 56)]   # #D92419 → #DC8C0F → #E3C238
OG_LINE1 = u"南昌大学教务处学生学习服务中心"
OG_LINE2 = u"服务全校师生 · 成立于 2006.10.10"

_FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")


def load_font(filename, size):
    u"""加载系统字体；拿不到或渲染不出中文就返回 None（上层据此报错）。"""
    path = os.path.join(_FONT_DIR, filename)
    if not os.path.isfile(path):
        return None
    try:
        font = ImageFont.truetype(path, size, index=0)
    except Exception:
        return None
    try:
        if font.getbbox(u"南昌大学")[2] <= 0:
            return None
    except Exception:
        return None
    return font


def build_emblem(name, size, kind, percent):
    master = load_master()
    im = step_resize(master, size)
    if percent:
        im = sharpen(im, percent)
    # 必须在缩放**之后**再清洗一次：Pillow 的 resize 对 RGBA 走预乘 alpha 的路径，
    # 会把全透明像素的 RGB 归零（实测 256px 输出 12,784 个透明像素全是 (0,0,0)）。
    # 源图清洗只保护"输入"，这里才是保护"输出"（断言 1 断的正是输出）。
    return clean_transparent(im)



def render_emblem_png(name, size, kind, percent):
    u"""在内存里渲染出 PNG 字节（--check 靠它做逐字节比对）。"""
    im = build_emblem(name, size, kind, percent)
    buf = BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def render_ico():
    u"""ICO 三帧（16/32/48），自 48px 那一版按 sizes 派生。"""
    master = load_master()
    big = sharpen(step_resize(master, max(ICO_FRAMES)), 80)
    buf = BytesIO()
    big.save(buf, "ICO", sizes=[(s, s) for s in ICO_FRAMES])
    return buf.getvalue()


def render_mascot(src_name):
    u"""吉祥物：256 色量化，原像素尺寸不变。返回 (png 字节, 源尺寸)。"""
    src = os.path.join(BRAND_SRC, src_name)
    im = Image.open(src).convert("RGBA")
    # FASTOCTREE：对照片/水彩类图像比默认的 MEDIANCUT 更快也更稳。
    # 量化会把 RGBA 变成 P 模式 + 内嵌调色板 alpha，存 PNG 时自动写 tRNS，
    # 四角 alpha 仍为 0（已由断言守住）。
    q = im.quantize(colors=256, method=Image.FASTOCTREE)
    buf = BytesIO()
    q.save(buf, "PNG", optimize=True)
    return buf.getvalue(), im.size


# 404 页的两张 data-URI（E6）：404 必须**自包含**——Pages 的 404 机制是"内容替换、
# URL 不变"，任何相对路径在 /a/b/c 下都会挂，所以会徽与吉祥物只能内联。
# 块由本工具生成/刷新，人工不要改（§3.11 / §5.4）。
ART_BEGIN_LINE = u"<!-- 404:ART BEGIN · 由 tools/make_images.py 生成（E6），勿手改 -->"
ART_END_LINE = u"<!-- 404:ART END -->"
ART_404_EMBLEM = 192
PAGE_404 = os.path.join(ROOT, "404.html")
PAGE_404_CAP = 90 * 1024
ART_RE = re.compile(r"[ \t]*<!-- 404:ART BEGIN[^\n]*-->\n.*?\n[ \t]*<!-- 404:ART END -->", re.S)


def render_404_art(indent):
    u"""渲染 404 的 ART 块（含标记行），按给定缩进。"""
    emb = step_resize(load_master(), ART_404_EMBLEM)
    emb = emb.quantize(colors=256, method=Image.FASTOCTREE)
    buf = BytesIO()
    emb.save(buf, "PNG", optimize=True)
    em_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    girl_bytes, _ = render_mascot(u"mascot-girl-222x282.png")
    girl_b64 = base64.b64encode(girl_bytes).decode("ascii")
    return (indent + ART_BEGIN_LINE + u"\n"
            + indent + u'<img class="emblem" src="data:image/png;base64,' + em_b64
            + u'" width="96" height="96" alt="">\n'
            + indent + u'<img class="girl" src="data:image/png;base64,' + girl_b64
            + u'" width="222" height="282" alt="学服吉祥物">\n'
            + indent + ART_END_LINE)


def refresh_404():
    u"""有 404.html 就刷新其 ART 块；返回 True 表示改动了。"""
    if not os.path.isfile(PAGE_404):
        return False
    text = io.open(PAGE_404, "r", encoding="utf-8", newline="").read()
    m = ART_RE.search(text)
    if m is None:
        return False
    indent = re.match(r"[ \t]*", m.group(0)).group(0)
    new_block = render_404_art(indent)
    if m.group(0) == new_block:
        return False
    with io.open(PAGE_404, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text[:m.start()] + new_block + text[m.end():])
    return True


def render_icon_png(size):
    u"""主屏图标：逐级缩放后铺品牌蓝底（alpha 全 255），保留 RGBA 以便断言通道。"""
    im = flatten_on_blue(step_resize(load_master(), size))
    buf = BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def flame_gradient(w, h):
    u"""横向三色火焰渐变（CSS linear-gradient(90deg,#D92419,#DC8C0F,#E3C238) 的等价实现）。"""
    line = Image.new("RGB", (w, 1))
    px = line.load()
    for x in range(w):
        t = (x / float(w - 1)) * (len(FLAME_STOPS) - 1)
        i = min(int(t), len(FLAME_STOPS) - 2)
        f = t - i
        a, b = FLAME_STOPS[i], FLAME_STOPS[i + 1]
        px[x, 0] = tuple(int(round(a[k] + (b[k] - a[k]) * f)) for k in range(3))
    return line.resize((w, h), Image.NEAREST)


def render_og():
    u"""OG 封面；返回 (png 字节, 误差信息 dict)。"""
    canvas = Image.new("RGB", (OG_W, OG_H), OG_BG)

    emblem = step_resize(load_master(), OG_EMBLEM)
    canvas.paste(emblem, (OG_EMBLEM_X, (OG_H - OG_EMBLEM) // 2), emblem)
    canvas.paste(flame_gradient(OG_W, OG_BAR_H), (0, OG_H - OG_BAR_H))

    f_bold = load_font("msyhbd.ttc", 44)
    f_reg = load_font("msyh.ttc", 28)
    if f_bold is None or f_reg is None:
        raise RuntimeError(u"系统 CJK 字体不可用：%s（需要 msyhbd.ttc / msyh.ttc）" % _FONT_DIR)

    draw = ImageDraw.Draw(canvas)
    b1 = draw.textbbox((0, 0), OG_LINE1, font=f_bold)
    b2 = draw.textbbox((0, 0), OG_LINE2, font=f_reg)
    h1, h2, gap = b1[3] - b1[1], b2[3] - b2[1], 16
    top = (OG_H - (h1 + gap + h2)) // 2
    draw.text((OG_TEXT_X, top - b1[1]), OG_LINE1, font=f_bold, fill=(31, 35, 41))
    draw.text((OG_TEXT_X, top + h1 + gap - b2[1]), OG_LINE2, font=f_reg, fill=(102, 112, 133))

    # 防"静默渲染空白"：数一遍文字区里非底色的像素。
    # 用 ImageChops.difference + histogram 而不是逐像素 getdata()——后者在 Pillow 12
    # 已弃用（会打 DeprecationWarning），而且纯 Python 循环慢得多。
    box = (OG_TEXT_X - 20, top - 20, OG_W - 20, top + h1 + gap + h2 + 20)
    region = canvas.crop(box)
    diff = ImageChops.difference(region, Image.new("RGB", region.size, OG_BG)).convert("L")
    ink = sum(diff.histogram()[1:])          # 亮度 >0 的像素数

    buf = BytesIO()
    canvas.save(buf, "PNG", optimize=True)
    if buf.tell() > OG_CAP:
        # 超限先量化到 256 色再试（§5.3）
        q = canvas.convert("P", palette=Image.ADAPTIVE, colors=256)
        buf = BytesIO()
        q.save(buf, "PNG", optimize=True)
    return buf.getvalue(), {"ink": ink, "top": top, "h1": h1, "h2": h2}


# --------------------------------------------------------------------------
# 照片管线（§5.5）
# --------------------------------------------------------------------------
MANIFEST = os.path.join(IMG, "image-manifest.tsv")
MANIFEST_EXT = (".png", ".jpg", ".jpeg", ".ico")

PHOTO_SUPPORTED = (".jpg", ".jpeg", ".png")
# 不支持的一律进 SKIP 列表打印出来——**不静默跳过**（静默跳过会让人以为处理过了）
PHOTO_SKIP_KNOWN = (".psd", ".heic", ".webp", ".gif", ".tif", ".tiff", ".bmp",
                    ".mp4", ".mov", ".zip", ".rar")

SLUG_RE = re.compile(r"^[a-z0-9-]{3,40}$")

PHOTO_CAP_COVER = 150 * 1024
PHOTO_CAP_BIG = 250 * 1024
PHOTO_CAP_THUMB = 60 * 1024
COVER_SIZE = (1200, 675)          # 16:9
BIG_EDGE = 1280
THUMB_EDGE = 480
Q_COVER, Q_BIG, Q_THUMB = 82, 80, 78
Q_FLOOR = 70                      # --auto-quality 的下限


def slug_ok(slug):
    return bool(slug) and bool(SLUG_RE.match(slug))


def fit_within(im, edge):
    u"""长边压到 ≤edge；**源不够大就不放大**（全管线通行"只缩不放"）。

    返回值直接写进 HTML 的 width/height，所以必须是真实像素。
    """
    w, h = im.size
    if max(w, h) <= edge:
        return im
    scale = edge / float(max(w, h))
    return im.resize((max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
                     Image.LANCZOS)


def make_cover(im, crop_mode):
    u"""16:9 裁切后缩到 1200×675；**源不够大就按源能力输出**，不放大。

    注意两步都要：只裁不缩会留下 6000×3375 这样的巨图（实测踩过），
    只缩不裁会破坏 16:9。输出尺寸会被写进 HTML 的 width/height，必须是真实像素。
    """
    w, h = im.size
    ar = COVER_SIZE[0] / float(COVER_SIZE[1])
    if w / float(h) > ar:
        cw, ch = int(round(h * ar)), h
    else:
        cw, ch = w, int(round(w / ar))
    cw, ch = max(1, min(cw, w)), max(1, min(ch, h))
    if crop_mode == "top":
        top = 0
    elif crop_mode == "bottom":
        top = h - ch
    else:
        top = (h - ch) // 2
    left = (w - cw) // 2
    tw, th = min(COVER_SIZE[0], cw), min(COVER_SIZE[1], ch)
    return im.crop((left, top, left + cw, top + ch)).resize((tw, th), Image.LANCZOS)


def save_jpeg(im, path, quality, cap, auto_quality):
    u"""存 JPEG 并守住体积；--auto-quality 时二分降 q（下限 70）。

    返回 (实际质量, 实际字节, 是否仍超限)。
    """
    q = quality
    while True:
        buf = BytesIO()
        im.save(buf, "JPEG", quality=q, progressive=True, optimize=True)
        size = buf.tell()
        if size <= cap or not auto_quality or q <= Q_FLOOR:
            break
        q = max(Q_FLOOR, q - 4)
    with io.open(path, "wb") as fh:
        fh.write(buf.getvalue())
    return q, size, size > cap


def load_photo(path, reject_alpha, problems):
    u"""按固定顺序处理：open → exif_transpose → 铺白底 → RGB。

    exif_transpose 必须在最前面：手机竖拍的照片靠 Orientation 标签才是正的，
    不先转置，后面所有裁切都按错误的宽高比算，人物会被裁掉头。
    """
    im = Image.open(path)
    im = ImageOps.exif_transpose(im) or im
    if im.mode in ("RGBA", "LA", "P"):
        rgba = im.convert("RGBA")
        if reject_alpha:
            problems.append(u"✗ %s 含透明通道（--reject-alpha）" % os.path.basename(path))
            return None
        problems.append(u"! %s 含透明通道，已铺白底" % os.path.basename(path))
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, rgba)
    return im.convert("RGB")


def process_photos(dirpath, slug, cover=None, crop="center", thumbs=False,
                   auto_quality=False, reject_alpha=False, quiet=False):
    u"""活动照片入库。返回 (退出码, 输出说明行)。"""
    lines = []
    problems = []
    if not slug_ok(slug):
        return 1, [u"✗ slug 必须匹配 ^[a-z0-9-]{3,40}$（收到 %r）" % slug]
    if not os.path.isdir(dirpath):
        return 1, [u"✗ 输入目录不存在：%s" % dirpath]

    outdir = os.path.join(IMG, "activities")
    if not os.path.isdir(outdir):
        os.makedirs(outdir)

    names = sorted(os.listdir(dirpath))
    usable, skipped = [], []
    for n in names:
        p = os.path.join(dirpath, n)
        if not os.path.isfile(p):
            continue
        ext = os.path.splitext(n)[1].lower()
        if ext in PHOTO_SUPPORTED:
            usable.append(n)
        else:
            skipped.append(n)

    if not usable:
        return 1, [u"✗ 目录里没有可处理的图片（jpg/jpeg/png）：%s" % dirpath]

    lines.append(u"输入 %s：可用 %d 张，跳过 %d 个" % (dirpath, len(usable), len(skipped)))
    for n in skipped:
        lines.append(u"! SKIP %s（不支持的格式，未静默跳过）" % n)

    numbered = len(usable) > 99
    total = 0

    # ① 封面
    cover_name = cover if cover in usable else usable[0]
    if cover is not None and cover not in usable:
        lines.append(u"! --cover %s 不在可用清单里，改用 %s" % (cover, cover_name))
    im = load_photo(os.path.join(dirpath, cover_name), reject_alpha, problems)
    if im is not None:
        cov = make_cover(im, crop)
        path = os.path.join(outdir, "cover-%s.jpg" % slug)
        q, size, over = save_jpeg(cov, path, Q_COVER, PHOTO_CAP_COVER, auto_quality)
        total += size
        lines.append(u"✓ cover-%s.jpg  %d×%d  q=%d  %d B%s"
                     % (slug, cov.size[0], cov.size[1], q, size,
                        u"  ← 超限！" if over else u""))
        if over:
            problems.append(u"✗ cover-%s.jpg 超 150 KB，建议 --auto-quality 或人工先缩" % slug)

    # ② 图集
    for i, n in enumerate(usable, 1):
        im = load_photo(os.path.join(dirpath, n), reject_alpha, problems)
        if im is None:
            continue
        big = fit_within(im, BIG_EDGE)
        stem = u"%s-%s" % (slug, u"%03d" % i if numbered else u"%02d" % i)
        path = os.path.join(outdir, stem + ".jpg")
        q, size, over = save_jpeg(big, path, Q_BIG, PHOTO_CAP_BIG, auto_quality)
        total += size
        lines.append(u"✓ %s.jpg  %d×%d  q=%d  %d B%s"
                     % (stem, big.size[0], big.size[1], q, size,
                        u"  ← 超限！" if over else u""))
        if over:
            problems.append(u"✗ %s.jpg 超 250 KB" % stem)
        if thumbs:
            th = fit_within(im, THUMB_EDGE)
            tpath = os.path.join(outdir, stem + u"-s.jpg")
            q, size, over = save_jpeg(th, tpath, Q_THUMB, PHOTO_CAP_THUMB, auto_quality)
            total += size
            lines.append(u"✓ %s-s.jpg  %d×%d  %d B%s"
                         % (stem, th.size[0], th.size[1], size,
                            u"  ← 超限！" if over else u""))

    # ③ 回读断言：没有任何一张带 EXIF（Pillow 恒定带 20 字节空段，故断言"标签数为 0"）
    bad = []
    for f in sorted(os.listdir(outdir)):
        if not f.endswith(".jpg"):
            continue
        p = os.path.join(outdir, f)
        n = len(Image.open(p).getexif())
        if n != 0:
            bad.append(u"✗ %s EXIF 标签数 %d" % (f, n))
    problems.extend(bad)

    lines.append(u"合计 %d B（%d 个文件）" % (total, len(usable) + (1 if thumbs else 0) + 1))
    lines.extend(problems)
    ok = not [p for p in problems if p.startswith(u"✗")]
    return (0 if ok else 1), lines


def contact_sheet(dirpath, out_path, cols=5, cell=240):
    u"""选图辅助：把目录里的图拼成一张带文件名的接触表，输出到项目**外**（不入库）。"""
    names = [n for n in sorted(os.listdir(dirpath))
             if os.path.splitext(n)[1].lower() in PHOTO_SUPPORTED]
    if not names:
        return 1, [u"✗ 目录里没有可处理的图片：%s" % dirpath]
    rows = (len(names) + cols - 1) // cols
    label_h = 22
    sheet = Image.new("RGB", (cols * cell, rows * (cell + label_h)), (246, 247, 249))
    font = load_font("msyh.ttc", 14)
    draw = ImageDraw.Draw(sheet)
    for i, n in enumerate(names):
        im = Image.open(os.path.join(dirpath, n))
        im = ImageOps.exif_transpose(im) or im
        im = im.convert("RGB")
        im.thumbnail((cell - 8, cell - 8), Image.LANCZOS)
        x = (i % cols) * cell + (cell - im.size[0]) // 2
        y = (i // cols) * (cell + label_h) + (cell - im.size[1]) // 2
        sheet.paste(im, (x, y))
        if font is not None:
            draw.text(((i % cols) * cell + 4, (i // cols) * (cell + label_h) + cell + 2),
                      n[:28], font=font, fill=(31, 35, 41))
    d = os.path.dirname(out_path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    sheet.save(out_path, "JPEG", quality=80, progressive=True)
    return 0, [u"✓ 接触表 %s（%d 张，%d×%d）"
               % (out_path, len(names), sheet.size[0], sheet.size[1])]


# --------------------------------------------------------------------------
# image-manifest.tsv（E31）：图片的唯一清单，check_site 靠它交叉断言
# --------------------------------------------------------------------------
def manifest_rows():
    rows = []
    for base, _dirs, files in os.walk(IMG):
        for f in sorted(files):
            if not f.lower().endswith(MANIFEST_EXT):
                continue
            p = os.path.join(base, f)
            rel = os.path.relpath(p, ROOT).replace("\\", "/")
            try:
                im = Image.open(p)
                if f.lower().endswith(".ico"):
                    w, h = sorted(im.ico.sizes())[-1]
                else:
                    w, h = im.size
            except Exception:
                continue
            rows.append((rel, w, h, os.path.getsize(p)))
    return sorted(rows)


def render_manifest():
    lines = [u"path\twidth\theight\tbytes"]
    for rel, w, h, size in manifest_rows():
        lines.append(u"%s\t%d\t%d\t%d" % (rel, w, h, size))
    return (u"\n".join(lines) + u"\n").encode("utf-8")


def write_bytes(rel, data):
    path = os.path.join(ROOT, rel)
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    old = None
    if os.path.isfile(path):
        with io.open(path, "rb") as fh:
            old = fh.read()
    if old != data:
        with io.open(path, "wb") as fh:
            fh.write(data)
        return True
    return False


# --------------------------------------------------------------------------
# 生成
# --------------------------------------------------------------------------
def generate(report):
    changed = 0
    for name, size, kind, percent in EMBLEM_SPECS:
        rel = "assets/img/" + name
        if write_bytes(rel, render_emblem_png(name, size, kind, percent)):
            report.append(u"✓ 生成 %s（%d×%d）" % (rel, size, size))
            changed += 1
    rel = "assets/img/" + ICO_NAME
    if write_bytes(rel, render_ico()):
        report.append(u"✓ 生成 %s（帧 %s）" % (rel, u"+".join(str(s) for s in ICO_FRAMES)))
        changed += 1
    for name, size in ICON_SPECS:
        rel = "assets/img/" + name
        if write_bytes(rel, render_icon_png(size)):
            report.append(u"✓ 生成 %s（%d×%d，铺底 %s）" % (rel, size, size, BRAND_BLUE_HEX))
            changed += 1
    rel = "assets/img/" + OG_NAME
    og_bytes, meta = render_og()
    if write_bytes(rel, og_bytes):
        report.append(u"✓ 生成 %s（%d×%d，文字墨点 %d）" % (rel, OG_W, OG_H, meta["ink"]))
        changed += 1
    for name, src_name in MASCOT_SPECS:
        rel = "assets/img/" + name
        data, size = render_mascot(src_name)
        if write_bytes(rel, data):
            report.append(u"✓ 生成 %s（%d×%d，%d B）" % (rel, size[0], size[1], len(data)))
            changed += 1
    if refresh_404():
        report.append(u"✓ 刷新 404.html 的 404:ART 块")
        changed += 1
    rel = "assets/img/image-manifest.tsv"
    if write_bytes(rel, render_manifest()):
        report.append(u"✓ 刷新 %s（%d 项）" % (rel, len(manifest_rows())))
        changed += 1
    return changed


# --------------------------------------------------------------------------
# 校验
# --------------------------------------------------------------------------
def luminance(rgb):
    r, g, b = rgb[:3]
    return 0.299 * r + 0.587 * g + 0.114 * b


def check(rep):
    ok = True

    # 1) 每个产物：存在 + 逐字节与重算一致（幂等的最强形式）+ 无 EXIF + 体积
    for name, size, kind, percent in EMBLEM_SPECS:
        rel = "assets/img/" + name
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            rep.fail("image", rel, u"产物不存在")
            ok = False
            continue
        disk = io.open(path, "rb").read()
        if disk != render_emblem_png(name, size, kind, percent):
            rep.fail("image", rel, u"与重算结果不一致（图被手改过或管线变了）")
            ok = False
        im = Image.open(path)
        if im.size != (size, size):
            rep.fail("image", rel, u"尺寸 %s，应为 %d×%d" % (im.size, size, size))
            ok = False
        if len(im.getexif()) != 0:
            rep.fail("image", rel, u"EXIF 标签数 %d（应为 0）" % len(im.getexif()))
            ok = False
        if os.path.getsize(path) > CAP_PNG:
            rep.fail("image", rel, u"体积 %d B 超上限 %d" % (os.path.getsize(path), CAP_PNG))
            ok = False

    # 2) 清洗生效：全透明像素的 RGB 亮度 ≥60（否则被拍平时会出黑边）
    p256 = os.path.join(IMG, "logo-emblem-256.png")
    if os.path.isfile(p256):
        im = Image.open(p256).convert("RGBA")
        px = im.load()
        worst = None
        for y in range(im.size[1]):
            for x in range(im.size[0]):
                r, g, b, a = px[x, y]
                if a == 0:
                    lum = luminance((r, g, b))
                    if worst is None or lum < worst:
                        worst = lum
        if worst is None:
            rep.fail("image", "logo-emblem-256.png", u"没有全透明像素（会徽应内切画布、四角透明）")
            ok = False
        elif worst < 60:
            rep.fail("image", "logo-emblem-256.png",
                     u"有透明像素未被清洗：最低亮度 %.1f（应 ≥60）" % worst)
            ok = False

    # 3) 主屏族：铺底生效（alpha 全 255）+ 尺寸正确
    for name, size in ICON_SPECS:
        rel = "assets/img/" + name
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            rep.fail("image", rel, u"产物不存在")
            ok = False
            continue
        if io.open(path, "rb").read() != render_icon_png(size):
            rep.fail("image", rel, u"与重算结果不一致")
            ok = False
        im = Image.open(path).convert("RGBA")
        if im.size != (size, size):
            rep.fail("image", rel, u"尺寸 %s，应为 %d×%d" % (im.size, size, size))
            ok = False
        lo, hi = im.getchannel("A").getextrema()
        if (lo, hi) != (255, 255):
            rep.fail("image", rel, u"存在非全不透明像素（alpha 范围 %s，铺底未生效）" % ((lo, hi),))
            ok = False
        if len(Image.open(path).getexif()) != 0:
            rep.fail("image", rel, u"EXIF 标签数非 0")
            ok = False

    # 4) OG 封面
    og_path = os.path.join(IMG, OG_NAME)
    if not os.path.isfile(og_path):
        rep.fail("image", OG_NAME, u"产物不存在")
        ok = False
    else:
        og_bytes, meta = render_og()
        if io.open(og_path, "rb").read() != og_bytes:
            rep.fail("image", OG_NAME, u"与重算结果不一致（文案或管线变过）")
            ok = False
        im = Image.open(og_path)
        if im.size != (OG_W, OG_H):
            rep.fail("image", OG_NAME, u"尺寸 %s，应为 %d×%d" % (im.size, OG_W, OG_H))
            ok = False
        size_b = os.path.getsize(og_path)
        if size_b > OG_CAP:
            rep.fail("image", OG_NAME, u"体积 %d B 超上限 %d（微信可能不显示卡片图）"
                     % (size_b, OG_CAP))
            ok = False
        # 防"静默渲染空白"：字体缺失/字形缺失时图片会是一张干净底图，看不出错
        if meta["ink"] < 3000:
            rep.fail("image", OG_NAME, u"文字区非底色像素仅 %d（<3000），疑似文字没渲染上"
                     % meta["ink"])
            ok = False
        rep.info(u"%s：%d×%d，%d B；文字墨点 %d（阈值 ≥3000）"
                 % (OG_NAME, OG_W, OG_H, size_b, meta["ink"]))

    # 5) favicon.ico 三帧
    icopath = os.path.join(IMG, ICO_NAME)
    if os.path.isfile(icopath):
        frames = len(Image.open(icopath).ico.sizes())
        if frames != 3:
            rep.fail("image", ICO_NAME, u"帧数 %d（应 3）" % frames)
            ok = False
    else:
        rep.fail("image", ICO_NAME, u"产物不存在")
        ok = False

    # 6) 吉祥物：尺寸必须与源一致（"只缩不放"的反面——也不许被放大），四角透明仍在
    for name, src_name in MASCOT_SPECS:
        rel = "assets/img/" + name
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            rep.fail("image", rel, u"产物不存在")
            ok = False
            continue
        data, src_size = render_mascot(src_name)
        if io.open(path, "rb").read() != data:
            rep.fail("image", rel, u"与重算结果不一致")
            ok = False
        im = Image.open(path).convert("RGBA")
        if im.size != src_size:
            rep.fail("image", rel, u"尺寸被改动：%s，源为 %s" % (im.size, src_size))
            ok = False
        corners = [(0, 0), (im.size[0] - 1, 0), (0, im.size[1] - 1),
                   (im.size[0] - 1, im.size[1] - 1)]
        for pt in corners:
            if im.getpixel(pt)[3] != 0:
                rep.fail("image", rel, u"角像素 %s 的 alpha 非 0（%d）" % (pt, im.getpixel(pt)[3]))
                ok = False
                break
        size_b = os.path.getsize(path)
        rep.info(u"%s：%d×%d，%d B（上限 %d）" % (name, im.size[0], im.size[1], size_b, MASCOT_CAP))
        if size_b > MASCOT_CAP:
            rep.fail("image", rel, u"体积 %d B 超上限 %d" % (size_b, MASCOT_CAP))
            ok = False
        if len(Image.open(path).getexif()) != 0:
            rep.fail("image", rel, u"EXIF 标签数非 0")
            ok = False

    # 7) favicon-16 的像素构成：16×16 只有 208 个不透明像素，只有像素级断言能证明
    #    "还是那个会徽，而不是一个色块"。阈值见 §5.2（**首跑校准后固定**）。
    #
    #    首跑校准结论（2026-10-08，实测值即下方打印值）：
    #      · 火焰像素 实测 8 → 阈值取 6（留 2 个余量）
    #      · "蓝环"在 16px 下**物理上不可分辨**：外环厚度 ≈10% 半径 ≈ 0.8 像素，
    #        重采样后每颗都被邻近的白面/透明稀释，实测无一落在 #2E5EA3 的 ±40 窗口内
    #        （严格判据只数到 2 个）。因此把该断言的操作性定义改为**蓝色主导**
    #        （b > r+15 且 b > 150）——它同样能抓住"蓝没了"或"整片糊成一个色块"的回归，
    #        实测 98 → 阈值取 70。
    p16 = os.path.join(IMG, "favicon-16.png")
    if os.path.isfile(p16):
        im = Image.open(p16).convert("RGBA")
        px = im.load()
        flame = blue = opaque = 0
        for y in range(im.size[1]):
            for x in range(im.size[0]):
                r, g, b, a = px[x, y]
                if a < 128:
                    continue
                opaque += 1
                if r > 150 and g > 60 and b < 80:
                    flame += 1
                if b > r + 15 and b > 150:
                    blue += 1
        rep.info(u"favicon-16.png：不透明 %d 像素；火焰 %d（阈值 ≥6）、蓝色主导 %d（阈值 ≥70）"
                 % (opaque, flame, blue))
        if opaque < 150:
            rep.fail("image", "favicon-16.png", u"不透明像素仅 %d，图基本是空的" % opaque)
            ok = False
        if flame < 6:
            rep.fail("image", "favicon-16.png", u"火焰像素 %d < 6（缩丢了）" % flame)
            ok = False
        if blue < 70:
            rep.fail("image", "favicon-16.png", u"蓝色主导像素 %d < 70（蓝没了或糊成一团）" % blue)
            ok = False

    # 8) 404 的 ART 块：必须存在，且与当前源重算一致（图换了却忘了刷新 = 线上 404 还是旧图）
    if not os.path.isfile(PAGE_404):
        rep.info(u"404.html 尚未建立——ART 块校验留待模板写入后（T19）")
    else:
        text = io.open(PAGE_404, "r", encoding="utf-8", newline="").read()
        m = ART_RE.search(text)
        if m is None:
            rep.fail("image", "404.html", u"找不到 404:ART 标记块")
            ok = False
        else:
            indent = re.match(r"[ \t]*", m.group(0)).group(0)
            if m.group(0) != render_404_art(indent):
                rep.fail("image", "404.html", u"404:ART 块与当前源不一致（图换了没刷新）")
                ok = False
        size_b = os.path.getsize(PAGE_404)
        rep.info(u"404.html：%d B（上限 %d）" % (size_b, PAGE_404_CAP))
        if size_b > PAGE_404_CAP:
            rep.fail("image", "404.html", u"体积 %d B 超上限 %d" % (size_b, PAGE_404_CAP))
            ok = False

    # 9) 清单与磁盘逐项一致（E31）：清单是 check_site 交叉断言的依据，它自己先得可信
    man_path = MANIFEST
    if not os.path.isfile(man_path):
        rep.fail("image", "image-manifest.tsv", u"清单不存在")
        ok = False
    else:
        disk = io.open(man_path, "rb").read()
        want = render_manifest()
        if disk != want:
            have = set(disk.decode("utf-8").split("\n"))
            need = set(want.decode("utf-8").split("\n"))
            missing = sorted(x for x in need - have if x)[:5]
            rep.fail("image", "image-manifest.tsv",
                     u"清单与磁盘不一致（例：%s）" % (u" | ".join(missing) or u"行数不同"))
            ok = False
        else:
            rep.info(u"image-manifest.tsv：%d 项，与磁盘一致" % (len(manifest_rows())))

    return ok


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
class CheckReport(object):
    def __init__(self):
        self.rows = []

    def fail(self, rule, where, message):
        self.rows.append(("FAIL", rule, where, message))

    def info(self, message):
        self.rows.append(("INFO", "", "", message))

    def total(self, level):
        return sum(1 for r in self.rows if r[0] == level)

    def dump(self):
        for level, rule, where, message in self.rows:
            if level == "FAIL":
                print(u"✗ [%s] %s: %s" % (rule, where, message))
            else:
                print(u"· %s" % message)


def main(argv):
    soften_stdout()
    if not argv:
        out = []
        n = generate(out)
        for line in out:
            print(line)
        if not n:
            print(u"✓ 无需改动（全部已是最新）")
        print(u"")
        print(u"OK 生成完毕。校验：python tools/make_images.py --check")
        return 0
    if argv[0] == "--check":
        rep = CheckReport()
        good = check(rep)
        rep.dump()
        print(u"")
        if rep.total("FAIL"):
            print(u"FAIL %d" % rep.total("FAIL"))
            return 1
        print(u"OK 图片管线全绿（FAIL 0 / WARN 0）")
        return 0
    if argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0

    if argv[0] == "--photos":
        opts = {"cover": None, "crop": u"center", "thumbs": False,
                "auto_quality": False, "reject_alpha": False}
        dirpath = slug = None
        rest = argv[1:]
        i = 0
        while i < len(rest):
            a = rest[i]
            if a in ("--slug", "--cover", "--crop"):
                if i + 1 >= len(rest):
                    print(u"✗ %s 缺参数" % a)
                    return 2
                opts[a[2:].replace("-", "_")] = rest[i + 1]
                i += 2
                continue
            if a == "--thumbs":
                opts["thumbs"] = True
            elif a == "--auto-quality":
                opts["auto_quality"] = True
            elif a == "--reject-alpha":
                opts["reject_alpha"] = True
            elif a.startswith("--"):
                print(u"✗ 未知参数：%s" % a)
                return 2
            elif dirpath is None:
                dirpath = a
            else:
                print(u"✗ 只接受一个输入目录")
                return 2
            i += 1
        if not dirpath or not opts.get("slug"):
            print(u"✗ --photos 需要 <目录> 与 --slug <slug>")
            return 2
        if opts["crop"] not in (u"center", u"top", u"bottom"):
            print(u"✗ --crop 只能是 center / top / bottom")
            return 2
        code, lines = process_photos(dirpath, opts["slug"], cover=opts["cover"],
                                     crop=opts["crop"], thumbs=opts["thumbs"],
                                     auto_quality=opts["auto_quality"],
                                     reject_alpha=opts["reject_alpha"])
        for line in lines:
            print(line)
        if code == 0:
            out = []
            generate(out)
            for line in out:
                print(line)
            print(u"")
            print(u"OK 照片已入库；清单已刷新。校验：python tools/make_images.py --check")
        return code

    if argv[0] == "--contact-sheet":
        dirpath = out_path = None
        rest = argv[1:]
        i = 0
        while i < len(rest):
            if rest[i] == "--out":
                if i + 1 >= len(rest):
                    print(u"✗ --out 缺参数")
                    return 2
                out_path = rest[i + 1]
                i += 2
                continue
            if rest[i].startswith("--"):
                print(u"✗ 未知参数：%s" % rest[i])
                return 2
            dirpath = rest[i]
            i += 1
        if not dirpath or not out_path:
            print(u"✗ --contact-sheet 需要 <目录> 与 --out <文件>")
            return 2
        code, lines = contact_sheet(dirpath, out_path)
        for line in lines:
            print(line)
        return code

    print(u"未知参数：%s\n" % argv[0])
    print(__doc__.strip())
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
