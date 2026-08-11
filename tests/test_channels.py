"""Tests for the Agent-Reach-inspired channels router (P8).

The new module is purely additive — these tests are *only* checks of
new behaviour, not regressions on existing modules.  They must pass
with the rest of the suite (38 modules, 258+ tests).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# Ensure repo root on path (matches the project's pytest.ini `pythonpath = .`)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── brain/channels.py — registry & probe ─────────────────────────────────

def test_channels_module_imports():
    from brain import channels
    assert hasattr(channels, "CHANNELS")
    assert hasattr(channels, "probe_all")
    assert hasattr(channels, "doctor_report")
    assert hasattr(channels, "list_channels")


def test_channels_registry_has_expected_channels():
    from brain.channels import CHANNELS
    # The four CryptoBrain channels
    assert set(CHANNELS.keys()) == {"cryptodada", "discord", "news", "llm"}


def test_channels_each_has_ordered_backends():
    from brain.channels import CHANNELS
    # The tail of every channel must be an "always-available" backend
    # so the engine is never blocked. We accept either the explicit
    # "none" sentinel or a domain-specific always-on fallback like
    # llm's "rule_based".
    ALWAYS_AVAILABLE_TAILS = {"none", "rule_based"}
    for name, ch in CHANNELS.items():
        assert ch.backends, f"{name} has no backends"
        assert ch.backends[-1].name in ALWAYS_AVAILABLE_TAILS, (
            f"{name} must end with an always-available backend; got {ch.backends[-1].name}"
        )
        assert ch.backends[-1].ok is True, (
            f"{name} tail backend must be ok=True so the channel is never down"
        )


def test_probe_all_isolates_exceptions(monkeypatch):
    """A broken probe in one channel must not crash probe_all()."""
    from brain import channels

    def boom():
        raise RuntimeError("simulated channel failure")

    monkeypatch.setattr(channels, "_probe_cryptodada_backends", boom)
    # probe_all should still return a dict, just with a 'down' cryptodada
    result = channels.probe_all()
    assert "cryptodada" in result
    assert result["cryptodada"].status in {"down", "degraded"}


def test_probe_all_picks_first_configured_and_ok_backend():
    from brain.channels import probe_all, _probe_news_backends
    # news is always fully configured; the first backend (rss_parallel) wins
    result = probe_all()
    assert result["news"].active == "rss_parallel"
    assert result["news"].status == "ok"


def test_llm_falls_back_to_rule_based_when_no_keys(monkeypatch):
    """With no API keys, llm.active should be the rule-based backend."""
    from brain import channels

    # Ensure no LLM keys are visible
    for var in ("OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(channels, "OPENAI_API_KEY", "")
    monkeypatch.setattr(channels, "GEMINI_API_KEY", "")
    monkeypatch.setattr(channels, "LLM_PROVIDER", "off")
    monkeypatch.setattr(channels, "OPENAI_BASE_URL", "https://api.openai.com/v1")

    result = channels.probe_all()
    assert result["llm"].active == "rule_based"
    assert result["llm"].status == "ok"


def test_discord_webhook_is_preferred_over_token(monkeypatch):
    """Webhook (safe outbound) is the first Discord backend."""
    from brain import channels

    monkeypatch.setattr(channels, "DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/x/y")
    monkeypatch.setattr(channels, "DISCORD_ANNOUNCE_WEBHOOK", "")
    monkeypatch.setattr(channels, "DISCORD_TOKEN", "")
    monkeypatch.setattr(channels, "DISCORD_CHANNEL_IDS", [])

    result = channels.probe_all()
    assert result["discord"].active == "webhook"
    assert result["discord"].status == "ok"


def test_discord_falls_back_to_none_without_anything(monkeypatch):
    from brain import channels

    monkeypatch.setattr(channels, "DISCORD_WEBHOOK_URL", "")
    monkeypatch.setattr(channels, "DISCORD_ANNOUNCE_WEBHOOK", "")
    monkeypatch.setattr(channels, "DISCORD_TOKEN", "")
    monkeypatch.setattr(channels, "DISCORD_CHANNEL_IDS", [])

    result = channels.probe_all()
    assert result["discord"].active == "none"
    assert result["discord"].status == "degraded"


def test_doctor_report_text_is_human_readable(monkeypatch):
    from brain import channels

    monkeypatch.setattr(channels, "DISCORD_WEBHOOK_URL", "")
    monkeypatch.setattr(channels, "DISCORD_TOKEN", "")
    monkeypatch.setattr(channels, "DISCORD_CHANNEL_IDS", [])
    monkeypatch.setattr(channels, "OPENAI_API_KEY", "")
    monkeypatch.setattr(channels, "GEMINI_API_KEY", "")
    monkeypatch.setattr(channels, "CRYPTODADA_BASE_URL", "")

    report = channels.doctor_report(as_json=False)
    assert isinstance(report, str)
    assert "CryptoBrain doctor report" in report
    assert "cryptodada" in report
    assert "discord" in report
    assert "news" in report
    assert "llm" in report


def test_doctor_report_json_is_machine_readable(monkeypatch):
    from brain import channels
    monkeypatch.setattr(channels, "DISCORD_WEBHOOK_URL", "")
    monkeypatch.setattr(channels, "DISCORD_TOKEN", "")
    monkeypatch.setattr(channels, "DISCORD_CHANNEL_IDS", [])
    monkeypatch.setattr(channels, "OPENAI_API_KEY", "")
    monkeypatch.setattr(channels, "GEMINI_API_KEY", "")
    monkeypatch.setattr(channels, "CRYPTODADA_BASE_URL", "")

    report = channels.doctor_report(as_json=True)
    assert isinstance(report, dict)
    assert "channels" in report
    assert set(report["channels"].keys()) == {"cryptodada", "discord", "news", "llm"}


def test_list_channels_returns_table_string():
    from brain.channels import list_channels
    out = list_channels(as_json=False)
    assert isinstance(out, str)
    assert "channel" in out  # the header


# ── SKILL.md — content contract ──────────────────────────────────────────

def test_skill_md_exists():
    skill = ROOT / "SKILL.md"
    assert skill.exists(), "SKILL.md must exist at repo root"


def test_skill_md_is_brief():
    """The Agent-Reach SKILL.md pattern is one short file. <300 lines."""
    skill = ROOT / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    n_lines = len(text.splitlines())
    assert n_lines < 300, f"SKILL.md is {n_lines} lines; keep it short (Agent-Reach pattern)"


def test_skill_md_lists_the_core_tools():
    skill = ROOT / "SKILL.md"
    text = skill.read_text(encoding="utf-8").lower()
    for tool in ("scan", "intelligence", "brief", "ask", "postreview",
                 "health", "risk", "doctor", "skill"):
        assert tool in text, f"SKILL.md must mention the '{tool}' tool"


def test_skill_md_states_safety_guarantee():
    skill = ROOT / "SKILL.md"
    text = skill.read_text(encoding="utf-8").lower()
    # Must include a "never place an order" or equivalent safety statement
    assert "never" in text and ("order" in text or "execution" in text or "trade" in text)


def test_skill_md_requires_citations_for_ask():
    skill = ROOT / "SKILL.md"
    text = skill.read_text(encoding="utf-8").lower()
    assert "cited" in text or "citation" in text, (
        "SKILL.md must document the citation pattern that `ask` produces"
    )


# ── main.py — new CLI subcommands (P7) ───────────────────────────────────

def test_main_help_mentions_doctor_channels_skill():
    """`python main.py --help` should list the new subcommands."""
    import subprocess
    res = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "--help"],
        capture_output=True, text=True, timeout=20, cwd=str(ROOT),
    )
    assert res.returncode == 0, res.stderr
    out = res.stdout.lower()
    for cmd in ("doctor", "channels", "skill"):
        assert cmd in out, f"`main.py --help` should list the {cmd!r} subcommand"


def test_main_doctor_text_runs(capsys):
    """`python main.py doctor` should exit 0 and produce a report."""
    import subprocess
    res = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "doctor"],
        capture_output=True, text=True, timeout=30, cwd=str(ROOT),
    )
    assert res.returncode == 0, res.stderr
    assert "doctor" in res.stdout.lower() or "channel" in res.stdout.lower()


def test_main_doctor_json_is_valid(capsys):
    import subprocess
    res = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "doctor", "--json"],
        capture_output=True, text=True, timeout=30, cwd=str(ROOT),
    )
    assert res.returncode == 0, res.stderr
    parsed = json.loads(res.stdout)
    assert "channels" in parsed


def test_main_channels_runs():
    import subprocess
    res = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "channels"],
        capture_output=True, text=True, timeout=20, cwd=str(ROOT),
    )
    assert res.returncode == 0, res.stderr
    out = res.stdout.lower()
    for ch in ("cryptodada", "discord", "news", "llm"):
        assert ch in out, f"`channels` output should mention {ch}"


def test_main_skill_print_runs():
    """`python main.py skill` defaults to printing the SKILL.md to stdout."""
    import subprocess
    res = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "skill"],
        capture_output=True, text=True, timeout=20, cwd=str(ROOT),
    )
    assert res.returncode == 0, res.stderr
    # The SKILL.md frontmatter should be in the output
    assert "name: cryptobrain" in res.stdout


def test_main_skill_install_requires_system(tmp_path, monkeypatch):
    """Without --system, --install must refuse (no $HOME writes)."""
    import subprocess
    res = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "skill", "--install"],
        capture_output=True, text=True, timeout=20, cwd=str(ROOT),
    )
    # Exit 2 = "refused without --system"
    assert res.returncode == 2, (res.stdout, res.stderr)
    assert "without" in res.stderr.lower() and "--system" in res.stderr


def test_main_skill_install_dry_run_does_not_write(tmp_path, monkeypatch):
    """--install --dry-run --system must NOT touch the filesystem."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    import subprocess
    res = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "skill",
         "--install", "--system", "--dry-run"],
        capture_output=True, text=True, timeout=20, cwd=str(ROOT),
    )
    assert res.returncode == 0, (res.stdout, res.stderr)
    assert "dry-run" in res.stdout.lower()
    # The home dir must remain untouched
    assert not (fake_home / ".claude").exists()


