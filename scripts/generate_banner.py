"""Generate docs/assets/banner.png with the OpenAI Images API.

Usage: python scripts/generate_banner.py   (needs OPENAI_API_KEY in env or .env)
"""
import base64
import os
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "assets" / "banner.png"
MODEL = "gpt-image-2"
PROMPT = (
    "Wide cheerful flat-illustration banner for a project called 'Support Ticket Pipeline'. "
    "A friendly little robot sorts colourful envelopes (support tickets) into three labelled "
    "mailboxes, with a small open book (the knowledge base) beside it and a green safety "
    "shield with a check mark. Soft pastel blue and yellow background, rounded shapes, "
    "playful and clean, no real brand logos, no readable small text except the title "
    "'Support Ticket Pipeline' in large friendly letters."
)


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def main() -> None:
    load_env()
    img = OpenAI().images.generate(model=MODEL, prompt=PROMPT, size="1536x1024", n=1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(base64.b64decode(img.data[0].b64_json))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
