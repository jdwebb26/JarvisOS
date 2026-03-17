from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import openclaw_specialization_bridge as bridge


def test_handler_patch_detection_and_apply() -> None:
    before = bridge._check_handler_state(bridge.HANDLER_OLD)
    assert not all(before.values())

    updated, changed = bridge._apply_handler_replacement(bridge.HANDLER_OLD)
    assert changed is True
    after = bridge._check_handler_state(updated)
    assert all(after.values())


def test_bundle_patch_detection_still_passes_when_present() -> None:
    text, _ = bridge._apply_bundle_replacements(
        '\t\tconst skillsPrompt = resolveSkillsPromptForRun({\n'
        'function shouldStripJarvisSkills(sessionKey) {\n        return true;\n}\n'
        'const candidate = path.resolve(workspaceDir, "scripts", "source_owned_context_engine_cli.py");\n'
        '\tif (existsSync(candidate)) return candidate;\n'
        '\tthrow new Error(`Source-owned context engine CLI not found: ${candidate}`);\n'
        'skills_prompt: typeof params.skillsPrompt === "string" ? params.skillsPrompt : ""\n'
        'agent_id: typeof params.agentId === "string" ? params.agentId : ""\n'
        'provider_id: typeof params.providerId === "string" ? params.providerId : ""\n'
        'model_id: typeof params.modelId === "string" ? params.modelId : ""\n'
        'if (typeof sourceOwnedContextSeed?.filteredSkillsPrompt === "string") skillsPrompt = sourceOwnedContextSeed.filteredSkillsPrompt;\n'
        '\t\tconst skillsPrompt = resolveSkillsPromptForRun({\n'
    )
    checks = bridge._check_bundle_state(text)
    assert all(checks.values())


def test_bundle_network_guard_detection_requires_both_soft_fail_paths() -> None:
    checks = bridge._check_bundle_state(
        "function listTailnetAddresses() {\n"
        "\tconst ipv4 = [];\n"
        "\tconst ipv6 = [];\n"
        "\tlet ifaces;\n"
        "\ttry {\n"
        "\t\tifaces = os.networkInterfaces();\n"
        "\t}\n"
        "\tcatch {\n"
        "\t\treturn {\n"
        "\t\t\tipv4: [],\n"
        "\t\t\tipv6: []\n"
        "\t\t};\n"
        "\t}\n"
        "}\n"
        "function pickPrimaryLanIPv4() {\n"
        "\tlet nets;\n"
        "\ttry {\n"
        "\t\tnets = os.networkInterfaces();\n"
        "\t}\n"
        "\tcatch {\n"
        "\t\treturn;\n"
        "\t}\n"
        "}\n"
        'skills_prompt: typeof params.skillsPrompt === "string" ? params.skillsPrompt : ""\n'
        'agent_id: typeof params.agentId === "string" ? params.agentId : ""\n'
        'provider_id: typeof params.providerId === "string" ? params.providerId : ""\n'
        'model_id: typeof params.modelId === "string" ? params.modelId : ""\n'
        'if (typeof sourceOwnedContextSeed?.filteredSkillsPrompt === "string") skillsPrompt = sourceOwnedContextSeed.filteredSkillsPrompt;\n'
        '\t\tlet skillsPrompt = resolveSkillsPromptForRun({\n'
        '\t\tlet skillsPrompt = resolveSkillsPromptForRun({\n'
        'path.resolve(process.env.HOME || "", ".openclaw", "workspace", "jarvis-v5", "scripts", "source_owned_context_engine_cli.py")\n'
        'const bootstrapExtraFilesModule = await import("./bundled/bootstrap-extra-files/handler.js");\n'
        "if (event.context.bootstrapFiles === originalFiles) try {\n"
        "function shouldStripJarvisSkills(sessionKey) {\n        return false;\n}\n"
    )
    assert checks[bridge.NETWORK_GUARD_LABEL] is True


# ---------------------------------------------------------------------------
# _apply_searxng_to_extra_bundles — missing / unpatched / patched cases
# ---------------------------------------------------------------------------

def test_extra_bundles_missing_file_reported(tmp_path: Path) -> None:
    """Bundles listed in SEARXNG_EXTRA_BUNDLES that don't exist appear in results as missing-file."""
    results = bridge._apply_searxng_to_extra_bundles(tmp_path, apply=False)
    # Every declared bundle must appear — none are silently dropped.
    for bname in bridge.SEARXNG_EXTRA_BUNDLES:
        assert bname in results, f"{bname} missing from results"
        checks = results[bname]
        assert checks["bundle_found"] is False
        assert checks["searxng_patched"] is False
        assert bridge._extra_bundle_status(checks) == "missing-file"
    # Missing files do not count as unpatched; fully_patched should be True.
    assert bridge._extra_bundles_fully_patched(results) is True


