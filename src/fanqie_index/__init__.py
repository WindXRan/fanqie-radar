# -*- coding: utf-8 -*-
"""fanqie-radar（番茄雷达）：番茄小说榜单数据 + 扫榜选书工作台 + MCP 服务（零配置/零爬虫/零第三方依赖）。

子模块：
  schema   榜单快照：目录探测 / 元数据解析 / 书目归一 / 查找 / 统计
  scoring  仿写选书六维评分（完结短书）+ 男频连载母本评分
  analysis 题材热度 / 跨榜强信号 / 书名热词 / 多日趋势差分
  mcp_server  stdio MCP 服务入口（python -m fanqie_index.mcp_server）
"""
from . import schema, scoring, analysis, mcp_server

__version__ = "0.2.0"

__all__ = ["schema", "scoring", "analysis", "mcp_server"]
