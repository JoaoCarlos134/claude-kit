"""Tests for model_router.py (UserPromptSubmit) and model_state.py, with fake transcripts."""

import json
import time

import pytest
from conftest import assistant, run_hook, user, write_transcript

import model_router
import model_state


@pytest.mark.parametrize("prompt, tier", [
    ("rename the variable foo to bar in all files", "chore"),
    ("fix the typo in the README", "chore"),
    ("traduza o README para o inglês", "chore"),
    ("convert this table to csv please", "chore"),
    ("fix the failing test in parser.py and add a unit test", "standard"),
    ("corrija o bug no script de coleta", "standard"),
    ("design the architecture for the new forecasting pipeline", "deep"),
    ("revise a metodologia de previsão e verifique vazamento de dados", "deep"),
    ("find the root cause of this intermittent failure", "deep"),
    ("is this result statistically significant?", "deep"),
    ("can you add a date filter to the Streamlit page?", "standard"),
])
def test_classify(prompt, tier):
    assert model_router.classify(prompt)[0] == tier


@pytest.mark.parametrize("prompt", [
    "ok do it",
    "yes",
    "/model opus",
    "<side-sessions-event>a session finished: refactor the whole codebase</side-sessions-event>",
    '<pasted_content id="x">design the architecture of everything</pasted_content> thanks',
    "add a rule that by the end of session it gets merged",
])
def test_classify_stays_silent_when_unclear(prompt):
    assert model_router.classify(prompt)[0] is None


@pytest.mark.parametrize("prompt", [  # the reviewer's false positives at an Opus default
    "what is the best way to structure the forecasting model for the prosumer data?",
    "o que é overfitting e como evito isso no meu modelo de previsão?",
    "why did you choose LightGBM over the persistence baseline here?",
    "can you explain what this function does?",
    "where is the config loaded?",
    "what does this error mean in the CI log?",
    "por que o teste está falhando só no Windows?",
])
def test_questions_and_refactors_get_no_label(prompt):
    assert model_router.classify(prompt)[0] is None


def test_refactor_with_convert_is_not_a_chore():
    # 0.2.0 kept this silent; the classifier calls it standard, which a reviewer accepts too
    assert model_router.classify(
        "convert the training loop to use the new data module and make sure the tests still pass")[0] != "chore"


def test_long_prompt_is_not_a_chore():
    assert model_router.classify("rename " + "word " * 100)[0] is None


@pytest.mark.parametrize("model, expected", [
    ("claude-opus-5-5", "Opus 5.5"), ("claude-sonnet-5", "Sonnet 5"),
    ("claude-haiku-4-5-20251001", "Haiku 4.5"), ("opus", "Opus"), ("claude-mythos-5-2", "Mythos 5.2"),
])
def test_display(model, expected):
    assert model_state.display(model) == expected


def test_last_turn_skips_subagents_and_synthetic(tmp_path):
    path = write_transcript(tmp_path / "t.jsonl", [
        assistant(model="claude-sonnet-5-5", effort="medium", read=10_000),
        user("next"),
        assistant(model="claude-opus-5-5", effort="xhigh", fresh=10, read=90_000, written=10_000, output=500),
        assistant(model="claude-haiku-5-5", sidechain=True),
        {"type": "assistant", "message": {"model": "<synthetic>", "usage": {"input_tokens": 0}}},
    ])
    turn = model_state.last_turn(path)
    assert turn["model"] == "claude-opus-5-5"
    assert turn["effort"] == "xhigh"
    assert turn["context_tokens"] == 100_510
    assert turn["cache_hit_pct"] == 90
    assert turn["ttl"] == "1h"


def test_switch_cost_uses_new_input_price_and_ttl():
    assert model_state.switch_cost(1_000_000, "sonnet", "1h") == pytest.approx(4.0)
    assert model_state.switch_cost(50_000, "haiku", "5m") == pytest.approx(0.00625)
    # Haiku 5.5 bills prompts over 100K at $0.50/M, not $0.10/M
    assert model_state.switch_cost(434_888, "haiku", "1h") == pytest.approx(0.434888)


def payload(tmp_path, prompt, rows=None, effort="xhigh"):
    data = {"session_id": "s1", "prompt": prompt, "cwd": str(tmp_path), "effort": {"level": effort}}
    if rows is not None:
        data["transcript_path"] = str(write_transcript(tmp_path / "t.jsonl", rows))
    return data


def env(tmp_path):
    return {"CLAUDE_KIT_STATE_DIR": str(tmp_path / "state"), "CLAUDE_CONFIG_DIR": str(tmp_path / "cfg")}


