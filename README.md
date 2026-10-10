# 南昌大学教务处学生学习服务中心 · 门户网站

对外门户静态站，7 个页面 + 1 个错误页，托管在 GitHub Pages 上。

**当前状态**：站点已按《门户网站实现方案》M0–M3 建成并**已上线到 GitHub Pages**
（<https://ncu-xuefu.github.io/>，2026-10-10）。**内容仍是占位**（`【待填·…】`），
施工期 `noindex` 仍然保留——**这不是正式发布**，只是让中心能打开链接看样张。

下一步：向中心回收内容（见《门户网站MVP计划书》附录 A）→ 逐页替换占位 →
`--release` 转绿 → 摘 `noindex`（见第 5 节②）→ 才算 M5 正式上线。

> ⚠ **此处不得出现任何密钥 / 口令 / 个人信息。**
> 本仓库是公开的：`tools/` 与所有文件都能被任何人下载。

---

## 1. 这是什么 · 四条红线

纯静态多页 HTML。**没有框架、没有构建、没有 npm、没有第三方运行时代码**——
仓库里被提交的文件就是被服务的文件。

1. **零外链**：不引任何 CDN / 字体 / 统计脚本。全站只有 14 处绝对 URL，
   是 7 个页面的 `og:url` 与 `og:image`（分享卡必须有绝对地址）。
2. **零构建**：`tools/` 下的三个脚本是**生成器与检查器**，不是构建步骤——忘了跑，网站照常运行。
3. **手机优先**：一切布局从 360px 起成立；验收宽度 360 / 390 / 414 / 768 / 1280。
4. **与《学服问答自动整理系统》零耦合**：不引用它的任何代码或数据，
   只共享品牌资产（会徽 / 吉祥物 / 色板）——品牌源图已一次性复制留档在 `brand-src/`。

**本地预览**：双击 `index.html` 即可（不需要任何服务器）。
若发现某个浏览器下样式没更新，改用 `python -m http.server 8000` 后访问 <http://localhost:8000/>。

## 2. 文件职责

| 文件 | 职责 | 谁会改 |
|---|---|---|
| `index.html` 等 7 个页面 | 页面内容（正文直接写在里面） | 维护者 / 非技术成员，按《内容更新.md》 |
| `assets/css/site.css` | **全部样式**（改内容永远碰不到它） | 只在做视觉调整时 |
| `assets/js/site.js` | 仅两个功能：手机菜单抽屉、页脚年份 | 基本不动 |
| `404.html` | 自包含错误页（全站唯一刻意重复样式处） | 基本不动 |
| `assets/img/` | 生成出来的图片 + `image-manifest.tsv` | **只由工具生成**，不要手改 |
| `brand-src/` | 品牌源图只读留档，页面不引用 | 基本不动 |
| `tools/make_images.py` | 图片全套生成 + 照片管线（幂等） | 基本不动 |
| `tools/check_site.py` | 上线门禁自检（S1–S24） | 基本不动 |
| `tools/sync_common.py` | 7 页公共块一致性 | 改导航 / 换域名时 |
| `内容更新.md` | **给非技术成员的操作手册** | 与结构同步维护 |

**7 页共用的三块**（页头导航 `<head>` 公共段、页脚）用注释界定，**逐字节相同**：

```html
<!-- COMMON:HEAD BEGIN --> … <!-- COMMON:HEAD END -->
<!-- COMMON:NAV BEGIN --> … <!-- COMMON:NAV END -->
<!-- COMMON:FOOT BEGIN --> … <!-- COMMON:FOOT END -->
```

外加两块重复内容：`SYNC:SERVICES-CARDS`（服务卡，源在 `index.html`）、
`SYNC:OFFICE-HOURS`（值班时间与地点，源在 `services.html`）。

> ⚠ **改 7 处必出事故。** 改导航、页脚、服务卡、值班时间，一律走
> `python tools/sync_common.py --fix`，**不要手改各页**。

