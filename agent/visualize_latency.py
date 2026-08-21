"""Day 4: turn agent/latency_log.jsonl (written by LatencyLogObserver during
real calls) into a bar chart of average time-to-first-byte/audio per pipeline
stage, in ms. Run manually after at least one real call: python
visualize_latency.py
"""

import json
from collections import defaultdict

import matplotlib.pyplot as plt

from latency_observer import LATENCY_LOG_PATH

STAGE_ORDER = ["STT", "LLM", "TTS"]


def friendly_stage(processor: str) -> str:
    for stage in STAGE_ORDER:
        if stage in processor.upper():
            return stage
    return processor


def load_rows() -> list[dict]:
    if not LATENCY_LOG_PATH.exists():
        return []
    rows = []
    with open(LATENCY_LOG_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def main():
    rows = load_rows()
    if not rows:
        print(
            f"No data in {LATENCY_LOG_PATH} yet - run a real call first "
            "(LatencyLogObserver writes to it during agent/bot.py's pipeline)."
        )
        return

    by_stage = defaultdict(list)
    for row in rows:
        by_stage[friendly_stage(row["processor"])].append(row["value_s"] * 1000)

    labels = [s for s in STAGE_ORDER if s in by_stage] + [
        s for s in by_stage if s not in STAGE_ORDER
    ]
    averages = [sum(by_stage[label]) / len(by_stage[label]) for label in labels]
    call_count = len({row["call_id"] for row in rows})

    fig, ax = plt.subplots(figsize=(6, 4))
    bars = ax.bar(labels, averages, color=["#4C72B0", "#DD8452", "#55A868"][: len(labels)])
    for bar, avg in zip(bars, averages):
        ax.annotate(
            f"{avg:.0f}ms",
            xy=(bar.get_x() + bar.get_width() / 2, avg),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
        )
    ax.set_ylabel("Avg time-to-first-byte/audio (ms)")
    ax.set_title(f"Pipeline latency by stage ({call_count} call(s), {len(rows)} samples)")
    fig.tight_layout()

    out_path = LATENCY_LOG_PATH.parent / "latency_chart.png"
    fig.savefig(out_path, dpi=150)
    print(f"Wrote {out_path} from {len(rows)} samples across {call_count} call(s).")


if __name__ == "__main__":
    main()
