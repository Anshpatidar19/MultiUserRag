"""
llm/smalltalk.py

Hardcoded, zero-latency replies for pure small talk -- greetings like
"hi", "hii", "hyy", "hello", plus thanks/goodbyes. These carry no
informational question, so the old behavior of routing them through
retrieval + a streamed Gemini call was pure wasted latency: a 1-3+
second round trip for an answer that's really just "hello back." This
module recognizes that pattern with no network/model call at all and
returns a ready-made reply instantly.

Deliberately narrow, on purpose: only a message that IS JUST a greeting
(after trimming trivial punctuation/whitespace) matches. "hi, what's in
my contract?" must NOT match -- it's a real question wearing a greeting
as a prefix, and stripping it down to "hi" and answering only that
would silently drop the actual question. `match_canned_reply` returns
None for anything that isn't unambiguously pure small talk, and the
caller (routers/chat.py) falls through to the normal RAG/LLM path.

Typo/elongation tolerance: real users type "hii", "heyy", "hlo", "hyy",
"hiiii", etc. -- treating only the dictionary-perfect spelling as a
greeting would miss most of what people actually type. For single-word
messages, `_normalize` collapses any run of a repeated letter down to
one instance ("hiiii" -> "hi", "heyyy" -> "hey", "hyy" -> "hy"), so the
match set only needs to list each greeting's *shortest* form. This
collapsing is deliberately skipped for multi-word phrases (e.g. "good
morning") so it can't mangle a legitimate doubled letter inside a real
word/phrase.
"""

import random
import re

_PUNCT_RE = re.compile(r"[!.?,;:~\s]+$")
_REPEATED_CHAR_RE = re.compile(r"(.)\1+")  # 2+ repeats of the same char, e.g. "ii", "yyy"

_PURE_GREETINGS = {
    "hi", "hey", "hy", "helo", "hlo", "halo", "yo", "sup",
    "hola", "hai", "heya", "hiya", "namaste", "namaskar", "gm",
    "good morning", "good afternoon", "good evening", "morning",
}

_GREETING_REPLIES = [
    "Hello! I'm doing great, thanks for asking — how can I help you today?",
    "Hi there! I'm all set and ready to go. What would you like to know?",
    "Hey! Good to see you. What can I help you with today?",
    "Hello! I'm here and ready — ask me anything about your documents, or anything else on your mind.",
]

_FAREWELL_GREETINGS = {"bye", "goodbye", "see you", "see ya", "cya", "bye bye", "take care"}
_FAREWELL_REPLIES = [
    "Goodbye! Feel free to come back anytime you have more questions.",
    "Bye! Have a great day — I'll be here whenever you need me.",
]

_THANKS_GREETINGS = {"thanks", "thank you", "thankyou", "thanx", "ty", "thanks a lot", "thank u"}
_THANKS_REPLIES = [
    "You're welcome! Let me know if there's anything else I can help with.",
    "Happy to help! Anything else you'd like to ask?",
]


def _normalize(message: str) -> str:
    text = message.strip().lower()
    text = _PUNCT_RE.sub("", text).strip()
    # Collapse repeated letters ("hiiiii" -> "hi", "heyyyy" -> "hey") --
    # but only for single-word messages, so a real multi-word phrase
    # like "good morning" (which has a legitimate doubled "o") is never
    # touched.
    if text and " " not in text:
        text = _REPEATED_CHAR_RE.sub(lambda m: m.group(1), text)
    return text


def match_canned_reply(message: str) -> str | None:
    """
    Returns a ready-made reply if `message` is PURE small talk with
    nothing else in it, else None -- meaning "run the normal RAG/LLM
    path for this message."
    """
    text = _normalize(message)
    if not text:
        return None
    if text in _PURE_GREETINGS:
        return random.choice(_GREETING_REPLIES)
    if text in _FAREWELL_GREETINGS:
        return random.choice(_FAREWELL_REPLIES)
    if text in _THANKS_GREETINGS:
        return random.choice(_THANKS_REPLIES)
    return None