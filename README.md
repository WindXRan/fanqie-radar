# 番茄雷达 Fanqie Radar

> **番茄小说榜单数据 · 扫榜选书工作台 · MCP Server**（fanqie novel rank data / webnovel trend analysis / imitation book scoring）
> 零配置、零第三方运行时依赖，纯 Python 标准库，**内置示例数据装完即用**。可选扫榜采集（Playwright）。

在 Claude / Cursor / 任意 MCP 客户端里直接问「现在女频什么火」「这本适合仿写吗」「豪门总裁赛道热度如何」，它就答。也可以打开自带的可视化看板，像人一样翻封面、扫书名、看在读、收藏候选。

![看板](docs/screenshot.jpg)

**关键词**：番茄小说 · 番茄榜单 · 扫榜 · 网文数据 · 网文选题 · 题材热度 · 仿写选书 · AI 写作 · MCP · Model Context Protocol · MCP Server · 数据看板

---

## 它解决什么

网文作者/AI 写作从业者天天要回答三个问题：**现在什么题材火？哪本书适合仿？为什么？**

市面上番茄榜单爬虫一大堆，但爬完就扔给你一堆书名。真正稀缺的是**选书判断力**——这本能不能仿、仿出来质量天花板在哪。本项目把方寸写作跑了真金白银验证过的**六维仿写选书评分模型**开源出来，并包成 MCP 服务，让你的 AI 助手直接具备这套判断力。

### 差异化（为什么值得装）

| 能力 | 普通榜单爬虫 | 本仓库 |
|---|---|---|
| 榜单数据 | ✅ | ✅（自备快照，附示例数据） |
| 题材热度聚合 | 偶尔 | ✅ |
| 跨榜强信号（新书即爆款） | ❌ | ✅ |
| 多日趋势差分 | ❌ | ✅ |
| **仿写适合度评分** | ❌ | ✅ **六维 + 加成，数据驱动** |
| 可视化扫榜看板 | ❌ | ✅ |
| 接入 AI 助手（MCP） | ❌ | ✅ |
| 上手成本 | 要配数据源 | **零配置，装完即用** |

评分模型是核心资产，不是拍脑袋的硬规则——维度权重、阈值都来自实测反馈（详见下方「评分模型」）。

---

## 三条红线（开源版铁律）

1. **核心库不内置任何平台数据。** 包内仅附**虚构**示例数据供零配置试跑；真实数据由用户自行采集（可选用自带的扫榜采集器，见下方「扫榜采集」）。
2. **不提供「下载整本小说」能力。** MCP 只返回 `book_id` / `url`，让你自己去处理。
3. **MCP 对外投影不返回 `intro` 简介全文 / `cover` 版权图 URL**（书目只含：book_id、标题、作者、品类、在读、状态、章节数、url）。本地看板**点击书名可看简介**——渲染的是用户本地自有快照，按需单本拉取，不经仓库分发、不进 MCP。

---

## 快速开始（零配置）

### 1. 安装

```bash
git clone https://github.com/WindXRan/fanqie-radar.git
cd fanqie-radar
pip install .           # 需要 Python >= 3.10，零第三方依赖
```

不装包也能直接跑：`python -m fanqie_index.mcp_server`。

### 2. 直接用（什么都不用配）

**未配置数据目录时，自动落到包内示例数据**（虚构榜单，非真实数据）——装完就能跑通全部 7 个工具和看板：

```bash
fanqie-radar            # MCP stdio 服务，直接挂客户端
fanqie-radar-web        # 可视化看板，浏览器打开 http://127.0.0.1:8401
```

### 3. 换上你的真实数据

把你的榜单快照放进 `./data/` 目录（或任意目录，设 `FANQIE_INDEX_DATA_DIRS` 指过去）。命名规范见下方「数据格式规范」。

### 3.5. 扫榜采集（可选）

内置扫榜采集器，用 Playwright 无头浏览器从番茄小说公开榜单页面采集数据，保存为本地 JSON 快照。

**看板一键采集（推荐）**：打开看板 → 点击顶栏「🔍 扫榜」按钮 → 选择频道/榜单/上限/间隔 → 点「开始采集」。首次运行自动安装 Playwright + Chromium，全程无需终端。采集过程实时显示进度日志，完成后看板自动刷新。

**命令行采集**（进阶）：

```bash
pip install fanqie-radar[scrape]          # 安装采集依赖
fanqie-radar-scrape                      # 采集全部 4 个榜
fanqie-radar-scrape --gender female --rank read  # 只采集女频阅读榜
fanqie-radar-scrape --limit 30 --sleep 5  # 控制每分类上限和间隔
```