def test_chore_on_opus_routes_to_haiku_worker_and_tells_user_once(tmp_path):
    rows = [assistant(model="claude-opus-5-5", effort="xhigh")]
    code, out, _ = run_hook("model_router.py", payload(tmp_path, "rename foo to bar everywhere", rows),
                            env=env(tmp_path))
    assert code == 0
    assert "haiku-worker" in out["systemMessage"] and "Opus 5.5" in out["systemMessage"]
    assert "keeps the cache" in out["systemMessage"]
    assert "joao-kit:haiku-worker" in out["hookSpecificOutput"]["additionalContext"]
    _, again, _ = run_hook("model_router.py", payload(tmp_path, "rename baz to qux too", rows),
                           env=env(tmp_path))
    assert "systemMessage" not in again  # the user saw it already
    assert "joao-kit:haiku-worker" in again["hookSpecificOutput"]["additionalContext"]


def test_user_hint_comes_back_after_repeat_after_prompts(tmp_path):
    rows = [assistant(model="claude-opus-5-5", effort="high")]
    shown = []
    for i in range(model_router.REPEAT_AFTER + 1):
        _, out, _ = run_hook("model_router.py", payload(tmp_path, f"rename item{i} to thing{i}", rows, "high"),
                             env=env(tmp_path))
        shown.append("systemMessage" in out)
    assert shown[0] and not any(shown[1:-1]) and shown[-1]


def test_bulky_chore_on_default_sonnet_goes_to_haiku_small_one_stays(tmp_path):
    big = [assistant(model="claude-sonnet-5-5", effort="medium", read=120_000)]
    _, out, _ = run_hook("model_router.py", payload(tmp_path, "rename foo to bar everywhere", big, "medium"),
                         env=env(tmp_path))
    assert "haiku-worker" in out["systemMessage"] and "/effort" not in out["systemMessage"]
    assert "joao-kit:haiku-worker" in out["hookSpecificOutput"]["additionalContext"]
    small = [assistant(model="claude-sonnet-5-5", effort="medium", read=8_000, written=1_000)]
    code, out, _ = run_hook("model_router.py", payload(tmp_path, "rename foo to bar here", small, "medium"),
                            env={**env(tmp_path), "CLAUDE_KIT_STATE_DIR": str(tmp_path / "state2")})
    assert code == 0 and out is None  # the default setup fits a small chore


def test_chore_at_effort_low_does_not_suggest_effort_low(tmp_path):
    rows = [assistant(model="claude-opus-5-5", effort="low")]
    _, out, _ = run_hook("model_router.py", payload(tmp_path, "rename foo to bar everywhere", rows, "low"),
                         env=env(tmp_path))
    assert "haiku-worker" in out["systemMessage"] and "/effort low" not in out["systemMessage"]


def test_deep_on_sonnet_suggests_opus_thinker_with_switch_cost(tmp_path):
    rows = [assistant(model="claude-sonnet-5-5", effort="medium", read=200_000)]
    _, out, _ = run_hook("model_router.py",
                         payload(tmp_path, "check the methodology for data leakage", rows, "medium"),
                         env=env(tmp_path))
    assert "opus-thinker" in out["systemMessage"]
    assert "$" in out["systemMessage"]
    assert "joao-kit:opus-thinker" in out["hookSpecificOutput"]["additionalContext"]


def test_fitting_setup_is_silent(tmp_path):
    rows = [assistant(model="claude-opus-5-5", effort="high")]
    code, out, _ = run_hook("model_router.py",
                            payload(tmp_path, "design the architecture of the sync layer", rows, "high"),
                            env=env(tmp_path))
    assert code == 0 and out is None


def test_first_prompt_with_known_model_says_switch_is_free(tmp_path):
    run_hook("model_router.py", {"session_id": "s1", "model": "claude-sonnet-5-5"}, "session-start",
             env=env(tmp_path))
    _, out, _ = run_hook("model_router.py", payload(tmp_path, "plan the migration of the database", None,
                                                    "medium"), env=env(tmp_path))
    assert "free now" in out["systemMessage"]


def test_first_prompt_with_unknown_model_does_not_guess_from_settings(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "settings.json").write_text(json.dumps({"model": "opus"}), encoding="utf-8")
    code, out, _ = run_hook("model_router.py", payload(tmp_path, "rename foo to bar everywhere", None),
                            env=env(tmp_path))
    assert code == 0 and out is None
    _, out, _ = run_hook("model_router.py", payload(tmp_path, "rename foo to bar everywhere", None),
                         env={**env(tmp_path), "ANTHROPIC_MODEL": "claude-opus-5-5"})
    assert "haiku-worker" in out["systemMessage"]


