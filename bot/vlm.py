"""
bot/vlm.py — Vision Language Model через z-ai CLI.

На ПК без z-ai CLI методы возвращают None (fallback на другие методы).
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import shutil
from typing import Optional, Tuple

import cv2
import numpy as np

from bot.clogger import log


def _check_zai_cli() -> Optional[str]:
    """Проверить что z-ai CLI установлен."""
    zai_path = shutil.which("z-ai")
    if zai_path is None:
        return None
    return zai_path


def vlm_ask(img_bgr: np.ndarray, question: str, timeout: int = 30) -> Optional[str]:
    """
    Спросить VLM про изображение. Вернуть текст ответа или None.
    """
    tmp_path = None
    try:
        zai_path = _check_zai_cli()
        if zai_path is None:
            return None

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp_path = f.name
        cv2.imwrite(tmp_path, img_bgr)

        result = subprocess.run(
            [zai_path, "vision", "-p", question, "-i", tmp_path],
            capture_output=True, text=True, timeout=timeout
        )

        if result.returncode != 0:
            return None

        output = result.stdout.strip()
        if not output:
            return None

        if output.startswith("{"):
            import json
            try:
                data = json.loads(output)
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                return content.strip() if content else None
            except Exception:
                pass

        return output

    except subprocess.TimeoutExpired:
        return None
    except FileNotFoundError:
        return None
    except Exception as e:
        log(f"VLM: ошибка: {e}", level="WARNING")
        return None
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
