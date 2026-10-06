# SQLAI model benchmark

Ten natural-language questions ([`questions.json`](questions.json)) over the
`initial_migration/csvs` data (customers, products, orders). Each model gets the
same schema and system prompt the app uses (`build_sql_prompt` in
`ai_service.py`); its SQL runs read-only against Postgres and is graded by
comparing result rows with a reference query. Reordered or extra columns,
rounding to 2 decimals, and numbers returned as text are accepted.

## Running it

Needs a scratch Postgres database (seeded automatically on first run) and
`NVIDIA_API_KEY` in the repo-root `.env`:

```bash
createdb sqlai_bench
python SQLAI/benchmark/run_benchmark.py \
  --db-url postgresql://localhost/sqlai_bench \
  --models nvidia/nemotron-3-super-120b-a12b,openai/gpt-oss-20b --runs 3
```

The free NVIDIA tier rate-limits bursts. The runner retries 429/503 with
backoff and reports API failures separately from wrong answers; keep
`--workers` low (default 3).

## Results (October 2026, 3 runs per question)

| Model | Correct (of 30) | Median latency | p90 latency | Misses |
|---|---|---|---|---|
| `meta/muse-glimmer-30b` | 30 | 27.9s | 62.5s | none |
| **`nvidia/nemotron-3-super-120b-a12b`** | **28** | **2.3s** | **6.5s** | Q4 ×2 |
| `nvidia/nemotron-3-ultra-550b-a55b` | 28 | 13.4s | 32.6s | Q1, Q4 |
| `openai/gpt-oss-20b` | 27 | 5.6s | 11.8s | Q4 ×2, Q7 (SQL error) |
| `nvidia/nemotron-3.5-lightning-30b-a3b` | 26 of 29 | 45.6s | 137.3s | Q4 ×2, Q8 (SQL error) |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` | 25 | 6.7s | 13.6s | Q1 ×2, Q4 ×2, Q10 |

**Chosen: `nvidia/nemotron-3-super-120b-a12b`.** One answer behind the top
scorer, on the question every other model also missed, at roughly a twelfth of
its latency. SQLAI is interactive and each question also triggers a chart
call, so a 28s median would be felt on every query.

An earlier, easier draft of the question set (plain counts, filters, joins,
GROUP BY/HAVING) scored 100% for every model it finished, which is why the
current set targets running totals, revenue shares, weekend detection, anti-joins
with date filters and year-over-year change.

Not benchmarked because they didn't answer at the time (requests hung until
timeout): `z-ai/glm-5.3`, `z-ai/glm-5.3-flash`, `google/gemma-4-31b-it`,
`moonshotai/kimi-k3`, `deepseek-ai/deepseek-v4.1-flash`, `poolside/laguna-xs-2.1`.
Most other listed chat models return 404 for this account.
