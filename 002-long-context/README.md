# Long context on one MI300X

How much context fits on one 192 GB MI300X, how fast does it answer, and can it still find a fact at the far end? Qwen3-Coder 30B fit a 256K-token window for about 3.8 simultaneous users with BF16 KV cache (7.6 with FP8), and found the target in all nine hard retrieval trials at 256K. On the tested vLLM stack, its decode slowed to 1.1 tokens/s at that length after the attention kernel fell back to Triton. Two sessions used 8.8 GPU-hours, costing $17.56 at $1.99/hour.

## Folder map

- [scripts/](scripts/): setup, serving, benchmarking, retrieval, sync, teardown, and summarization commands.
- [results/](results/): raw measurements, [summary.csv](results/summary.csv), and recorded environment details.

## Rerun

Install `doctl`, prepare an SSH key and AMD Developer Cloud access, then copy [config.env.example](config.env.example) to `config.env` and fill in the blank values. Use the scripts in `scripts/` to set up, run, sync, and tear down the experiment. The scripts use the configured deadline and teardown commands so the GPU is not left running after the work ends.