def test_main_skill_install_writes_to_target_dir(tmp_path, monkeypatch):
    """--install --system --target-dir <tmp> must write the SKILL there."""
    target = tmp_path / "my_skills" / "cryptobrain"

    import subprocess
    res = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "skill",
         "--install", "--system", "--target-dir", str(target)],
        capture_output=True, text=True, timeout=20, cwd=str(ROOT),
    )
    assert res.returncode == 0, (res.stdout, res.stderr)
    written = target / "SKILL.md"
    assert written.exists(), f"SKILL.md not written at {written}"
    text = written.read_text(encoding="utf-8")
    assert "name: cryptobrain" in text


def test_main_skill_uninstall_removes_written_file(tmp_path, monkeypatch):
    """--uninstall must remove what --install wrote."""
    target = tmp_path / "my_skills" / "cryptobrain"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("placeholder", encoding="utf-8")

    import subprocess
    res = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "skill",
         "--uninstall", "--system", "--target-dir", str(target)],
        capture_output=True, text=True, timeout=20, cwd=str(ROOT),
    )
    assert res.returncode == 0, (res.stdout, res.stderr)
    assert not (target / "SKILL.md").exists()


# ── Roadmap document ─────────────────────────────────────────────────────

def test_roadmap_exists_and_mentions_phases():
    doc = ROOT / "ROADMAP_AGENT_REACH_UPGRADE.md"
    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for ph in ("P7", "P8", "P9"):
        assert ph in text, f"roadmap must mention phase {ph}"
    assert "Out of scope" in text or "not copying" in text.lower()


def test_ai_anatomy_roadmap_mentions_p7_p9():
    doc = ROOT / "AI_ANATOMY_ROADMAP.md"
    text = doc.read_text(encoding="utf-8")
    for ph in ("P7", "P8", "P9"):
        assert ph in text, f"AI_ANATOMY_ROADMAP must mention {ph}"
