# Method and interpretation

One MI300X (192 GB), Qwen3.8-27B BF16, vLLM, 131072-token context, model-default thinking. Caps: 1800 seconds, 60 turns, 400000 uncached-input-plus-output tokens. Image digest, model revision and server flags are in `007-inputs/served_engine.json`. Frozen ATLAS source: `279889b8f42c607344781766503602a8c462f5df`; task tag: tasks-v1.

Strict solved uses the original ATLAS category: infrastructure, budget, timeout, turn/token caps and tamper take precedence over passing tests. Tests passing at cutoff is a secondary artifact observation; report both raw and clean counts. Each main level has 29 graded tasks of 30 planned; one task has only grader-infrastructure outcomes and is excluded, not scored as a model failure. Retries consume resources and contribute at most one usable verdict per task.

GPU-hours are the exact timestamp-derived active windows, including retries and grading/tool gaps. Setup, probe, cleanup, failed sessions and the discarded historical c22 infrastructure attempt are outside these level windows. $/solve is active GPU-hours × $1.99 / strict solved. Whole-study billable usage, recorded to its historical precision, is 15.5049 GPU-hours.

Wilson 95% intervals describe strict solved probability on the graded tasks. Throughput chart intervals scale those bounds by graded tasks / observed GPU-hours, conditional on the observed duration. They do not model queue-time variation. Fisher exact tests are two-sided, probability-ordered and unadjusted. Task sets overlap; these descriptive tests do not model pairing or establish a stable concurrency optimum.

Engine-side complete prompt input = prefix_queries delta, cached = prefix_hits delta, uncached = queries − hits. c16 uses a stable endpoint after its last attempt; c8/c4 have explicit boundaries and c4 subtracts the existing server baseline. Output remains a completed-response lower bound because interrupted requests lack terminal proxy usage. No output tail is extrapolated. c1's sampler includes extra historical infrastructure traffic and cannot be attributed to the anecdotal three-attempt subset.

The separate saved-diff sensitivity regrades 13 unsafe-snapshot attempts on amd64 native images rebuilt from frozen recipes, with node_modules omitted and hidden tests unchanged. Regraded originals replace retries for affected task/levels. Original cap, tamper and claim rules remain. Four recovered test passes are tampered and add no strict solves. The resulting panel is 3/30, 7/30 and 6/30. Reconstruction also omits generated untracked artifacts, so it is not an exact full-workspace ATLAS v1.1 replay. Official exports are unchanged.

ATLAS v1.1 for the next study excludes node_modules in workspace snapshots, retains strict checks for other symlinks, versions grades/cache fingerprints, and drains interrupted upstream requests for up to 30 seconds to retain reported usage. Forced termination or absent provider usage can still leave nulls. Changed grading policy can change denominators and scores; use a common policy or report separate panels. Frozen task bytes are unchanged.

One model, one engine, one GPU and one run per task. Training cutoff is unknown. c1 remains dropped, with only anecdotal n=3. No c32 or prefix-scheduling experiment was completed. Prefix-scheduling design credit: @thewidechaos.
