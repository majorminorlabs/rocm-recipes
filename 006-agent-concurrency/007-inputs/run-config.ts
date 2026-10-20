import type { RunConfig } from '../atlas.config.ts';

export const qwen38Mi300xConfig: RunConfig = {
  id: 'qwen38-27b-mi300x', harness: 'opencode', backend: 'local',
  model: 'Qwen/Qwen3.8-27B', trainingCutoff: null,
  trainingCutoffNote: 'unknown: no training cutoff stated in the official model card checked 2026-10-15; all frozen source commits are after 2026-08-15.',
  effort: null, // No reasoning override: preserve the model/server default.
  label: 'Qwen3.8-27B BF16, 1× MI300X; GPU-hours × $1.99',
  execution: { precision: 'BF16', thinking: 'model-default', wallS: 1800,
    turns: 60, totalTokens: 400_000, context: 131_072, tokenAccounting: 'uncached_input_output' },
};
export const qwen38Mi300x = {
  localCost: { hourlyRateUsd: 1.99, hardware: '1× AMD MI300X 192 GB (AMD Developer Cloud)', owned: false },
  modelCard: 'https://huggingface.co/Qwen/Qwen3.8-27B',
  modelCardRevision: '1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0',
  modelCardSha256: '57e4bdb258ee1a7d2635c5174ebd4e56abe392505cdb5f8bbb356b0dc4293641',
  checked: '2026-10-15',
  trainingCutoffStatus: 'unknown',
} as const;
