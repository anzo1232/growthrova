import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {createRequire} from 'node:module';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
const require=createRequire(import.meta.url);
const built=await build({entryPoints:['src/GrowthrovaProductShell.jsx'],bundle:true,write:false,format:'cjs',platform:'node',jsx:'automatic',external:['react','react/jsx-runtime'],loader:{'.css':'empty'},logLevel:'silent'});
const module={exports:{}};
new Function('require','module','exports',built.outputFiles[0].text)(require,module,module.exports);
const Shell=module.exports.default;
test('connected presentation preserves real workspace controls and escapes business names',()=>{
 const html=renderToStaticMarkup(React.createElement(Shell,{businessName:'<img src=x onerror=alert(1)>',businessCount:2,signedIn:true},React.createElement('button',{type:'submit'},'Save my changes')));
 assert.ok(html.includes('Save my changes'));
 assert.ok(html.includes('&lt;img src=x onerror=alert(1)&gt;'));
 assert.ok(!html.includes('<img src=x'));
 assert.ok(html.includes('Workspace navigation'));
 for(const anchor of ['#gr-business','#gr-research','#gr-campaign'])assert.ok(html.includes('href="'+anchor+'"'));
 assert.ok(html.includes('businesses in your workspace'));
 assert.ok(!html.includes('Ledger Lane'));
});
test('signed-out presentation does not imply a connected business or populated workspace',()=>{
 const html=renderToStaticMarkup(React.createElement(Shell,{},React.createElement('form',null,'Sign in')));
 assert.ok(html.includes('Sign in to get started'));
 assert.ok(!html.includes('businesses in your workspace'));
 assert.ok(!html.includes('Your business, connected'));
 assert.ok(html.includes('Posting drafts are not published posts'));
});
