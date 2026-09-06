# -*- coding: utf-8 -*-
"""fanqie-radar-skill-install 一键安装 Agent Skill 的测试。"""
import importlib
import tempfile
from pathlib import Path

import pytest

install_skill = importlib.import_module("fanqie_index.install_skill")


def test_list_skills_finds_bundled():
    skills = install_skill.list_skills()
    assert skills, "仓库内置 skills 不应为空"
    assert any(s.name == "fanqie-radar" for s in skills)


def test_skill_name_matches_dir():
    d = next(s for s in install_skill.list_skills() if s.name == "fanqie-radar")
    assert install_skill._skill_name(d) == "fanqie-radar"
    assert install_skill._valid_name("fanqie-radar")


def test_install_local_to_agents(tmp_path):
    d = next(s for s in install_skill.list_skills() if s.name == "fanqie-radar")
    ok, _ = install_skill.install(d, "claude-code", local=True, cwd=tmp_path)
    assert ok
    installed = tmp_path / ".claude" / "skills" / "fanqie-radar" / "SKILL.md"
    assert installed.is_file()


def test_install_all_clients(tmp_path):
    d = next(s for s in install_skill.list_skills() if s.name == "fanqie-radar")
    ok, msg = install_skill.install(d, "all", local=True, cwd=tmp_path)
    assert ok
    for agent in install_skill._CLIENTS:
        rel = install_skill._CLIENTS[agent]["home_rel"]
        assert (tmp_path / rel / "fanqie-radar" / "SKILL.md").is_file()


def test_install_overwrites_same_dir(tmp_path):
    d = next(s for s in install_skill.list_skills() if s.name == "fanqie-radar")
    install_skill.install(d, "trae", local=True, cwd=tmp_path)
    install_skill.install(d, "trae", local=True, cwd=tmp_path)  # 二次安装应覆盖不报错
    assert (tmp_path / ".trae-cn" / "skills" / "fanqie-radar" / "SKILL.md").is_file()