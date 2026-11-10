import {businessFactsReviewed,strategyConfirmed} from './businessOwnerStrategy.mjs';
import {marketingCopyIssue} from './businessCopyReadiness.mjs';
/** Explain the actual offline customer workflow without implying production success.
 * This is a UI view model, never a media, owner-approval or publishing authority.
 * Asset count is a count of existing image attempts, not verified usable media.
 */
export function summariseJourney(document,{assetCount=null}={}){
  const facts=Array.isArray(document?.observedFacts)
    ? document.observedFacts.filter(f=>typeof f==='string'&&f.trim()):[];
  const posts=Array.isArray(document?.posts)?document.posts:[];
  const shortlisted=Array.isArray(document?.editorialShortlist?.candidates)
    ? document.editorialShortlist.candidates:[];
  const pictures=Number.isSafeInteger(assetCount)&&assetCount>=0?assetCount:0;
  const confirmed=strategyConfirmed(document);
  const ownerBrief=['audience','offer','callToAction','constraints'].every(key=>
    typeof document?.ownerStrategy?.[key]==='string'&&document.ownerStrategy[key].trim());
  const hasEvidence=facts.length>0||ownerBrief;
  const factsReviewed=businessFactsReviewed(document);
  const hasGoal=typeof document?.goal==='string'&&document.goal.trim().length>0;
  const reviewed=posts.filter(x=>x?.status==='copy_reviewed'&&!marketingCopyIssue(x,document.business)).length;
  const status=(id,title,value,detail)=>({id,title,status:value,detail});
  const steps=[
    status('research','Know the business',hasEvidence?'verify':'blocked',
      facts.length?`${facts.length} website observation${facts.length===1?'':'s'} saved; ${factsReviewed?'owner decisions recorded; independent verification remains outstanding.':'confirm, correct or exclude each observation in your strategy below.'}`
      :ownerBrief?`Owner-supplied brief; no website observations. ${confirmed?'Owner confirmation recorded; independent verification remains outstanding.':'Review and confirm your supplied details below.'}`
      :'Business evidence required before making claims.'),
    status('strategy','Find the angle',hasEvidence&&hasGoal?'draft':'blocked',
      confirmed?'Owner confirmed the current brief locally; independent claim verification and media approval remain outstanding.':hasEvidence&&hasGoal?`Goal: ${document.goal}. Strategy is a draft until first-party offers and buyer concerns are validated.`
      :'Add business evidence and a goal.'),
    status('plan','Plan the content',shortlisted.length||posts.length?(reviewed>0&&reviewed===posts.length?'review':'draft'):'blocked',
      shortlisted.length&&!confirmed?`${shortlisted.length} directions for asset review; the bulk posting calendar is withheld.`
      :posts.length?`${posts.length} draft posts · ${reviewed} copy-reviewed. Neither copy review nor draft count is publication approval.`
      :'No source-backed content planned yet.'),
    status('production','Create & inspect','waiting',
      pictures?`${pictures} image attempts recorded; verify actual output bytes, authenticity, rights and visual quality before review.`
      :'Awaiting genuine business media and separately authorised production.'),
    status('approval','Your sign-off','waiting',
      'Owner decision, source evidence and finished-media quality checks are still required.'),
    status('delivery','Schedule & improve','not_connected',
      'No connected publishing or performance-measurement loop in this local preview.'),
  ];
  const nextAction=!hasEvidence?'Add evidence for the business before creating a campaign.'
      :!facts.length&&!confirmed?'Review and confirm your owner-supplied brief before requesting writing.'
      :!facts.length?'Review copy against your confirmed owner-supplied brief, then supply authentic brand media.'
      :!factsReviewed?'Review each website observation in your strategy: confirm, correct or exclude it before preparing authentic media.'
      :shortlisted.length&&!pictures?'Supply authentic business assets and review the proposed directions.'
      :pictures?'Verify actual output bytes and review media for realism, rights and brand accuracy before owner sign-off.'
      :'Review sourced business claims and draft copy, then supply authentic brand media.';
  return {steps,nextAction,published:0,measured:false};
}
