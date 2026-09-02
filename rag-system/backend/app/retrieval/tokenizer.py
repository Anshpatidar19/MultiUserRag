
import re

from nltk.stem import PorterStemmer

_TOKEN_RE = re.compile(r"[a-z0-9]+")


_stemmer = PorterStemmer()


def tokenize(text: str) -> list[str]:
    
    words = _TOKEN_RE.findall(text.lower())
    return [_stemmer.stem(w) for w in words]