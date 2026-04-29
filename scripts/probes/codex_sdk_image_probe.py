from __future__ import annotations

import json
from pathlib import Path

from backend.codex_utils import run_codex


REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGE_PATH = REPO_ROOT / "imagen.jpg"
RESULT_PATH = REPO_ROOT / "codex_sdk_image_probe_result.json"


def main() -> None:
    if IMAGE_PATH.exists():
        raise SystemExit(f"Refusing to overwrite existing file: {IMAGE_PATH}")

    prompt = f"""
We are testing whether the Codex SDK/app-server environment has native image
generation available through the ChatGPT/Codex login.

Task:
- If you have a native image generation tool available in this Codex run, use
  that native tool to generate a JPG image about "un contador argentino usando
  un dashboard moderno de automatizacion para WhatsApp" and save it exactly at:
  {IMAGE_PATH}
- Do not use OpenAI API keys, the OpenAI Images API, DALL-E/GPT Image API calls,
  local drawing libraries, SVG conversion, screenshots, downloads, or placeholder
  files. This is only a test for native image generation availability inside
  Codex SDK/app-server.
- If no native image generation tool is available, do not create the image.
  Explain that clearly in the final answer and start the final answer with:
  NO_NATIVE_IMAGE_TOOL

After the attempt, state whether {IMAGE_PATH.name} was created.
""".strip()

    result = run_codex(prompt)

    payload = {
        "final_response": result.final_response,
        "image_path": str(IMAGE_PATH),
        "image_exists": IMAGE_PATH.exists(),
        "image_size_bytes": IMAGE_PATH.stat().st_size if IMAGE_PATH.exists() else 0,
        "items_count": result.items_count,
    }
    RESULT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