采集的数据自动保存到 `./data/` 目录。**合规设计**：固定延迟（默认 5s/分类）、User-Agent 轮换、只采集公开榜单信息、数据存本地不上传。

### 4. 挂到 MCP 客户端

**Claude Desktop**（`claude_desktop_config.json`）：

```json
{
  "mcpServers": {
    "fanqie-radar": {
      "command": "fanqie-radar"
    }
  }
}
```

零配置即可挂载（跑在示例数据上）；要分析自己的数据，加一个 env 指向快照目录：

```json
"env": { "FANQIE_INDEX_DATA_DIRS": "C:/path/to/your/data" }
```

**Cursor / 其他**：同样指向 `fanqie-radar` 命令（或 `python -m fanqie_index.mcp_server`）。多目录用 `;` 分隔（Windows）/ `:`（Linux/macOS）。

### 5. Agent Skill（WorkBuddy / Claude 等智能体一键接入）

本仓库自带 Agent Skill（`skills/fanqie-radar/SKILL.md`）：智能体用户把该目录装进技能库，即可让 AI 自动启动服务、调用 API/工具，**同样零配置**。

---

## 可视化看板（引流门面）

纯前端暗色玻璃风仪表盘，**零依赖、纯原生**（无 CDN、无框架）。把数据能力变成一眼能看懂的漂亮界面——开源引流的主战场。

```bash
fanqie-radar-web --data <你的数据目录> --port 8401
# 浏览器打开 http://127.0.0.1:8401（不传 --data 则自动用包内示例数据）
```

看板包含：

- **固定顶栏**：品牌 / 女频·男频·新书榜切换 / 快筛工具条 / 品类快跳条——整条 sticky 毛玻璃，下滑不消失，换榜筛选随时可用
- **书卡流**（主视图，全宽三列）：封面 / 书名 / 作者·品类 / 在读大字（量级分色）/ 徽章（完结·章节数·套路命中）/ 简介前两行；品类分组小节标题 + 骨架屏 + 级联入场
- **右侧抽屉**（顶栏按钮呼出，Esc/遮罩关闭）：
  - 📊 题材热度 —— 各品类在读量对比条
  - ⚡ 今日动静 —— 新上榜 / 掉出榜（对比同榜两份快照）
  - 🔥 热词榜 —— 点词筛同套路书
  - ★ 候选清单 —— 点 ☆ 收藏（localStorage 持久化），顶栏按钮带数量角标
- **人类动线**：点书名看完整简介 → 点热词筛同套路书 → 点题材热度条筛品类 → 收藏候选集中对比
- **广告位**：主区横幅 + 抽屉底部各一处，放一份 `web/ads.json` 即可自定义（仓库附示例）
- 无综合评分刷屏——评分模型在 MCP 工具 `fanqie_imitation_score` 里，看板只做「帮人扫榜」

![简介弹窗](docs/screenshot-modal.jpg)

![抽屉面板](docs/screenshot-drawer.jpg)

切换「女频/男频」「阅读榜/新书榜」即时重渲。`web/` 目录为静态资源，`src/fanqie_index/web.py` 为标准库 server（静态页 + `/api/*` 复用内核）。

## 数据格式规范（接入契约）

文件名：

```
fanqie_{gender}_{rank}_ranks_{YYYYMMDD}.json
  gender: female | male
  rank:   read(阅读榜) | new(新书榜) | peak(巅峰榜) | completed(完结池)
```

文件内容（两种都兼容）：

```json
{
  "date": "20260905",
  "rank_type": "女频阅读榜",
  "categories": [
    {"name": "豪门总裁", "books": [{ "title": "...", "author": "...", "reads": "24.1万",
      "intro": "（可选）...", "url": "https://fanqienovel.com/page/123", "status": "已完结",
      "chapters": 158, "bookid": "123" }]}
  ]
}
```

- `reads` 支持 `"24.1万"` / `"1.2亿"` / 整数。
- `bookid` 缺失时自动从 `url` 的 `/page/{id}` 提取——**全量书目都可被 book_id 寻址**。
- `intro` 选填：有它评分更准确（套路/金手指命中），没有给中性分。
- `chapters` 选填：章节数（番茄书籍页公开可获取），用于体量适配评分与看板徽章。
- 也兼容平铺格式 `{"books": [...], ...}`（每本自带 `category`）。

