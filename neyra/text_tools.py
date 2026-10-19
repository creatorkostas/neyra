"""Local dictation cleanup and user-defined phrase expansion."""
import re


def clean_text(text):
    text = re.sub(r"\b(?:um+|uh+|erm+|er)\b[, ]*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b([\w']+)(?:\s+\1\b)+", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+([,.;!?])", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" ,")
    if text:
        text = text[0].upper() + text[1:]
        if text[-1] not in ".!?":
            text += "."
    return text


def apply_style(text, style):
    if style == "Clean up speech":
        return clean_text(text)
    if style == "Formal":
        return clean_text(text).replace("don't", "do not").replace("can't", "cannot")
    return text.strip()


def expand_snippets(text, snippets):
    for trigger, replacement in sorted(snippets.items(), key=lambda pair: len(pair[0]), reverse=True):
        if trigger.strip():
            text = re.sub(rf"(?<!\w){re.escape(trigger.strip())}(?!\w)", lambda _: replacement,
                          text, flags=re.IGNORECASE)
    return text


def meeting_brief(text):
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    summary = " ".join(sentences[:3]) or "No speech detected."
    actions = [sentence for sentence in sentences if re.search(
        r"\b(will|need to|next step|follow[- ]?up|action item|todo|should|due by)\b", sentence, re.IGNORECASE)]
    return summary, actions
