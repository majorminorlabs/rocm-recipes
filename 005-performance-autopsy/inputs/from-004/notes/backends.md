
## VD

```text
(EngineCore pid=182) INFO 10-10 16:37:39 [rocm.py:703] Found incompatible backend(s) [TURBOQUANT] with AttentionType.DECODER. Overriding with ROCM_ATTN out of potential backends: ['ROCM_ATTN', 'ROCM_AITER_UNIFIED_ATTN', 'TRITON_ATTN'].
(EngineCore pid=182) INFO 10-10 16:37:39 [unquantized.py:319] Using TRITON Unquantized MoE backend out of potential backends: ['ROCm AITER', 'TRITON', 'BATCHED_TRITON'].
(EngineCore pid=182) INFO 10-10 16:38:08 [unquantized.py:400] Using TritonExperts MoE backend
```

## VT

```text
(EngineCore pid=182) INFO 10-10 17:13:56 [rocm.py:638] Using ROCM_AITER_UNIFIED_ATTN backend (selected via --attention-backend).
(EngineCore pid=182) INFO 10-10 17:13:58 [unquantized.py:319] Using TRITON Unquantized MoE backend out of potential backends: ['ROCm AITER', 'TRITON', 'BATCHED_TRITON'].
(EngineCore pid=182) INFO 10-10 17:14:29 [unquantized.py:400] Using TritonExperts MoE backend
(EngineCore pid=182) INFO 10-10 17:14:30 [interface.py:635] Setting kv cache block size to 64 for ROCM_AITER_UNIFIED_ATTN backend.
```

## SD

- Startup/capacity log: `Attention backend not specified. Use aiter backend by default.`
- AITER fused MoE was selected (`[fused_moe] using 2stage default`); hipcc reports it does not support `-mllvm -amdgpu-coerce-illegal-types=1` and skips that option.
- KV pool: 914643 tokens; VRAM used at capacity snapshot: 186553257984 B.

## SX

- Requested `SGLANG_USE_AITER=0` (confirmed by `logs/current_server.json` and container environment).
- Observed startup still says `Attention backend not specified. Use aiter backend by default.`; AITER attention JIT activity appears in the server log.
- MoE path reports `Using default MoE kernel config` for Triton fused-MoE config files; no AITER fused-MoE selection was observed in the capacity capture.
- KV pool: 914643 tokens; capacity snapshot is in `results/raw/L0/L0-M1-SX/`.

## LC1

- llama.cpp commit `06cad0b9e77315bd2930bd4f70a6d7b37b2a01c1`; KV cache dtype `f16`.
- Capacity parser returned null (allowed for llama.cpp). Raw line records `n_slots = 1`, `n_ctx_slot = 131072`; full capture is in `results/raw/L0/L0-M1-LC1/capacity_raw.txt`.

## LC4

- llama.cpp commit `06cad0b9e77315bd2930bd4f70a6d7b37b2a01c1`; KV cache dtype `f16`.
- Capacity parser returned null (allowed for llama.cpp). Raw line records `n_slots = 4`, `n_ctx_slot = 34816`; full capture is in `results/raw/L0/L0-M1-LC4/capacity_raw.txt`.

## SD256

- SGLang default AITER attention; AITER fused-MoE initialization observed.
- Capacity KV pool: 914622 tokens at 262144 context. Full capture in `results/raw/L0/L0-M1-SD256/`.

## M7-VT

- vLLM selected `ROCM_AITER_UNIFIED_ATTN`; attention backend evidence is in `results/raw/L0/L0-M7-VT/backend.txt`.
- KV capacity: 421952 tokens; GPU memory and full raw capture are saved with the L0 result.

## M7-SD

- SGLang default AITER attention; model's dense FFN has no MoE backend path.
- KV pool: 326383 tokens; full backend/capacity capture in `results/raw/L0/L0-M7-SD/`.
