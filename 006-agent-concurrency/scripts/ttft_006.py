"""Engine-side TTFT: cumulative Prometheus histogram snapshots and queue deltas."""
import json
import math
import re

METRICS = {'vllm': 'vllm:time_to_first_token_seconds',
           'sglang': 'sglang:time_to_first_token_seconds'}


def histogram(text, engine):
    name = METRICS.get(engine)
    if not name:
        return None
    series = {}
    pattern = re.compile(r'^' + re.escape(name) + r'_bucket\{(.*)\}\s+(\S+)')
    labels = re.compile(r'(\w+)="((?:\\.|[^"\\])*)"')
    for line in text.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        pairs = dict(labels.findall(match[1]))
        bound = pairs.pop('le', None)
        try:
            limit, count = float(bound), float(match[2])
            if math.isnan(limit) or limit < 0 or not math.isfinite(count) or count < 0:
                return None
        except (ValueError, TypeError):
            return None
        key = json.dumps(sorted(pairs.items()), separators=(',', ':'))
        bucket = '+Inf' if math.isinf(limit) else str(limit)
        values = series.setdefault(key, {})
        if bucket in values:
            return None
        values[bucket] = count
    if not series or any('+Inf' not in buckets or len(buckets) < 2 for buckets in series.values()):
        return None
    for buckets in series.values():
        counts = [v for k, v in sorted(buckets.items(), key=lambda kv: float(kv[0]))]
        if any(b < a for a, b in zip(counts, counts[1:])):
            return None
    return {'metric': name, 'series': series}


def histogram_quantile(buckets, q):
    """Classic histogram linear interpolation, including Prometheus +Inf rule."""
    pairs = sorted((float(k), v) for k, v in buckets.items())
    if not pairs or not math.isinf(pairs[-1][0]) or pairs[-1][1] <= 0:
        return None
    rank = q * pairs[-1][1]
    lower, previous = 0.0, 0.0
    for bound, cumulative in pairs:
        if cumulative >= rank:
            if math.isinf(bound):
                return lower
            return lower + (bound - lower) * (rank - previous) / (cumulative - previous) if cumulative > previous else bound
        lower, previous = bound, cumulative
    return None


def level_ttft(samples, level, start=None, end=None):
    """Use explicit before/after snapshots, never relabel proxy timing as TTFT.

    Counter resets, changed label/bucket sets, absent metrics or insufficient
    snapshots yield null rather than an extrapolated or partially scoped result.
    """
    result = dict(engine_ttft_p50_s=None, engine_ttft_p95_s=None,
                  engine_ttft_observations=None, engine_ttft_metric=None,
                  engine_ttft_source='engine-side TTFT', engine_ttft_status='absent')
    records = sorted((s for s in samples if s.get('level') == level), key=lambda s: s.get('_ts', s['ts']))
    before = [i for i, s in enumerate(records) if s.get('boundary') == 'before']
    after = [i for i, s in enumerate(records) if s.get('boundary') == 'after']
    if len(before) != 1 or len(after) != 1 or before[0] >= after[0]:
        result['engine_ttft_status'] = 'missing_or_ambiguous_boundaries'
        return result
    first_ts=records[before[0]].get('_ts', records[before[0]]['ts'])
    last_ts=records[after[0]].get('_ts', records[after[0]]['ts'])
    if (start is not None and first_ts > start) or (end is not None and last_ts < end):
        result['engine_ttft_status'] = 'window_not_bracketed'
        return result
    snapshots = [s.get('engine_ttft_histogram') for s in records[before[0]:after[0] + 1]]
    if any(h is None for h in snapshots):
        return result
    first = snapshots[0]
    result['engine_ttft_metric'] = first['metric']
    aggregate = {}
    for a, b in zip(snapshots, snapshots[1:]):
        if b['metric'] != first['metric'] or set(a['series']) != set(b['series']):
            result['engine_ttft_status'] = 'series_changed'
            return result
        for key, older in a['series'].items():
            newer = b['series'][key]
            if set(older) != set(newer):
                result['engine_ttft_status'] = 'buckets_changed'
                return result
            changes = {le: newer[le] - count for le, count in older.items()}
            counts = [v for k, v in sorted(changes.items(), key=lambda kv: float(kv[0]))]
            if any(v < 0 for v in counts) or any(b < a for a, b in zip(counts, counts[1:])):
                result['engine_ttft_status'] = 'counter_reset_or_invalid_delta'
                return result
            # Equal bucket schemas are required across labels before aggregation.
            if aggregate and set(aggregate) != set(changes):
                result['engine_ttft_status'] = 'buckets_changed'
                return result
            for le, count in changes.items():
                aggregate[le] = aggregate.get(le, 0) + count
    if not aggregate or aggregate.get('+Inf', 0) <= 0:
        result['engine_ttft_status'] = 'no_observations'
        return result
    result.update(engine_ttft_p50_s=histogram_quantile(aggregate, .5),
                  engine_ttft_p95_s=histogram_quantile(aggregate, .95),
                  engine_ttft_observations=aggregate['+Inf'], engine_ttft_status='ok')
    return result
