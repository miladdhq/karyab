"""The auto-mode toggle must not be inverted.

A checkbox's `checked` is ALREADY flipped by the browser when `click` fires,
so it reports the state the user is asking for, not the state before. An
earlier version read it as the current state: clicking to turn auto ON
reported true, that was treated as "already on", and it turned straight back
off. Auto mode could never be enabled, and nothing reported an error.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

APP_JS = Path(__file__).resolve().parents[1] / "karyab" / "web" / "static" / "app.js"


def test_the_toggle_handler_goes_through_the_named_helper():
    """Guard the fix itself: an inline `if (checked)` is how this regressed."""
    js = APP_JS.read_text(encoding="utf-8")
    start = js.index("$('#autoOn').onclick")
    handler = js[start:start + 400]
    assert "autoToggleIntent" in handler, "the handler must go through the helper"


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_clicking_an_off_box_asks_to_turn_auto_on(tmp_path):
    assert _intent(tmp_path, "true") == "confirm_on"


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_clicking_an_on_box_turns_auto_off(tmp_path):
    assert _intent(tmp_path, "false") == "turn_off"


def _intent(tmp_path: Path, checked: str) -> str:
    """Run the real helper out of app.js under node."""
    source = APP_JS.read_text(encoding="utf-8")
    helper = re.search(r"function autoToggleIntent[\s\S]*?\n}", source)
    assert helper, "autoToggleIntent is missing from app.js"

    script = tmp_path / "intent.js"
    script.write_text(
        f"{helper.group(0)}\nconsole.log(autoToggleIntent({checked}));\n",
        encoding="utf-8",
    )
    result = subprocess.run(["node", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()
