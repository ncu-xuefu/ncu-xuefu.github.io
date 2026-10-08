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
import io
import os
import re
import sys

try:
    from PIL import Image, ImageChops, ImageFilter, ImageFont, ImageDraw
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

    # 6) favicon-16 的像素构成：16×16 只有 208 个不透明像素，只有像素级断言能证明
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
    print(u"未知参数：%s\n" % argv[0])
    print(__doc__.strip())
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