def test_session_start_model_is_used_on_first_prompt(tmp_path):
    run_hook("model_router.py", {"session_id": "s1", "model": "claude-haiku-5-5"}, "session-start",
             env=env(tmp_path))
    _, out, _ = run_hook("model_router.py", payload(tmp_path, "find the root cause of the flaky sync", None,
                                                    "medium"), env=env(tmp_path))
    assert "Haiku 5.5" in out["systemMessage"] and "opus-thinker" in out["systemMessage"]


def test_model_switch_after_last_response_wins_over_transcript(tmp_path):
    rows = [assistant(model="claude-opus-5-5", effort="high", timestamp="2026-01-01T00:00:00.000Z")]
    run_hook("model_router.py", {"session_id": "s1", "to_model": "claude-sonnet-5-5"}, "model-switch",
             env=env(tmp_path))
    _, out, _ = run_hook("model_router.py",
                         payload(tmp_path, "design the architecture of the cache layer", rows, "medium"),
                         env=env(tmp_path))
    assert "Sonnet 5.5" in out["systemMessage"]


def test_response_after_recorded_model_wins(tmp_path):
    run_hook("model_router.py", {"session_id": "s1", "model": "claude-haiku-5-5"}, "session-start",
             env=env(tmp_path))
    rows = [assistant(model="claude-opus-5-5", effort="high", timestamp="2099-01-01T00:00:00.000Z")]
    code, out, _ = run_hook("model_router.py",
                            payload(tmp_path, "design the architecture of the cache layer", rows, "high"),
                            env=env(tmp_path))
    assert code == 0 and out is None  # deep on Opus high fits


def test_standard_on_opus_xhigh_small_context_suggests_effort_only(tmp_path):
    rows = [assistant(model="claude-opus-5-5", effort="xhigh", read=5_000, written=1_000)]
    _, out, _ = run_hook("model_router.py", payload(tmp_path, "implement the export command", rows),
                         env=env(tmp_path))
    assert "/effort medium" in out["systemMessage"]
    assert "sonnet-worker" not in out["systemMessage"]
    assert "hookSpecificOutput" not in out


def test_old_model_effort_change_is_not_called_cache_safe(tmp_path):
    rows = [assistant(model="claude-opus-4-8", effort="high")]
    _, out, _ = run_hook("model_router.py", payload(tmp_path, "fix the typo in the README", rows, "high"),
                         env=env(tmp_path))
    assert "re-reads the context once" in out["systemMessage"]


def test_portuguese_prompt_bytes_survive_stdin(tmp_path):
    rows = [assistant(model="claude-opus-5-5", effort="high")]
    _, out, _ = run_hook("model_router.py", payload(tmp_path, "traduza a seção de instalação", rows, "high"),
                         env=env(tmp_path))
    assert "chore" in out["systemMessage"]


def test_silent_inside_subagents_and_on_bad_input(tmp_path):
    rows = [assistant(model="claude-opus-5-5")]
    data = payload(tmp_path, "rename foo to bar everywhere", rows)
    data["agent_id"] = "agent-1"
    assert run_hook("model_router.py", data, env=env(tmp_path))[1] is None
    code, out, _ = run_hook("model_router.py", "not an object", env=env(tmp_path))
    assert code == 0 and out is None


def test_state_script_never_fails(tmp_path):
    code, _, text = run_hook("model_state.py", {}, "no-such-session", "high",
                             env={"CLAUDE_CONFIG_DIR": str(tmp_path)})
    assert code == 0 and text.startswith("state=missing")


def test_state_script_finds_the_session_transcript(tmp_path):
    write_transcript(tmp_path / "projects" / "some-folder" / "abc-123.jsonl",
                     [assistant(model="claude-opus-5-5", effort="xhigh", read=160_000)])
    code, _, text = run_hook("model_state.py", {}, "abc-123", "xhigh", env={"CLAUDE_CONFIG_DIR": str(tmp_path)})
    assert code == 0
    assert "model=claude-opus-5-5 (Opus 5.5) effort=xhigh context=165k" in text
    assert "cache cold" in text  # the fixture's response is long past the 1h TTL


def test_state_script_prices_a_switch_while_the_cache_is_warm(tmp_path):
    now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    write_transcript(tmp_path / "projects" / "f" / "warm.jsonl",
                     [assistant(model="claude-opus-5-5", read=160_000, timestamp=now)])
    _, _, text = run_hook("model_state.py", {}, "warm", "high", env={"CLAUDE_CONFIG_DIR": str(tmp_path)})
    assert "switch_re-cache" in text and "sonnet $0.66" in text and "haiku $0.17" in text
