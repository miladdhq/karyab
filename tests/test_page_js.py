"""The page script must parse.

A syntax error anywhere in it stops every handler from running: the page
renders, the queue silently stays empty, and nothing in the server logs says
why. That happened — a string replacement hit `loadQueue();` in two places and
spliced a block into the middle of a function — so it is now checked.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "karyab" / "web"
APP_JS = WEB / "static" / "app.js"
INDEX = WEB / "index.html"


def test_the_script_lives_in_a_file_not_inline():
    # Inline script cannot be syntax-checked and was edited into corruption.
    html = INDEX.read_text(encoding="utf-8")
    assert "/static/app.js" in html
    assert not re.search(r"<script>\s*\w", html), "no inline script blocks"


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_the_script_parses():
    result = subprocess.run(["node", "--check", str(APP_JS)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_no_top_level_name_is_declared_twice():
    """Four copies of the same block once shipped; the duplicate `let` threw."""
    js = APP_JS.read_text(encoding="utf-8")
    names = re.findall(r"^(?:let|const|function|async function)\s+(\w+)", js, re.M)
    dupes = {n for n in names if names.count(n) > 1}
    assert not dupes, f"declared more than once at top level: {sorted(dupes)}"


def test_every_element_the_script_touches_exists_in_the_page():
    """A renamed id makes the handler silently never fire."""
    js = APP_JS.read_text(encoding="utf-8")
    html = INDEX.read_text(encoding="utf-8")
    for element_id in sorted(set(re.findall(r"\$\('#([A-Za-z0-9_-]+)'\)", js))):
        assert f'id="{element_id}"' in html, f"#{element_id} is used but not in the page"