**可选：章节/状态缓存**（`<数据目录>/meta_cache.json`）——榜单快照通常不含章节/状态，
本仓库**不抓取**，由你自己的外部工具补全后放到数据目录即可，看板自动合并（mtime 热更新，改完即生效）：

```json
{ "<book_id>": { "chapters": 158, "status": "已完结" } }
```

快照缺字段时用缓存补，快照有值不覆盖。没有缓存文件看板照常工作（章节数显示 "—"）。

---

## 工具清单

| 工具 | 作用 |
|---|---|
| `fanqie_ranks` | 读取最新榜单（频道/榜型/品类过滤） |
| `fanqie_find` | 跨全部快照按书名/作者查找 → book_id |
| `fanqie_trend` | 多日趋势差分：新上榜 / 掉榜 / 排名变化 / 在读增长（需 ≥2 份同榜快照） |
| `fanqie_genre_heat` | 题材热度（按在读总量排序） |
| **`fanqie_imitation_score`** | **核心**：六维仿写选书评分（另支持男频连载母本评分 `serial=true`） |
| `fanqie_hotwords` | 书名热词频次 |
| `fanqie_stats` | 数据概览（快照数 / 书目数 / book_id 覆盖率） |

---

## 评分模型（六维 + 加成）

**完结短书（女频主体）六维权重：**

| 维度 | 权重 | 含义 |
|---|---|---|
| 完结度 | 20% | 已完结=100 / 连载中=40（可一次性拆全本） |
| 体量适配 | 20% | 90–220 章最优；<70 章弧线不足，>450 章强缩写丢尾 |
| 单本热度 | 15% | 在对数归一后的在读量级（避免头部吃光分数） |
| 题材吸量 | 15% | 所在类目的吸量指数（在数据驱动聚合的 heat 基础上） |
| 套路密度 | 15% | 简介命中的套路词数（骨架清晰度代理） |
| 金手指清晰 | 15% | 命中 1–2 种金手指=满分；0 种=不明；≥3 种=堆叠降分 |

**加成项（有则加，无则跳过）：** 持续在榜天数（≤+8，套路耐看）、新书榜命中（+6，近期起量）、跨榜（≥2 榜，+4）、巅峰榜（+8，平台月度精选，女频专属再 +4）。

**男频连载母本评分（`serial=true`）：** 维度换成 连载体量 25% / 在读 25% / 更新活跃 15% / 题材吸量 15% / 套路 10% / 金手指 10%——与女频「短完结」相反，母本追求 450 章+ 连载长书 + 日更活跃。

所有阈值来自实测（如「百万字长书不作仿写源」「≈220–450 章的连载体量最优」；历史字数阈值按 2250 字/章折算为章节数），详见 `src/fanqie_index/scoring.py` 内各函数 docstring 的调研出处。

---

## 开发

```bash
pip install -e ".[dev]"
pytest                      # 21 个测试
```

结构：

```
src/fanqie_index/
  schema.py      榜单快照：目录探测 / 元数据解析 / 书目归一 / 查找 / 统计
  scoring.py     六维评分 + 男频连载评分（词表 + 维度函数 + 加权）
  analysis.py    题材热度 / 跨榜强信号 / 书名热词 / 多日趋势差分
  mcp_server.py  stdio MCP 服务入口（手写 JSON-RPC，零第三方依赖）
  sample_data/   包内示例数据（虚构，零配置兜底）
examples/sample_data/   同款示例数据（仓库副本）
skills/fanqie-radar/    Agent Skill（智能体一键接入）
tests/                  pytest 冒烟测试
```

**调试 MCP：** 直接往 stdin 发 newline-delimited JSON-RPC：

```bash
python -c "
import subprocess,os,json
inp=[json.dumps({'jsonrpc':'2.0','id':1,'method':'initialize','params':{}}),
     json.dumps({'jsonrpc':'2.0','id':2,'method':'tools/list'})]
p=subprocess.Popen(['python','-m','fanqie_index.mcp_server'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,encoding='utf-8',env=os.environ)
print(p.communicate('\n'.join(inp)+'\n')[0])
"
```

---

## 免责声明

本项目仅提供数据**读取 / 分析 / 评分**的工具能力。数据由使用者自行负责采集与合规，须遵守相关平台的服务条款与所在地法律法规，**仅供个人学习与研究使用**。本仓库不对使用者采集、持有或使用数据的行为承担任何责任。

## License

MIT © 方寸写作 (FangCun Studio)
