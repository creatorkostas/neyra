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
        expanded = re.sub(r"\b(don't|can't)\b",
                          lambda match: {"don't": "do not", "can't": "cannot"}[match.group().lower()],
                          text, flags=re.IGNORECASE)
        return clean_text(expanded)
    return text.strip()


def expand_snippets(text, snippets):
    entries = sorted(((trigger.strip(), replacement) for trigger, replacement in snippets.items() if trigger.strip()),
                     key=lambda entry: len(entry[0]), reverse=True)
    if not entries:
        return text
    triggers = "|".join(f"({re.escape(trigger)})" for trigger, _ in entries)
    # One substitution pass prevents replacement text from triggering another snippet.
    return re.sub(rf"(?<!\w)(?:{triggers})(?!\w)",
                  lambda match: entries[match.lastindex - 1][1], text, flags=re.IGNORECASE)


def meeting_brief(text):
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    summary = " ".join(sentences[:3]) or "No speech detected."
    actions = [sentence for sentence in sentences if re.search(
        r"\b(will|need to|next step|follow[- ]?up|action item|todo|should|due by)\b", sentence, re.IGNORECASE)]
    return summary, actions
