import assert from 'node:assert/strict';
import {marketingCopyIssue} from '../src/lib/businessCopyReadiness.mjs';
const post={copyDraft:'Bring your bicycle to our workshop for servicing.',graphicText:'Still on your to-do list?',callToAction:'Contact the workshop'};
assert.equal(marketingCopyIssue(post,'QA Workshop'),'','A question is valid graphic copy beside a complete caption and CTA');
assert.ok(marketingCopyIssue({...post,copyDraft:'Ready for something different?'},'QA Workshop'),'Question-only full captions remain held');
assert.ok(marketingCopyIssue({...post,callToAction:''},'QA Workshop'),'A CTA remains required');
assert.ok(marketingCopyIssue({...post,graphicText:'Visual direction: add a receipt'},'QA Workshop'),'Internal instructions remain held');
assert.equal(post.graphicText,'Still on your to-do list?','Do not silently rewrite the selected question');