## 3. 三个工具的用法

```bash
# 施工期每次改完
python tools/check_site.py              # 结构/内容/预算；WARN 可接受，FAIL 必须为 0
python tools/sync_common.py --check     # 7 页公共块一致

# 提交前
python tools/make_images.py --check     # 图片管线：无 EXIF、体积、尺寸、清单一致
git status --porcelain                  # 确认没有意外文件

# 上线门禁（M5）
python tools/check_site.py --release    # 必须退出 0（占位清零、noindex 已摘）
```

辅助命令：

```bash
python tools/check_site.py --contrast   # 打印色板对比度验算表
python tools/check_site.py --ids        # 打印全站 id 清单（归档用）
python tools/sync_common.py --bump 20261015   # 改过 css/js 后推缓存串（css 与 js 同值）
python tools/make_images.py --photos "<目录>" --slug <短名>   # 活动照片入库
python tools/make_images.py --contact-sheet "<目录>" --out "<项目外的路径>"  # 选图辅助
```

## 4. 账号归属与交接（**只记"谁负责"，不记任何口令**）

| 项目 | 现状 | 交接要求 |
|---|---|---|
| GitHub 组织 | 待建（建议 `ncu-xuefu`） | **owner ≥ 2 人**：现任负责人 + 指导老师或上届负责人 |
| 仓库 | 待建（org 用户站须命名为 `<org>.github.io`） | Public；站点放仓库根 |
| 推送通道 | 待配 | fine-grained 令牌（仅该仓库 contents:write）存**凭据管理器**，或 SSH 密钥 |
| 域名 | 未定（A20） | 若购买，**必须由中心/教务处持有**（组织邮箱、走中心账），不得落在个人名下 |
| 品牌资产著作权 | **待中心书面确认（A17）** | 确认前不得对外宣称所有权 |

**年度日历**：9 月招新 → 每学期开学发公告 → 6 月换届 → 每年检查域名与托管。

**交接时逐项过**：《门户网站MVP计划书》§9 验收表；并让一位从未接触过的同学
照《内容更新.md》独立加一条公告成功（《内容更新.md》第 7 节有勾选表）。

## 5. 上线步骤（命令级）

> **先做这两件事，再推送。** 它们是上线前唯一容易做错的步骤。

### ① 如果组织名不叫 `ncu-xuefu`

全站有 14 处地址（7 页 × `og:url` + `og:image`）**硬编码**了 `https://ncu-xuefu.github.io/`，
另外 `tools/check_site.py` 顶部的 `SITE_URL` 常量也是它。组织名若不同，推送前改这三处：

```bash
# 1) 改校验器里的常量（1 处）
#    tools/check_site.py  →  SITE_URL = "https://<你的org>.github.io/"

# 2) 改 index.html 的 COMMON:HEAD 里那一行 og:image（1 行）→ 然后同步到全站
python tools/sync_common.py --fix

# 3) 改 7 页各自的 og:url（每页 1 行；它们在 COMMON 块外，所以要逐页改）

python tools/check_site.py      # S3 会核对绝对 URL 前缀；改错了这里会红
```

改错的后果不是静默的：`check_site.py` 的 S3 会因为前缀对不上而报 FAIL——分享卡图与链接全废，
但你能发现。

### ② 摘掉施工期的 `noindex`

施工期 7 页都带着 `<meta name="robots" content="noindex">`（防止占位内容被搜索引擎收录）。
它在 **COMMON:HEAD 块里**，所以**只改一处**：

```bash
# 1) 删掉 index.html 中 COMMON:HEAD 里的这一行：
#    <meta name="robots" content="noindex">
# 2) 同步到其余 6 页：
python tools/sync_common.py --fix
# 3) 确认：
python tools/check_site.py --release    # S21 会断言"7 页都不含 noindex、404 恒含"
```

