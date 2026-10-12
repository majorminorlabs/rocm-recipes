## A

(EngineCore pid=182) INFO 10-09 23:04:01 [rocm.py:703] Found incompatible backend(s) [TURBOQUANT] with AttentionType.DECODER. Overriding with ROCM_ATTN out of potential backends: ['ROCM_ATTN', 'ROCM_AITER_UNIFIED_ATTN', 'TRITON_ATTN'].
(EngineCore pid=182) INFO 10-09 23:04:01 [unquantized.py:319] Using TRITON Unquantized MoE backend out of potential backends: ['ROCm AITER', 'TRITON', 'BATCHED_TRITON'].
(EngineCore pid=182) INFO 10-09 23:04:31 [unquantized.py:400] Using TritonExperts MoE backend
(EngineCore pid=182) WARNING 10-09 23:05:17 [chunked_prefill_paged_decode.py:433] Cannot use ROCm custom paged attention kernel, falling back to Triton implementation.

## B

(EngineCore pid=182) INFO 10-09 23:51:40 [rocm.py:703] Found incompatible backend(s) [TURBOQUANT] with AttentionType.DECODER. Overriding with ROCM_ATTN out of potential backends: ['ROCM_ATTN', 'ROCM_AITER_UNIFIED_ATTN', 'TRITON_ATTN'].
(EngineCore pid=182) INFO 10-09 23:51:40 [unquantized.py:319] Using TRITON Unquantized MoE backend out of potential backends: ['ROCm AITER', 'TRITON', 'BATCHED_TRITON'].
(EngineCore pid=182) INFO 10-09 23:52:08 [unquantized.py:400] Using TritonExperts MoE backend

## C

(EngineCore pid=182) INFO 10-10 00:16:52 [rocm.py:638] Using ROCM_AITER_UNIFIED_ATTN backend (selected via --attention-backend).
(EngineCore pid=182) INFO 10-10 00:16:54 [unquantized.py:319] Using TRITON Unquantized MoE backend out of potential backends: ['ROCm AITER', 'TRITON', 'BATCHED_TRITON'].
(EngineCore pid=182) INFO 10-10 00:17:22 [unquantized.py:400] Using TritonExperts MoE backend

## D

(EngineCore pid=182) INFO 10-10 00:46:16 [rocm.py:703] Found incompatible backend(s) [TURBOQUANT] with AttentionType.DECODER. Overriding with ROCM_ATTN out of potential backends: ['ROCM_ATTN', 'ROCM_AITER_FA', 'ROCM_AITER_UNIFIED_ATTN', 'TRITON_ATTN'].
(EngineCore pid=182) INFO 10-10 00:46:16 [unquantized.py:282] Using ROCm AITER Unquantized MoE backend out of potential backends: ['ROCm AITER', 'TRITON', 'BATCHED_TRITON'].
(EngineCore pid=182) INFO 10-10 00:46:44 [unquantized.py:400] Using AiterExperts MoE backend
(EngineCore pid=182) WARNING 10-10 00:47:13 [chunked_prefill_paged_decode.py:433] Cannot use ROCm custom paged attention kernel, falling back to Triton implementation.

## E

(EngineCore pid=182) INFO 10-10 02:07:14 [rocm.py:638] Using ROCM_AITER_UNIFIED_ATTN backend (selected via --attention-backend).
(EngineCore pid=182) INFO 10-10 02:07:16 [unquantized.py:319] Using TRITON Unquantized MoE backend out of potential backends: ['ROCm AITER', 'TRITON', 'BATCHED_TRITON'].
(EngineCore pid=182) INFO 10-10 02:07:44 [unquantized.py:400] Using TritonExperts MoE backend

### Session 2

## C

(EngineCore pid=182) INFO 10-10 09:59:57 [rocm.py:638] Using ROCM_AITER_UNIFIED_ATTN backend (selected via --attention-backend).
(EngineCore pid=182) INFO 10-10 09:59:57 [rocm_aiter_unified_attn.py:165] Using aiter unified attention for RocmAiterUnifiedAttentionImpl
(EngineCore pid=182) INFO 10-10 10:00:32 [interface.py:635] Setting kv cache block size to 64 for ROCM_AITER_UNIFIED_ATTN backend.
(EngineCore pid=182) INFO 10-10 09:59:41 [api_utils.py:286] non-default args include attention_backend ROCM_AITER_UNIFIED_ATTN and enable_prefix_caching False.
(EngineCore pid=182) INFO 10-10 10:00:00 [unquantized.py:400] Using TritonExperts MoE backend

## E

(EngineCore pid=182) INFO 10-10 10:48:35 [rocm.py:638] Using ROCM_AITER_UNIFIED_ATTN backend (selected via --attention-backend).
(EngineCore pid=182) INFO 10-10 10:48:35 [rocm_aiter_unified_attn.py:165] Using aiter unified attention for RocmAiterUnifiedAttentionImpl
(EngineCore pid=182) INFO 10-10 10:49:06 [interface.py:635] Setting kv cache block size to 64 for ROCM_AITER_UNIFIED_ATTN backend.
(EngineCore pid=182) INFO 10-10 10:48:18 [api_utils.py:286] non-default args show kv_cache_dtype fp8 and enable_prefix_caching False.
(EngineCore pid=182) INFO 10-10 10:49:06 [unquantized.py:400] Using TritonExperts MoE backend

## A (session 2)

(EngineCore pid=182) INFO 10-10 11:24:11 [rocm.py:703] Overriding with ROCM_ATTN out of potential backends.
(EngineCore pid=182) INFO 10-10 11:24:40 [unquantized.py:400] Using TritonExperts MoE backend
(EngineCore pid=182) WARNING 10-10 11:25:27 [chunked_prefill_paged_decode.py:433] Cannot use ROCm custom paged attention kernel, falling back to Triton implementation.

## B (session 2)

(EngineCore pid=182) INFO 10-10 12:44:23 [rocm.py:703] Overriding with ROCM_ATTN out of potential backends.
(EngineCore pid=182) INFO 10-10 12:44:51 [unquantized.py:400] Using TritonExperts MoE backend
