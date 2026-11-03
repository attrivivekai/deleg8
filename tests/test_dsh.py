"""DeepSeek Harness adapter, exercised against a fake `dsh` executable (no model needed)."""

import json
import stat

import yaml

from deleg8.agents.base import make_harness
from deleg8.config import load_config

FAKE_DSH = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
record = {"args": args, "mode": os.environ.get("DSH_PERMISSION_MODE"), "home": os.environ.get("DSH_HOME"),
          "key": os.environ.get("LOCAL_KEY"), "cwd": os.getcwd()}
open(os.environ["FAKE_DSH_RECORD"], "w").write(json.dumps(record))
print("thinking...", file=sys.stderr)
print('Done. Here is the result:\\n```json\\n{"status": "done", "summary": "ok"}\\n```')
"""


def make_cfg(tmp_path, cfg):
    fake = tmp_path / "fake-dsh"
    fake.write_text(FAKE_DSH)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    (tmp_path / "model.env").write_text("export LOCAL_KEY=sekrit\n")
    home = tmp_path / "dsh-home"
    home.mkdir()
    (home / "settings.yaml").write_text(
        yaml.safe_dump(
            {
                "agent-default-model": {"provider": "local", "model": "qwen-coder"},
                "llm-pi-ai": {
                    "providers": {
                        "local": {
                            "baseURL": "http://127.0.0.1:8080/v1",
                            "models": [{"id": "qwen-coder", "contextWindow": 65536}],
                        }
                    }
                },
            }
        )
    )
    raw = yaml.safe_load(cfg.path.read_text())
    preset = {
        "provider": "dsh",
        "command": [str(fake)],
        "env_file": str(tmp_path / "model.env"),
        "env": {"DSH_HOME": str(home), "FAKE_DSH_RECORD": str(tmp_path / "record.json")},
    }
    raw["harnesses"] = {"dsh": {"coding_agent": {**preset, "permission_mode": "danger-full-access"}, "brain": preset}}
    cfg.path.write_text(yaml.safe_dump(raw))
    return load_config(cfg.path, harness="dsh")


def test_dsh_think_is_read_only_and_mounts_mcp(tmp_path, cfg):
    c = make_cfg(tmp_path, cfg)
    res = make_harness(c, "brain").think("plan it", {"type": "object"}, tmp_path, "plan-1")
    rec = json.loads((tmp_path / "record.json").read_text())
    assert res.ok and res.data == {"status": "done", "summary": "ok"} and res.cost_usd == 0.0
    assert rec["mode"] == "read-only"
    assert rec["key"] == "sekrit" and rec["home"].endswith("dsh-home")
    assert rec["args"][rec["args"].index("--profile") + 1] == "headless"
    overlay = yaml.safe_load(open(rec["args"][rec["args"].index("--patch") + 1]))
    mcp = overlay[1]["insert"][0]
    assert mcp["name"] == "@deepseek-ai/dsh-mcp-client" and mcp["config"]["serverName"] == "deleg8"
    assert "READ-ONLY MODE" in rec["args"][-1]


def test_dsh_work_uses_configured_permission_mode(tmp_path, cfg):
    c = make_cfg(tmp_path, cfg)
    res = make_harness(c, "coding").work("code it", {"type": "object"}, tmp_path, "work-1")
    rec = json.loads((tmp_path / "record.json").read_text())
    assert res.ok and rec["mode"] == "danger-full-access"


def test_dsh_model_info_reads_settings(tmp_path, cfg):
    info = make_harness(make_cfg(tmp_path, cfg), "coding").model_info()
    assert info["model"] == "qwen-coder" and info["context_window"] == 65536


def test_default_config_unaffected_by_presets(tmp_path, cfg):
    make_cfg(tmp_path, cfg)
    assert load_config(cfg.path).coding_agent.provider == "claude_code"
