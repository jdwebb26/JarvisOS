from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.browser.backends.page_agent import PageAgentAnalyzer


def test_analyze_page_returns_stubbed_structured_analysis() -> None:
    analyzer = PageAgentAnalyzer(config={"mode": "local_stub"})
    payload = analyzer.analyze_page("https://example.com/demo")
    assert payload["analyzer"] == "page_agent"
    assert payload["status"] == "stubbed"
    assert payload["source_ref"] == "https://example.com/demo"
    assert isinstance(payload["detected_elements"], list)
    assert payload["reason"] == "page_agent_not_connected"


def test_propose_actions_returns_list() -> None:
    analyzer = PageAgentAnalyzer()
    analysis = analyzer.analyze_page("https://example.com/demo")
    proposals = analyzer.propose_actions("inspect the page and continue", analysis)
    assert isinstance(proposals, list)
    assert proposals
    assert "action_type" in proposals[0]
    assert "proposal_status" in proposals[0]


def test_high_risk_proposals_require_review() -> None:
    analyzer = PageAgentAnalyzer()
    analysis = analyzer.analyze_page("https://example.com/compose")
    proposals = analyzer.propose_actions("send a message to the customer", analysis)
    high_risk = [item for item in proposals if item["action_type"] == "send_external_message"]
    assert high_risk
    assert high_risk[0]["requires_review"] is True


if __name__ == "__main__":
    test_analyze_page_returns_stubbed_structured_analysis()
    test_propose_actions_returns_list()
    test_high_risk_proposals_require_review()
