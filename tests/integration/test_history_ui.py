"""History navigation derives dossier state from the current listing fragment."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(not shutil.which('node'), reason='Node required for interaction checks')
def test_history_and_deep_link_synchronization():
    page = Path('docs/index.html').read_text(encoding='utf-8')
    functions = 'function closeModal' + page.split('function closeModal', 1)[1].split(
        "$('#modal-close').onclick", 1
    )[0]
    script = """
const assert = require('node:assert/strict');
let listings = [], currentModalListing = null, opens = 0, closes = 0, writes = 0;
const listeners = {};
const window = {
 location: {hash:'#listing-1',pathname:'/Collegeum/',search:'?view=cards'},
 addEventListener(name, callback) {listeners[name] = callback;}
};
const modal = {open:false,close(){this.open=false;closes++;}};
const history = {replaceState(_,__,url){writes++;assert.equal(url,'/Collegeum/?view=cards');
 window.location.hash='';}};
function openModal(item, options) {
 assert.equal(options.updateUrl,false);
 currentModalListing=item;modal.open=true;opens++;
}
""" + functions + """
syncModalWithUrl(); // Fragment exists before asynchronous data arrives.
assert.equal(opens,0);
assert.equal(window.location.hash,'#listing-1');
listings=[{id:1},{id:2}];
syncModalWithUrl();
assert.equal(currentModalListing.id,1);
listeners.hashchange();listeners.popstate();
assert.equal(opens,1); // Browser can emit both events for one navigation.
window.location.hash='';listeners.popstate();
assert.equal(modal.open,false);assert.equal(currentModalListing,null);
assert.equal(writes,0); // Back must not rewrite history.
window.location.hash='#listing-1';listeners.hashchange();
assert.equal(currentModalListing.id,1); // Forward restores the dossier.
window.location.hash='#listing-2';listeners.popstate();
assert.equal(currentModalListing.id,2);
for (const hash of ['#listing-999','#listing-bad','#section']) {
 window.location.hash=hash;listeners.hashchange();
 assert.equal(modal.open,false);assert.equal(window.location.hash,hash);
}
window.location.hash='#listing-2';listeners.popstate();
closeModal();assert.equal(window.location.hash,'');assert.equal(writes,1);
assert.equal(currentModalListing,null);
"""
    result = subprocess.run([shutil.which('node')], input=script,
                            capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr
    assert page.count('syncModalWithUrl();') == 1  # Called after successful data loading.
    assert "if (!modal.open && typeof modal.showModal === 'function')" in page
