import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const ui=readFileSync(new URL('../src/BusinessWorkspace.jsx',import.meta.url),'utf8');
test('owner media intake leads to real authenticated video studio and brand kit',()=>{
 assert.match(ui,/aria-label="Customer media intake"/);
 assert.match(ui,/to="\/business\/media">Upload and review business videos/);
 assert.match(ui,/id="biz-logo-file"/);
});
test('intake makes no false promise of full photo upload or immediate publishing approval',()=>{
 assert.match(ui,/general photo-library upload is not available/);
 assert.match(ui,/Uploading does not approve footage/);
 assert.doesNotMatch(ui,/Your verified brand logo has been saved/);
});
