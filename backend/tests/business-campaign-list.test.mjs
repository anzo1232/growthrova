import assert from 'node:assert/strict';
import {reconcileCampaignList} from '../src/lib/businessCampaignList.mjs';

const saved=(id,revision,name=id)=>({id,revision,name});
const old=saved('older',1),created=saved('new',1,'Owner saved campaign');
// Initial loading started before creation. The persisted result must stay
// selectable alongside campaigns returned by that older request.
assert.deepEqual(reconcileCampaignList([old],[created],[]),[created,old]);
// An acknowledgement updates the title/revision while a refresh is in flight.
const edited=saved('older',2,'Owner correction');
assert.deepEqual(reconcileCampaignList([old],[edited],[old]),[edited]);
// A genuinely newer server revision wins over the intervening local save.
const newer=saved('older',3,'Later correction');
assert.deepEqual(reconcileCampaignList([newer],[edited],[old]),[newer]);
// A later refresh still reflects deletion; old unchanged summaries are not
// retained forever. Foreign/unlisted IDs are never manufactured.
assert.deepEqual(reconcileCampaignList([], [old,created], [old,created]),[]);
assert.deepEqual(reconcileCampaignList([old], [created], [created]),[old]);
// More than one save may finish during the same delayed list request.
assert.deepEqual(reconcileCampaignList([old],[created,edited],[old]),[created,edited]);
assert.deepEqual(reconcileCampaignList([edited],[edited],[old]),[edited]);
console.log('PASS: delayed campaign lists, save/revision reconciliation and deletion refresh');
