# Published Mock Benchmark

## Summary

This small benchmark exercises AgentEval's repeated-run statistics and CI regression gate with the built-in `MockAdapter`. It is a deterministic harness benchmark, not a measure of coding-agent capability or container performance.

| Version | Mock behavior | Passing runs | Pass rate | Wilson 95% interval | Estimated token cost |
| --- | --- | ---: | ---: | ---: | ---: |
| `mock-baseline-20` | Always succeeds | 20 / 20 | 100% | 83.9%–100.0% | $0.000160 |
| `mock-flaky-20` | Alternates fail, pass | 10 / 20 | 50% | 29.9%–70.1% | $0.000160 |

The one-sided Fisher exact test for a lower candidate pass rate returns **p = 0.000218**. At α = 0.05 this is a significant regression. The alternating mock fails on its first attempt, so its `pass@1` is 0%; the baseline `pass@1` is 100%.

## Method

- Use the same fixed instruction, `fix the clamping bug`, for 20 adapter calls per version.
- The baseline uses `MockAdapter(SUCCEEDS)`; the candidate uses `MockAdapter(FLAKY)`, whose scripted sequence starts with failure and alternates deterministically.
- Each mock result contributes its exit status and token/tool-call metadata. The configured price is $1 per million input tokens and $2 per million output tokens. Both output strings contain two words; each input has four words, producing $0.000008 per call and $0.000160 per 20-call version.
- Compute pass-rate intervals with the scorer's Wilson 95% interval and compare the two pass counts with the one-sided Fisher exact test.
- The figures above were calculated with `fisher_exact_regression(20, 20, 10, 20)` and `_wilson_interval(20, 20)` / `_wilson_interval(10, 20)` from the backend implementation.

This adapter-level benchmark does **not** execute a task repository, pytest, or Docker. The separate GitHub Actions workflow runs `MockAdapter` against the passing `tasks/ci-smoke` repository inside the `agenteval:ci` sandbox image, then checks that an intentionally failing mock version is rejected by `agenteval compare`.
