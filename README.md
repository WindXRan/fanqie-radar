# fanqie-index-mcp

> 番茄小说榜单「阅读 + 仿写选书评分」MCP 服务。零爬虫、零第三方运行时依赖，纯标准库。

在 Claude / Cursor / 任意 MCP 客户端里直接问「现在女频什么火」「这本适合仿写吗」「豪门总裁赛道热度如何」，它就答。

![看板](docs/screenshot.jpg)

---

## 它解决什么

网文作者/AI 写作从业者天天要回答三个问题：**现在什么题材火？哪本书适合仿？为什么？**

市面上番茄榜单爬虫一大堆，但爬完就扔给你一堆书名。真正稀缺的是**选书判断力**——这本能不能仿、仿出来质量天花板在哪。本项目把方寸写作跑了真金白银验证过的**六维仿写选书评分模型**开源出来，并包成 MCP 服务，让你的 AI 助手直接具备这套判断力。

### 差异化（为什么值得装）

| 能力 | 普通榜单爬虫 | 本仓库 |
|---|---|---|
| 榜单数据 | ✅ | ✅（自备快照） |
| 题材热度聚合 | 偶尔 | ✅ |
| 跨榜强信号（新书即爆款） | ❌ | ✅ |
| 多日趋势差分 | ❌ | ✅ |
| **仿写适合度评分** | ❌ | ✅ **六维 + 加成，数据驱动** |
| 接入 AI 助手（MCP） | ❌ | ✅ |

评分模型是核心资产，不是拍脑袋的硬规则——维度权重、阈值都来自实测反馈（详见下方「评分模型」）。

---

## 三条红线（开源版铁律）

1. **不抓取、不内置任何平台数据。** 本仓库零爬虫代码、零版权数据。数据是**你自己负责采集**的本地快照。
2. **不提供「下载整本小说」能力。** MCP 只返回 `book_id` / `url`，让你自己去处理。
3. **MCP 对外投影不返回 `intro` 简介全文 / `cover` 版权图 URL**（书目只含：book_id、标题、作者、品类、在读、状态、字数、url）。本地看板**点击书名可看简介**——渲染的是用户本地自有快照，按需单本拉取，不经仓库分发、不进 MCP。

---

## 快速开始

### 1. 安装

```bash
git clone <本仓库地址>
cd fanqie-index-mcp
pip install -e .        # 需要 Python >= 3.10
```

装完后有 `fanqie-index` 命令，等价于 `python -m fanqie_index.mcp_server`。

### 2. 准备数据

把你的榜单快照放到一个目录（**不进 git**，`.gitignore` 已排除 `data/`）。文件命名遵循下方规范：

```
fanqie_female_read_ranks_20260905.json
fanqie_female_new_ranks_20260905.json
fanqie_male_read_ranks_20260905.json
...
```

仓库 `examples/sample_data/` 里有一份**虚构的**示例数据（非真实榜单），仅供跑通流程。

### 3. 挂到 MCP 客户端

**Claude Desktop**（`claude_desktop_config.json`）：

```json
{
  "mcpServers": {
    "fanqie-index": {
      "command": "fanqie-index",
      "env": {
        "FANQIE_INDEX_DATA_DIRS": "C:/path/to/your/data"
      }
    }
  }
}
```

**Cursor / 其他**：同样指向 `fanqie-index` 命令（或 `python -m fanqie_index.mcp_server`），并设 `FANQIE_INDEX_DATA_DIRS` 环境变量。

数据目录也可在运行时指定：多目录用 `;` 分隔（Windows）/ `:`（Linux/macOS）：

```bash
FANQIE_INDEX_DATA_DIRS="C:/data/a;C:/data/b" fanqie-index
```

### 4. 直接玩（不挂客户端）

```bash
FANQIE_INDEX_DATA_DIRS=examples/sample_data python -m fanqie_index.mcp_server
# 然后按 JSON-RPC 协议发 stdin 行（见下方「调试」）
```

---

## 可视化看板（引流门面）

纯前端暗色玻璃风仪表盘，**零依赖、纯原生**（无 CDN、无框架）。把数据能力变成一眼能看懂的漂亮界面——开源引流的主战场。

