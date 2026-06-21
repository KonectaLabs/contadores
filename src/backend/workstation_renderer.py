"""Runtime renderer for Workstation static page previews."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


RenderStage = Literal["playwright_import", "browser_launch", "record_video", "ffmpeg"]


@dataclass
class WorkstationRenderError(RuntimeError):
    """Structured renderer failure that is still readable as an exception."""

    stage: RenderStage
    message: str
    stdout: str = ""
    stderr: str = ""

    def __str__(self) -> str:
        return f"{self.stage}: {self.message}"

    def as_dict(self) -> dict[str, str]:
        return {
            "stage": self.stage,
            "message": self.message,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


def check_workstation_renderer_dependencies() -> dict[str, Any]:
    """Report renderer dependencies without rendering a page."""
    playwright_ok = True
    playwright_error = ""
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError as error:
        playwright_ok = False
        playwright_error = str(error)

    ffmpeg_path = shutil.which("ffmpeg")
    return {
        "playwright": {"ok": playwright_ok, "error": playwright_error},
        "ffmpeg": {"ok": ffmpeg_path is not None, "path": ffmpeg_path or ""},
    }


def render_landing_page_video_sync(*, index_path: Path, output_path: Path) -> None:
    """Record a desktop scroll preview of a static landing page as MP4."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise WorkstationRenderError(
            stage="playwright_import",
            message="playwright is required to render Workstation preview videos",
        ) from error

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(
                    viewport={"width": 1440, "height": 900},
                    record_video_dir=str(temp_path),
                    record_video_size={"width": 1440, "height": 900},
                )
                page = context.new_page()
                page.goto(index_path.resolve().as_uri(), wait_until="networkidle")
                page.wait_for_timeout(800)
                page.evaluate(
                    """
                    async () => {
                      const max = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
                      const root = document.documentElement;
                      const previousBehavior = root.style.scrollBehavior;
                      root.style.scrollBehavior = "auto";
                      window.scrollTo(0, 0);
                      await new Promise((resolve) => setTimeout(resolve, 700));

                      const durationMs = Math.min(18000, Math.max(9500, max / 0.55));
                      const start = performance.now();
                      await new Promise((resolve) => {
                        const step = (now) => {
                          const progress = Math.min(1, (now - start) / durationMs);
                          window.scrollTo(0, Math.round(max * progress));
                          if (progress < 1) {
                            window.requestAnimationFrame(step);
                            return;
                          }
                          resolve();
                        };
                        window.requestAnimationFrame(step);
                      });

                      await new Promise((resolve) => setTimeout(resolve, 900));
                      root.style.scrollBehavior = previousBehavior;
                    }
                    """
                )
                context.close()
                browser.close()
        except WorkstationRenderError:
            raise
        except Exception as error:
            raise WorkstationRenderError(stage="browser_launch", message=str(error) or "browser launch failed") from error

        webm_files = sorted(temp_path.glob("*.webm"))
        if not webm_files:
            raise WorkstationRenderError(stage="record_video", message="Playwright did not record a preview video")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(webm_files[0]),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-an",
            str(output_path),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            error_text = (completed.stderr or completed.stdout or "ffmpeg failed").strip()
            raise WorkstationRenderError(
                stage="ffmpeg",
                message=f"ffmpeg could not create preview video: {error_text}",
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
