"""Objective text statistics that the model cannot count reliably itself.

These are measured in code and passed to the model as supporting evidence, alongside the same
statistics for marked exemplar answers, so it can see where an answer sits.
"""
import re
import statistics as st

EMOTION_LABELS = re.compile(
    r"\b(scared|afraid|fear|frightened|terrified|happy|sad|angry|nervous|shocked|excited|depressed|bored|"
    r"relieved|grateful|disappointed|disheartened|fulfilled|joy|amazed|confused|worried|anxious)\w*"
)
TIME_SKIPS = re.compile(r"\b(one day|the next day|after that|then|eventually|finally|years|days|weeks|all day|every day)\b")

# (key, label shown to the model, decimals)
MEASURES = [
    ("variety", "Vocabulary variety: distinct words per 100-word window (0-1)", 3),
    ("sentence_length", "Mean sentence length (words)", 1),
    ("emotion_labels", "Named emotions per 100 words (e.g. 'terrified', 'happy')", 2),
    ("time_skips", "Time-skip / summary phrases per 100 words (e.g. 'then', 'the next day')", 2),
    ("dialogue", "Words inside quotation marks (% of answer)", 1),
]


def measure(text):
    words = re.findall(r"[a-z']+", text.lower())
    n = max(len(words), 1)
    window = min(100, n)
    variety = st.mean(len(set(words[i:i + window])) / window for i in range(0, n - window + 1, 5))
    sentences = [s for s in re.split(r"(?<=[.!?])\s+|\n+", text) if re.search(r"\w", s)]
    quoted = sum(len(re.findall(r"[A-Za-z']+", q)) for q in re.findall(r"[\"\u201c](.*?)[\"\u201d]", text, re.S))
    return {
        "variety": variety,
        "sentence_length": n / max(len(sentences), 1),
        "emotion_labels": 100 * len(EMOTION_LABELS.findall(text.lower())) / n,
        "time_skips": 100 * len(TIME_SKIPS.findall(text.lower())) / n,
        "dialogue": 100 * quoted / n,
    }


def statistics_block(text, exemplars):
    """Markdown block comparing ``text`` with ``exemplars`` ({mark: [texts]} of other marked answers)."""
    mine = measure(text)
    marked = sorted(((mark, measure(t)) for mark, texts in exemplars.items() for t in texts), key=lambda x: x[0])
    lines = [
        "<text_statistics>",
        "Measured automatically for this answer and for answers to the same task already marked by the senior examiner.",
        "Use them only as supporting evidence for your own reading: they show where this answer sits, they never "
        "override the descriptors, and you must not mention them in your output.",
        "",
        "| Measure | This answer | Marked answers (mark: value) |",
        "|---|---|---|",
    ]
    for key, label, dp in MEASURES:
        others = ", ".join(f"{mark}: {m[key]:.{dp}f}" for mark, m in marked)
        lines.append(f"| {label} | {mine[key]:.{dp}f} | {others} |")
    lines.append("</text_statistics>")
    return "\n".join(lines)
