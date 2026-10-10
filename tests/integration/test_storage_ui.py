"""Browser preferences must never gate loading or switching dashboard views."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(not shutil.which('node'), reason='Node required for preference checks')
@pytest.mark.parametrize('saved', ['ledger', 'grid', 'stats', None, '', 'broken', 'blocked'])
def test_view_read_and_write_failures_have_usable_defaults(saved):
    page = Path('docs/index.html').read_text(encoding='utf-8')
    read = 'function readViewPreference' + page.split('function readViewPreference', 1)[1].split(
        'let viewMode', 1)[0]
    change = 'function setViewMode' + page.split('function setViewMode', 1)[1].split(
        "$('#view-ledger-btn').onclick", 1)[0]
    script = f"const saved = {json.dumps(saved)};" + """
const assert = require('node:assert/strict');
const localStorage = {
 getItem() {if(saved==='blocked')throw new Error('Storage blocked'); return saved;},
 setItem() {throw new Error('Quota exceeded');}
};
const $ = () => ({classList:{toggle(){}},setAttribute(){}});
let draws = 0;
function draw() {draws++;}
""" + read + change + """
let viewMode = readViewPreference();
assert.equal(viewMode,['ledger','grid','stats'].includes(saved)?saved:'ledger');
for (const mode of ['ledger','grid','stats','invalid']) {
 setViewMode(mode);
 assert.equal(viewMode,mode==='invalid'?'ledger':mode);
}
assert.equal(draws,4);
"""
    subprocess.run([shutil.which('node'), '-e', script], check=True,
                   capture_output=True, text=True)


@pytest.mark.skipif(not shutil.which('node'), reason='Node required for preference checks')
@pytest.mark.parametrize('saved', ['system', 'dark', 'light', 'broken', None, 'blocked'])
def test_theme_initialization_survives_blocked_or_invalid_storage(saved):
    page = Path('docs/index.html').read_text(encoding='utf-8')
    head = re.findall(r'<script>(.*?)</script>', page, re.S)[0]
    script = f"const saved = {json.dumps(saved)};" + """
const assert = require('node:assert/strict');
const localStorage = {getItem() {if(saved==='blocked')throw new Error('Blocked');return saved;}};
const attrs = {};
const document = {documentElement:{setAttribute(name,value) {attrs[name]=value;}}};
const window = {matchMedia() {return {matches:true};}};
""" + head + """
const expected = ['system','dark','light'].includes(saved)?saved:'system';
assert.equal(attrs['data-theme'],expected);
assert.equal(attrs['data-active-theme'],expected==='system'?'dark':expected);
"""
    subprocess.run([shutil.which('node'), '-e', script], check=True,
                   capture_output=True, text=True)


@pytest.mark.skipif(not shutil.which('node'), reason='Node required for clipboard checks')
@pytest.mark.parametrize('outcome', ['success', 'rejected', 'missing', 'throws'])
def test_clipboard_failures_offer_selectable_text_without_claiming_success(outcome):
    page = Path('docs/index.html').read_text(encoding='utf-8')
    handler = "$('#modal-copy-btn').onclick" + page.split(
        "$('#modal-copy-btn').onclick", 1)[1].split('// Keyboard shortcuts', 1)[0]
    script = f"const outcome = {json.dumps(outcome)};" + """
const assert = require('node:assert/strict');
let currentModalListing = {id:42};
const window = {location:{origin:'https://example.org',pathname:'/Collegeum/'}};
const navigator = outcome==='missing'?{}:{clipboard:{writeText() {
 if(outcome==='throws')throw new Error('Blocked');
 return outcome==='success'?Promise.resolve():Promise.reject(new Error('Denied'));
}}};
let focused = false, selected = false;
const nodes = {
 '#modal-copy-btn':{}, '#modal-copy-fallback':{hidden:true},
 '#modal-copy-text':{focus(){focused=true;},select(){selected=true;}}
};
const $ = id => nodes[id];
const messages = [];
function toast(message) {messages.push(message);}
""" + handler + """
(async () => {
 await nodes['#modal-copy-btn'].onclick();
 if(outcome==='success') {
   assert.deepEqual(messages,['Link copied to clipboard']);
   assert.equal(nodes['#modal-copy-fallback'].hidden,true);
 } else {
   assert.ok(messages[0].includes('Could not copy'));
   assert.ok(!messages[0].includes('Link copied'));
   assert.equal(nodes['#modal-copy-fallback'].hidden,false);
   assert.equal(nodes['#modal-copy-text'].value,'https://example.org/Collegeum/#listing-42');
   assert.ok(focused && selected);
 }
})();
"""
    subprocess.run([shutil.which('node'), '-e', script], check=True,
                   capture_output=True, text=True)
