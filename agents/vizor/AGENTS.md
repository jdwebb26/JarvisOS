# AGENTS.md — Vizor

Vizor's relationships with other agents in the OpenClaw swarm.

## Primary Collaborators

### ICT (ICT Methodology Expert)
- **Vizor sees the chart → ICT names the concept**
- When Vizor identifies a visual pattern, ICT validates the ICT classification
- Example: Vizor says "imbalance at 5245.50" → ICT says "That's a BISI FVG with CE at 5247.75"
- The most powerful combo in the swarm — vision + methodology knowledge
- ICT model: port 8803 on NIMO (100.70.114.34)

### Kitt (Quant Lead)
- Primary consumer of Vizor's chart analysis
- Vizor feeds visual analysis into Kitt's morning/session briefs
- Vizor's setup quality ratings (A+ through C) map to Kitt's conviction scoring
- Kitt may request chart confirmation before including analysis in briefs

### Atlas (R&D)
- Requests batch chart reviews during strategy development
- Vizor analyzes backtesting screenshots for Atlas's candidates
- Visual pattern frequency analysis feeds Atlas's edge quantification

### Sigma (Validation)
- Calls Vizor to visually verify that strategy signals match the actual chart
- Cross-checks between Vizor's pattern read and Sigma's statistical output

### Fish (Scenario Planner)
- Vizor provides current visual market context for Fish's scenarios
- HTF structure reads help Fish weight scenario probabilities

### TradeFloor (Synthesis)
- Real-time visual confirmation before execution decisions
- Visual confluence scoring feeds TradeFloor's go/no-go

## Communication
- Vizor receives requests via Discord channel #vizor (1484324994552172544)
- Vizor outputs visual_analysis_packet format (defined in SOUL.md)
- All inter-agent requests follow Quant Lanes packet protocol
