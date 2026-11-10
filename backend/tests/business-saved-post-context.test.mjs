import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {createRequire} from 'node:module';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';

const require=createRequire(import.meta.url);
async function render(post){
 const bundle=await build({entryPoints:['src/BusinessSavedPostContext.jsx'],bundle:true,write:false,
  format:'cjs',platform:'node',jsx:'automatic',external:['react','react/jsx-runtime'],logLevel:'silent'});
 const module={exports:{}};
 new Function('require','module','exports',bundle.outputFiles[0].text)(require,module,module.exports);
 return renderToStaticMarkup(React.createElement(module.exports.default,{post}));
}

test('media review shows the complete saved words and CTA without rewriting or interpreting markup',async()=>{
 const post={day:2,theme:'Service detail',copyDraft:'First line.\n\nSecond line <script>alert(1)</script>.',
  callToAction:'Ask about <availability> & timing.',status:'copy_reviewed'};
 const before=structuredClone(post),html=await render(post);
 assert.match(html,/aria-label="Saved words for day 2"/);
 assert.match(html,/white-space:pre-wrap/);
 assert.ok(html.includes('First line.\n\nSecond line &lt;script&gt;alert(1)&lt;/script&gt;.'));
 assert.ok(html.includes('Ask about &lt;availability&gt; &amp; timing.'));
 assert.match(html,/Call to action/);
 assert.match(html,/not rendered into this media preview/);
 assert.match(html,/not independent verification/);
 assert.deepEqual(post,before);
});
test('missing copy or CTA is explicit and whole-library inspection has no invented day context',async()=>{
 const html=await render({day:3,copyDraft:'  ',callToAction:'',status:'draft'});
 assert.match(html,/No saved post words yet/);
 assert.match(html,/No saved call to action yet/);
 assert.match(html,/Words have not been marked checked/);
 assert.equal(await render(null),'');
});
