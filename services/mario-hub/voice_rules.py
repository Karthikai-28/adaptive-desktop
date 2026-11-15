"""What counts as "Hey Mario", and as your voice. Pure rules: no audio, no models, no files.

The hub (system Python) and the recognition worker (the voice environment) both read this, so the
two never disagree about the phrase.

A voiceprint is a list of numbers the speaker model gives for a stretch of speech; two stretches by
the same person point nearly the same way. Training keeps the prints of four "Hey Mario"s, their
middle, and how close a new one must be to count as you. That bar is set from how much your own
four differ, between LOW and HIGH. It is a convenience, not a lock: a similar voice or a recording
of you can pass it.
"""
import math
import re

# How recognition writes the phrase: "Hey Mario", "Hey, Mario!", "Hi Mario", "Himario", "Hey Mari-o".
# Other names (Maria, Maya) are not the phrase.
_HEY = r"(?:hey|hay|hi|he|eh|a|ay|aye|pay|say|they|day|yay|okay|ok)"
_MARIO = r"(?:mario|marrio|mareo|maryo|morio|merio|mar[iy][\s-]o)"
WAKE = re.compile(rf"^\W*(?:{_HEY}\W+|h(?:ey|i|e)){_MARIO}\b[\s,.!?:;\-]*", re.I)
# the first words sound like the phrase is still being said: worth one more look a moment later
BEGINS = re.compile(rf"^\W*(?:{_HEY}\b|h(?:ey|i|e)m)", re.I)

SAMPLES = 4        # how many times training asks for the phrase
LOW, HIGH = 0.38, 0.54
MARGIN = 0.16      # how far below your own least-alike sample the bar sits
STRANGER = 0.30    # a training sample this unlike the ones before is not the same voice


def is_wake(text):
    return bool(WAKE.match(str(text or "")))


def only_wake(text):
    """The phrase and nothing after it (what training asks for)."""
    return is_wake(text) and not strip_wake(text)


def strip_wake(text):
    """What was said after "Hey Mario", starting with a capital; the text itself without the phrase."""
    text = str(text or "").strip()
    rest = WAKE.sub("", text, count=1).strip()
    if rest == text:
        return text
    return rest[:1].upper() + rest[1:]


def unit(vector):
    size = math.sqrt(sum(x * x for x in vector))
    return [x / size for x in vector] if size else list(vector)


def cosine(a, b):
    a, b = unit(a), unit(b)
    return sum(x * y for x, y in zip(a, b))


def centre(prints):
    return unit([sum(column) for column in zip(*(unit(p) for p in prints))])


def bar(prints):
    """How close a new print must be: each of yours against the middle of the others."""
    if len(prints) < 2:
        return HIGH
    least = min(cosine(p, centre(prints[:i] + prints[i + 1:])) for i, p in enumerate(prints))
    return round(max(LOW, min(HIGH, least - MARGIN)), 3)


def make_profile(prints):
    prints = [unit(p) for p in prints]
    return {"centre": centre(prints), "prints": prints, "bar": bar(prints)}


def belongs(prints, new):
    """During training: is this sample the same voice as the ones before it?"""
    return not prints or cosine(new, centre(prints)) >= STRANGER
