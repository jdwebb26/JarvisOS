from pathlib import Path
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
