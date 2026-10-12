# Friction log

- 2026-10-11T08:47:20-05:00 — P1.4 vLLM serve help without GPU device flags failed during device inference; reran with the server's GPU device flags and captured help successfully. Approx. 1 minute lost.
- 2026-10-11T08:47:20-05:00 — P1.4 client help lacks `--custom-skip-chat-template`. Per the decision table, W1 will use random prompts with a 1536-token shared prefix and 2560 random continuation tokens; no code text. Updated `scripts/bench_engine.sh` to enact and record this fallback. No percentile flags were missing.
- 2026-10-11T10:40:00-05:00 — P1.6 first prompt-build attempt ran for about 1h43 CPU, then failed at prompt 0: the pinned Transformers image returns `BatchEncoding`, and `len()` counted its two mapping fields instead of token IDs. Fixed `count()` in `scripts/make_code_prompts.py` to count `input_ids`; retry passed with 192 prompts (4,066–4,128 tokens). Approx. 1h44 GPU-droplet time consumed.
- 2026-10-11T13:21:00-05:00 — Phase 3 was briefly started with SD due to a phase/config mapping error; section 6 defines Phase 3 as CFG_B=VT. The SD server was stopped, the first client attempt was interrupted before any requests completed, and its failed metadata is preserved under `L2-M1-SD-B-P3-w1-c1`. Restarting Phase 3 with VT; no workload result from the invalid attempt is included in analysis.

- 2026-10-11T18:27:00Z — P3.B prewarm client was interrupted before metadata was written during runner correction; repeated under the same run ID and completed cleanly. The earlier result file was superseded and is not used.

- 2026-10-11T19:13:00Z — Phase 3 VT B runner omitted the planned `w1-c8-r2` noise repeat. The remaining B and K1/K2 cells completed; the 5.5h threshold has passed and the server block is closed, so the repeat cannot be added. VT B noise band is unavailable and will be reported as such.
- 2026-10-11T15:40:17-05:00 — P4.3 initial tmux launch ended immediately because the remote shell expanded the image variable before sourcing config.env. Corrected the quoting and restarted the detached model download; approx. 1 minute lost.
