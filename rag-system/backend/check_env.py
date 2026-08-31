from app.config import get_settings

s = get_settings()
print("public:", repr(s.langfuse_public_key))
print("secret set:", bool(s.langfuse_secret_key))
print("host:", s.langfuse_host)

from app.config import get_settings
from langfuse import Langfuse

s = get_settings()
lf = Langfuse(
    public_key=s.langfuse_public_key,
    secret_key=s.langfuse_secret_key,
    host=s.langfuse_host,
)
print("auth check:", lf.auth_check())