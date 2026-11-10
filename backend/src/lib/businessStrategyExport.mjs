/** Readable saved planning context; owner reviews are never independent verification. */
import {BUSINESS_GOALS} from './businessConfig.mjs';
import {businessFactReview, strategyFields, strategyConfirmed, strategyEvidenceState} from './businessOwnerStrategy.mjs';

export function marketingStrategyText(doc, saved) {
  const strategy=doc.ownerStrategy||{};
  const lines=[
    'Saved business strategy — '+doc.name,
    'Campaign: '+saved.id,
    'Revision: '+saved.revision,
    'Business: '+doc.business,
    'Website: '+(doc.sourceUrl||'Not supplied'),
    'Goal: '+(BUSINESS_GOALS.find(goal=>goal.id===doc.goal)?.label||doc.goal),
    'Calendar start: '+(doc.calendarStartDate||'Not selected'),
    'Strategy review: '+(strategyConfirmed(doc)?'Owner confirmed this saved context.':'Current context needs owner review.'),
    '',
    'Planning handoff only. Owner statements and website excerpts are not independently verified.',
    'This download grants no media rights, publishing, messaging or spending authority.',
    '', 'Owner strategy',
  ];
  const labels={audience:'Audience',offer:'Offer',positioning:'Positioning',callToAction:'Next step',constraints:'Constraints'};
  for (const key of Object.keys(strategyFields)) {
    lines.push('', labels[key]+': '+(strategy[key]||'Not supplied'));
    const state=strategyEvidenceState(doc,key);
    lines.push('Source review: '+state.detail);
    // Retain stale references as history, without relabelling them current.
    const link=strategy.evidenceLinks?.[key];
    if (link) lines.push('Saved source ('+state.status+'): '+link.sourceUrl, 'Saved excerpt: '+link.quote);
  }
  lines.push('', 'Website observations and owner decisions');
  if (!doc.observedFacts?.length) lines.push('No saved website observations. Owner statements still require verification.');
  for (const [index,observation] of (doc.observedFacts||[]).entries()) {
    const review=businessFactReview(doc,index);
    lines.push('', 'Observation '+(index+1)+': '+observation,
      'Original page: '+(doc.observedFactSources?.[index]||'Not retained for this observation'),
      'Owner decision: '+(review?.decision||'pending'));
    if (review?.decision==='corrected') lines.push('Owner correction (not website evidence): '+review.statement);
    if (review?.decision==='excluded') lines.push('Excluded from reviewed business details.');
  }
  const historical=(strategy.factDecisions||[]).filter(review=>businessFactReview(doc,review.index)!==review);
  if (historical.length) {
    lines.push('', 'Historical decisions — do not apply to current observations');
    for (const review of historical) lines.push('', 'Original observation: '+review.observation,
      'Past decision: '+review.decision, ...(review.statement?['Past owner correction: '+review.statement]:[]));
  }
  lines.push('', 'Saved website audit', doc.websiteAuditText||'No saved audit.', '');
  return lines.join('\n');
}
