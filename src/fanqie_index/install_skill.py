# -*- coding: utf-8 -*-
"""一键安装本项目自带 Agent Skill（skills/ 目录）到各 AI 客户端的 skills 目录。

零第三方依赖（纯标准库），跨平台（Windows / macOS / Linux）。

支持目标客户端（统一识别 SKILL.md，仅安装目录不同）：

    claude-code   Claude Code          ~/.claude/skills
    cursor        Cursor               ~/.cursor/skills  （推荐 .agents/skills）
    trae          Trae / Trae CN       %USERPROFILE%/.trae-cn/skills
    copilot       GitHub Copilot       ~/.copilot/skills
    cline         Cline                ~/.cline/skills
    gemini        Gemini CLI           ~/.gemini/skills
    codex         Codex                ~/.codex/skills
    opencode      OpenCode             ~/.config/opencode/skills
    all           以上全部

安装范围：
    --global（默认，全局到用户根目录，多用）
    --local（仅当前项目的 .<agent>/skills，随仓库走）

使用：
    fanqie-radar-skill-install                      # 交互式：选客户端+范围
    fanqie-radar-skill-install --agent all --global # 一键装到所有客户端全局
    fanqie-radar-skill-install --agent claude-code --local
    fanqie-radar-skill-install --list               # 列出仓库内置 skills
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

# ── 各客户端：相对用户根目录的全局 skills 路径 ──────────────────
# 安装范围 global → ~/<rel>/<skill>；local → <cwd>/<rel>/<skill>
_CLIENTS = {
    "claude-code": {"home_rel": ".claude/skills"},
    "cursor":      {"home_rel": ".cursor/skills"},
    "trae":        {"home_rel": ".trae-cn/skills"},
    "copilot":     {"home_rel": ".copilot/skills"},
    "cline":       {"home_rel": ".cline/skills"},
    "gemini":      {"home_rel": ".gemini/skills"},
    "codex":       {"home_rel": ".codex/skills"},
    "opencode":    {"home_rel": ".config/opencode/skills"},
}


def _repo_skills_dir() -> Path:
    """仓库 bundled skills 目录（skills/，多个 SKILL.md）。"""
    # 本文件：<repo>/src/fanqie_index/install_skill.py → 上溯 3 级到 <repo>
    here = Path(__file__).resolve()
    return here.parent.parent.parent / "skills"


def list_skills() -> list[Path]:
    """返回仓库内所有含 SKILL.md 的 skill 目录。"""
    skills_root = _repo_skills_dir()
    out = []
    if skills_root.is_dir():
        for d in skills_root.iterdir():
            if d.is_dir() and (d / "SKILL.md").is_file():
                out.append(d)
    return sorted(out)


def _skill_name(skill_dir: Path) -> str:
    """从 SKILL.md frontmatter 读 name；读不到退回目录名。"""
    try:
        text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    except Exception:
        return skill_dir.name
    m = re.search(r"^name:\s*([\w-]+)", text, re.MULTILINE)
    return m.group(1).strip() if m else skill_dir.name


def _valid_name(name: str) -> bool:
    """Agent Skills spec：小写字母/数字/连字符，≤64，不以 - 开头结尾。"""
    if not name or len(name) > 64 or name.startswith("-") or name.endswith("-"):
        return False
    return bool(re.fullmatch(r"[a-z0-9-]+", name))


def _dest(skill_dir: Path, agent: str, local: bool, cwd: Path | None = None) -> Path:
    """计算 skill 安装目标目录。local=True 装当前项目，否则全局用户根目录。"""
    root = (cwd or Path.cwd()) if local else Path.home()
    rel = _CLIENTS[agent]["home_rel"]
    return root / rel / skill_dir.name


def _copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def install(skill_dir: Path, agent: str, local: bool = False, cwd: Path | None = None) -> tuple[bool, str]:
    """安装单个 skill 到指定客户端。返回 (是否成功, 说明文字)。"""
    name = _skill_name(skill_dir)
    if not _valid_name(name):
        return False, f"跳过 {skill_dir.name}：SKILL.md name「{name}」非法（须小写字母/数字/连字符，≤64，且与目录名一致）"
    if name != skill_dir.name:
        return False, f"跳过 {skill_dir.name}：SKILL.md name「{name}」与目录名不一致"

    if agent == "all":
        ok, msgs = True, []
        for a in _CLIENTS:
            success, msg = install(skill_dir, a, local, cwd)
            ok = ok and success
            msgs.append(msg)
        return ok, "\n".join(msgs)

    dst = _dest(skill_dir, agent, local, cwd)
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        _copy_tree(skill_dir, dst)
    except Exception as e:
        return False, f"✗ {agent}: 安装失败 → {dst}\n    {type(e).__name__}: {e}"
    return True, f"✓ {agent}: 已安装 → {dst}"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(
        prog="fanqie-radar-skill-install",
        description="一键安装番茄雷达自带 Agent Skill 到各 AI 客户端（Claude Code/Cursor/Trae/Copilot/Cline/Gemini/Codex/OpenCode）",
    )
    ap.add_argument("--agent", default="",
                    help="目标客户端：claude-code|cursor|trae|copilot|cline|gemini|codex|opencode|all（默认交互选择）")
    ap.add_argument("--global", dest="is_global", action="store_true", help="安装到用户全局目录（默认）")
    ap.add_argument("--local", dest="is_local", action="store_true", help="仅安装到当前项目（.<agent>/skills）")
    ap.add_argument("--list", action="store_true", help="只列出仓库内置 skills 并退出")
    a = ap.parse_args(argv)

    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    skills = list_skills()
    if not skills:
        print("仓库中未找到自带 skills（应位于 <repo>/skills/<name>/SKILL.md）")
        return
    if a.list:
        print("仓库内置 skills：")
        for s in skills:
            print(f"  - {_skill_name(s)}  ({s.parent.parent.name}/{s.name})")
        return

    # 选 skill
    if len(skills) == 1:
        chosen = skills[0]
    else:
        print("选择要安装的 skill：")
        for i, s in enumerate(skills, 1):
            print(f"  {i}. {_skill_name(s)}")
        try:
            pick = int(input("编号: ").strip())
            chosen = skills[pick - 1]
        except Exception:
            print("无效输入，退出。")
            return

    # 选客户端
    agent = a.agent or input(
        "目标客户端 [claude-code/cursor/trae/copilot/cline/gemini/codex/opencode/all]: ").strip()
    if agent not in _CLIENTS and agent != "all":
        print(f"未知客户端「{agent}」。可用：{', '.join(list(_CLIENTS) + ['all'])}")
        return

    # 范围
    local = a.is_local
    if not a.is_global and not a.is_local:
        local = input("安装范围 [global/local]，默认 global: ").strip() == "local"

    ok, msg = install(chosen, agent, local)
    print(msg)
    if not ok:
        sys.exit(1)
    print("\n安装完成。请重启你的 AI 客户端后生效。")


if __name__ == "__main__":
    main()