def test_extra_bundles_unpatched_reported(tmp_path: Path) -> None:
    """A bundle with createWebSearchTool but no SearXNG patch is reported as unpatched."""
    bname = bridge.SEARXNG_EXTRA_BUNDLES[0]
    (tmp_path / bname).write_text(
        'function createWebSearchTool() {}\nif (raw === "perplexity") return "perplexity";\n',
        encoding="utf-8",
    )
    results = bridge._apply_searxng_to_extra_bundles(tmp_path, apply=False)
    checks = results[bname]
    assert checks["bundle_found"] is True
    assert checks["has_web_search_tool"] is True
    assert checks["searxng_patched"] is False
    assert bridge._extra_bundle_status(checks) == "unpatched"
    assert bridge._extra_bundles_fully_patched(results) is False


def test_extra_bundles_no_wst_not_a_failure(tmp_path: Path) -> None:
    """A bundle that exists but has no createWebSearchTool is not counted as needing a patch."""
    bname = bridge.SEARXNG_EXTRA_BUNDLES[0]
    (tmp_path / bname).write_text("// no web search here\n", encoding="utf-8")
    results = bridge._apply_searxng_to_extra_bundles(tmp_path, apply=False)
    checks = results[bname]
    assert checks["bundle_found"] is True
    assert checks["has_web_search_tool"] is False
    assert bridge._extra_bundle_status(checks) == "no-web-search-tool"
    # Not having the tool means nothing to patch; fully_patched returns True.
    assert bridge._extra_bundles_fully_patched(results) is True


def test_extra_bundles_fully_patched_helper() -> None:
    """_extra_bundles_fully_patched logic across mixed states."""
    assert bridge._extra_bundles_fully_patched({}) is True
    assert bridge._extra_bundles_fully_patched(
        {"a.js": {"bundle_found": True, "has_web_search_tool": True, "searxng_patched": True}}
    ) is True
    assert bridge._extra_bundles_fully_patched(
        {"a.js": {"bundle_found": True, "has_web_search_tool": True, "searxng_patched": False}}
    ) is False
    # Missing file does not fail the check.
    assert bridge._extra_bundles_fully_patched(
        {"a.js": {"bundle_found": False, "has_web_search_tool": False, "searxng_patched": False}}
    ) is True


# ---------------------------------------------------------------------------
# _discover_unregistered_web_search_bundles
# ---------------------------------------------------------------------------

def test_discover_unregistered_web_search_bundles(tmp_path: Path) -> None:
    skip = {bridge.SEARXNG_EXTRA_BUNDLES[0]}

    # A bundle in the skip set — must not be returned.
    (tmp_path / bridge.SEARXNG_EXTRA_BUNDLES[0]).write_text(
        "x" * 20_000 + "createWebSearchTool", encoding="utf-8"
    )
    # An unknown bundle that has createWebSearchTool — must be returned.
    unknown = tmp_path / "reply-NEWXXXXX.js"
    unknown.write_text("x" * 20_000 + "createWebSearchTool", encoding="utf-8")
    # A bundle without the marker — must not be returned.
    (tmp_path / "other-ZZZZ.js").write_text("x" * 20_000, encoding="utf-8")
    # A tiny stub — must not be returned (below 10 KB threshold).
    (tmp_path / "stub-TINY.js").write_text("createWebSearchTool", encoding="utf-8")

    found = bridge._discover_unregistered_web_search_bundles(tmp_path, skip)
    assert unknown.name in found
    assert bridge.SEARXNG_EXTRA_BUNDLES[0] not in found
    assert "other-ZZZZ.js" not in found
    assert "stub-TINY.js" not in found


# ---------------------------------------------------------------------------
# _smoke_check_searxng — no-URL fast path
# ---------------------------------------------------------------------------

def test_smoke_check_no_url() -> None:
    """Smoke check returns ok=False immediately when no URL is available."""
    old = os.environ.pop("JARVIS_SEARXNG_URL", None)
    try:
        result = bridge._smoke_check_searxng(base_url=None)
        assert result["ok"] is False
        assert "error" in result
    finally:
        if old is not None:
            os.environ["JARVIS_SEARXNG_URL"] = old


def test_smoke_check_unreachable_url() -> None:
    """Smoke check returns ok=False with healthz_error when the host is not reachable."""
    result = bridge._smoke_check_searxng(base_url="http://127.0.0.1:19999")
    assert result["ok"] is False
    assert result.get("healthz_ok") is False
    assert "healthz_error" in result
