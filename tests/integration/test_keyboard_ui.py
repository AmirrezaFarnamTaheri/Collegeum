"""Custom listing activators support keyboard input without duplicate activation."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(not shutil.which('node'), reason='Node required for interaction checks')
def test_keyboard_activation_and_render_wiring():
    page = Path('docs/index.html').read_text(encoding='utf-8')
    body = page.split('function wireKeyboardActivation', 1)[1].split('// Render Analytics', 1)[0]
    helper = 'function wireKeyboardActivation' + body
    script = helper + """
const assert = require('node:assert/strict');
let clicks=0, prevented=0;
const element={click(){clicks++;}};
wireKeyboardActivation(element);
for (const key of ['Enter',' ']) {
 element.onkeydown({key,target:element,repeat:false,preventDefault(){prevented++;}});
 element.onkeydown({key,target:element,repeat:true,preventDefault(){prevented++;}});
}
element.onkeydown({key:'Enter',target:{},preventDefault(){throw Error('child intercepted');}});
element.onkeydown({key:'Escape',target:element,preventDefault(){throw Error('wrong key');}});
assert.equal(clicks,2);
assert.equal(prevented,4);
"""
    result = subprocess.run([shutil.which('node')], input=script,
                            capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr
    assert 'wireKeyboardActivation(btn);' in page
    assert 'wireKeyboardActivation(c);' in page
    assert 'class="job-card" data-open="${r.id}" tabindex="0" role="button"' in page
    assert '.job-card:focus-visible' in page
