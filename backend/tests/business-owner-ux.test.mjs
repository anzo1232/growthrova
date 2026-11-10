import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const read=file=>readFileSync(new URL('../src/'+file,import.meta.url),'utf8');
test('first-time owner sees one website action and plain-English promise',()=>{
 const front=read('BusinessAgencyPreview.jsx');
 assert.match(front,/Your marketing, sorted\./);
 assert.match(front,/Build my marketing/);
 assert.match(front,/posts, pictures, a short video/i);
});
test('download and review labels make sense without marketing training',()=>{
 const output=read('BusinessAgencyDeliverables.jsx');
 const editor=read('BusinessMarketingBoard.jsx');
 assert.match(output,/Your posts, pictures &amp; video|Your posts, pictures & video/);
 assert.match(output,/Download all my marketing/);
 assert.match(output,/How to get more enquiries/);
 assert.match(editor,/Your 30 posts/);
 assert.match(editor,/Change the words/);
 assert.doesNotMatch(editor,/CREATIVE DIRECTOR/);
});
test('customer can inspect actual website picture candidates without falsely approving rights',()=>{
 const editor=read('BusinessMarketingBoard.jsx');
 const picker=read('BusinessWebsitePictures.jsx');
 assert.match(editor,/<BusinessWebsitePictures/);
 assert.match(picker,/Pictures found on your website/);
 assert.match(picker,/Permission to use these pictures is not confirmed/);
 assert.match(picker,/ownerConfirmed:true/);
});
