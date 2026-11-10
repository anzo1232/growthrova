import test from 'node:test';
import assert from 'node:assert/strict';
import {restoreGrowthrovaBusiness, selectGrowthrovaBusiness} from '../src/lib/growthrovaNavigation.mjs';

const businesses = [{id:'first-business'}, {id:'second-business'}];
const saved = 'https://preview.invalid/growthrova.html?growthrovaBusiness=second-business&marketingDraft='+'a'.repeat(32);

test('reload restores the authorised second business and its exact campaign link', () => {
  const restored = restoreGrowthrovaBusiness(saved, businesses);
  assert.equal(restored.organisationId, 'second-business');
  assert.equal(restored.url.href, saved);
  assert.equal(restored.unavailable, false);
  // Reordering the list on a later reload must not change the saved scope.
  assert.equal(restoreGrowthrovaBusiness(saved, [...businesses].reverse()).url.href, saved);
});

test('switch, create and sign-out clear the previous campaign without changing other URL state', () => {
  for (const id of ['first-business', 'new-business', '']) {
    const next = selectGrowthrovaBusiness(saved+'&view=calendar#editor', id);
    assert.equal(next.searchParams.has('marketingDraft'), false);
    assert.equal(next.searchParams.get('growthrovaBusiness'), id || null);
    assert.equal(next.searchParams.get('view'), 'calendar');
    assert.equal(next.hash, '#editor');
  }
});

test('successful business correction resets the campaign link even for the same business', () => {
  const next = selectGrowthrovaBusiness(saved, 'second-business', {resetCampaign:true});
  assert.equal(next.searchParams.get('growthrovaBusiness'), 'second-business');
  assert.equal(next.searchParams.has('marketingDraft'), false);
});

test('revoked, foreign and unbound legacy links never restore a campaign under another business', () => {
  for (const allowed of [[businesses[0]], []]) {
    const next = restoreGrowthrovaBusiness(saved, allowed);
    assert.equal(next.unavailable, true);
    assert.equal(next.organisationId, allowed[0]?.id || '');
    assert.equal(next.url.searchParams.has('marketingDraft'), false);
  }
  const legacy = restoreGrowthrovaBusiness('https://preview.invalid/growthrova.html?marketingDraft='+'a'.repeat(32), businesses);
  assert.equal(legacy.organisationId, 'first-business');
  assert.equal(legacy.url.searchParams.has('marketingDraft'), false);
});
