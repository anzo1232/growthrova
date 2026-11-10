import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import postcss from 'postcss';

// The board's shared editor paragraphs are 10px. Writing needs an explicit
// scoped override, including comparison panels and the wrapped storyboard.
// Actual cascade/layout/interaction assertions run in the trusted browser gate.
const css=postcss.parse(readFileSync('src/BusinessMarketingBoard.css','utf8'));
function declaration(selector,property,stylesheet=css){
 let value;
 stylesheet.walkRules(rule=>{
  if(rule.selectors.includes(selector))rule.walkDecls(property,decl=>{value=decl.value;});
 });
 return value;
}
test('campaign writing has legible body and editable text instead of inheriting miniature editor copy',()=>{
 const source=readFileSync('src/GrowthrovaCampaignWriter.jsx','utf8');
 for(const element of ['p','pre','blockquote','textarea','select']){
  const selector='.bmb .bmb-writer '+element;
  const inherited=element==='p'?declaration('.bmb-editor p','font-size'):undefined;
  assert.equal(declaration(selector,'font-size')||inherited,'16px',selector+' must support reading and mobile editing');
  assert.ok(Number(declaration(selector,'line-height'))>=1.5,selector+' needs readable line spacing');
 }
 assert.ok(source.includes('className="bmb-editor bmb-writer"'),'Apply readable styles to the real writing panel');
 assert.equal(declaration('.bmb .bmb-writer select','min-height'),'44px',
  'Native selects need readable control height even when Chromium computes line-height as normal');
 for(const element of ['p','pre','blockquote']){
  assert.equal(declaration('.bmb .bmb-writer '+element,'overflow-wrap'),'anywhere','Long words and source excerpts must wrap');
 }
});
test('connected product body typography preserves the campaign reading minimum',()=>{
 const shell=postcss.parse(readFileSync('src/GrowthrovaProductShell.css','utf8'));
 // The product shell's more-specific body rule overrides board editor styles.
 // Keep this contract alongside the browser's computed-style/layout checks.
 for(const element of ['p','li']){
  const selector='.gr-product .bmb '+element;
  assert.ok(parseFloat(declaration(selector,'font-size',shell))>=16,
   selector+' must not shrink campaign words below the mobile reading minimum');
  assert.ok(Number(declaration(selector,'line-height',shell))>=1.5);
 }
});