> ⚠ **不要手改 7 个页面**——COMMON 块是单源的，手改会在下一次 `--fix` 时被覆盖回去，
> 而且极容易漏掉一页。这正是"改 7 处必出事故"那一条。
> 404.html 的 `noindex` **要保留**（错误页永远不该被收录），它不在 COMMON 块里。

```bash
# ① 先在 GitHub 网页建好 org 与仓库 <org>.github.io（Public），然后：
git remote add origin https://github.com/<org>/<org>.github.io.git
git push -u origin main

# ② 网页操作：Settings → Pages → Source: Deploy from a branch → main / (root) → Save
# ③ 等 1–2 分钟：Settings → Pages → 勾选 Enforce HTTPS
# ④ 上线断言：
BASE=https://<org>.github.io
curl -s -o /dev/null -w "%{http_code}\n" $BASE/
for p in index about services notices team activities contact; do
  curl -s -o /dev/null -w "$p %{http_code}\n" $BASE/$p.html; done
curl -s $BASE/this-does-not-exist | grep -c "这个页面走丢了"    # 期望 1（断言内容，不只是状态码）
```

**日常发布**：改内容 → 改 `index.html` 页脚的「最后更新」→
`python tools/sync_common.py --fix` → `python tools/check_site.py` → 提交推送。

**改过 css/js 后**：`python tools/sync_common.py --bump <当天日期>` → `--fix` → 提交。
微信缓存顽固，换了缓存串才看得到新样式。

**换域名**：改 `index.html` 的 `og:image` + 7 页 `og:url`，`og-cover.png` **换文件名**
（微信按 URL 缓存分享卡），再 `--fix`。`404.html` 不用改（它的链接是根绝对路径）。

## 6. 出事了怎么办

| 情况 | 处置 |
|---|---|
| 某个文件改坏了 | `git checkout -- <文件>` |
| 某个任务整体改坏了 | `git reset --hard <上一个里程碑的提交>` |
| git 完全不可用 | 用 `F:\claudecode\backup\` 下的整目录备份覆盖 |
| 线上是旧的 | 先看是不是微信缓存：换个链接参数试；再确认缓存串是否推过 |
| 404 页显示成裸白页 | 检查 `404.html` 是不是被引用了 `site.css`——它**必须自包含** |

**上线实测结论（2026-10-10，回填方案 §11.2 的待实测项）**

| 项 | 结论 |
|---|---|
| **D10：`.nojekyll` × 自定义 404** | ✅ **不冲突**。`/this-does-not-exist` 与深层 `/a/b/c` 都返回 **404 状态码 + 自定义 404 内容**（含内联会徽 data-URI）。保留 `.nojekyll` 的决定成立，不需要走"接受默认 404"的退路——**这条未决项关闭**。同时这也验证了 404 用**根绝对路径**是对的：深层 URL 下相对路径必挂（E5）。 |
| **D1**：根 + 7 页 | ✅ 全部 200 |
| **D2**：Enforce HTTPS | ✅ 默认开启，`http://` → 301 → `https://` |
| **D3**：404 | ✅ 见上 |
| 静态资源 | ✅ `site.css` 返回 `text/css; charset=utf-8`；`?v=20261008` 的 css/js 均 200；`favicon.ico`、`manifest.json`、`.nojekyll`、`og-cover.png`（119,352 B）均 200 |
| `file://` 下的 `manifest.json` | ⚠️ 浏览器因 CORS **拒绝加载**（Chrome/Edge 报 "blocked by CORS policy"）。不影响页面显示，用 HTTP 打开即正常，**不是缺陷**。 |
| 本机推代码的通道 | ⚠️ `github.com:443` 被网络阻断，**只能走 SSH**（见 §5 的 `url.insteadOf` 配置）。 |

**仍然待测（需要真机/中心）**：D4 微信分享卡、D5 微信内置浏览器逐页、D6 多平台截图、
D7 缓存串强刷、R8 真机"强制深色"、校园网可达性。