```bash
fanqie-index-web --data <你的数据目录> --port 8401
# 浏览器打开 http://127.0.0.1:8401
```

> 想先看看长什么样？用仓库自带的虚构示例数据：
> ```bash
> fanqie-index-web --data examples/sample_data --port 8401
> ```

看板包含：

- **KPI 条**：快照数 / 书目数 / 最高分书 / 最强吸量题材
- **题材热度**：SVG 渐变条形图（按在读总量）
- **仿写选书评分 Top**：卡片网格，每卡含**封面** + 分数环 + 六维小条（完结/体量/热度/吸量/套路/金指）+ 套路/金手指命中标签
- **趋势差分**：新上榜 / 掉出榜单 两列（需 ≥2 份同榜快照）
- **书名热词**：套路词频标签云
- **榜单明细**：封面 / 书名 / 作者 / 品类 / 在读 / 字数 / 评分
- **点击书名看详情**：任意书名（评分卡或明细表）点击弹出单本详情——**封面、简介全文、字数、连载状态**、作者、品类、在读、榜单位次、番茄原链、book_id

![简介弹窗](docs/screenshot-modal.jpg)

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
      "words": 356000, "bookid": "123" }]}
  ]
}
```

- `reads` 支持 `"24.1万"` / `"1.2亿"` / 整数。
- `bookid` 缺失时自动从 `url` 的 `/page/{id}` 提取——**全量书目都可被 book_id 寻址**。
- `intro` 选填：有它评分更准确（套路/金手指命中），没有给中性分。
- 也兼容平铺格式 `{"books": [...], ...}`（每本自带 `category`）。

**可选：字数/状态缓存**（`<数据目录>/meta_cache.json`）——榜单快照通常不含字数/状态，
本仓库**不抓取**，由你自己的外部工具补全后放到数据目录即可，看板自动合并（mtime 热更新，改完即生效）：

```json
{ "<book_id>": { "words": 356000, "status": "已完结", "chapters": 158 } }
```

快照缺字段时用缓存补，快照有值不覆盖。没有缓存文件看板照常工作（字数显示 "—"）。

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
| 体量适配 | 20% | 20–50 万字最优；<15 万弧线不足，>100 万强缩写丢尾 |
| 单本热度 | 15% | 在对数归一后的在读量级（避免头部吃光分数） |
| 题材吸量 | 15% | 所在类目的吸量指数（在数据驱动聚合的 heat 基础上） |
| 套路密度 | 15% | 简介命中的套路词数（骨架清晰度代理） |
| 金手指清晰 | 15% | 命中 1–2 种金手指=满分；0 种=不明；≥3 种=堆叠降分 |

**加成项（有则加，无则跳过）：** 持续在榜天数（≤+8，套路耐看）、新书榜命中（+6，近期起量）、跨榜（≥2 榜，+4）、巅峰榜（+8，平台月度精选，女频专属再 +4）。

**男频连载母本评分（`serial=true`）：** 维度换成 连载体量 25% / 在读 25% / 更新活跃 15% / 题材吸量 15% / 套路 10% / 金手指 10%——与女频「短完结」相反，母本追求百万字级连载长书 + 日更活跃。

所有阈值来自实测（如「百万字长书不作仿写源」「50 万–100 万字的连载体量最优」），详见 `src/fanqie_index/scoring.py` 内各函数 docstring 的调研出处。

---

## 开发

```bash
pip install -e ".[dev]"
pytest                      # 用 examples/sample_data 跑 11 个冒烟测试
```

结构：

```
src/fanqie_index/
  schema.py      榜单快照：目录探测 / 元数据解析 / 书目归一 / 查找 / 统计
  scoring.py     六维评分 + 男频连载评分（词表 + 维度函数 + 加权）
  analysis.py    题材热度 / 跨榜强信号 / 书名热词 / 多日趋势差分
  mcp_server.py  stdio MCP 服务入口（手写 JSON-RPC，零第三方依赖）
examples/sample_data/   合成示例数据（虚构，非真实榜单）
tests/                  pytest 冒烟测试
```

**调试 MCP：** 直接往 stdin 发 newline-delimited JSON-RPC：

```bash
FANQIE_INDEX_DATA_DIRS=examples/sample_data python -c "
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
