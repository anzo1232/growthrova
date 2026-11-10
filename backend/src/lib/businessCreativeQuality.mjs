/** Premium creative brief gate. Prevent generic/fabricated content being marked ready. */
export function assessCreativeReadiness({brandAssets=[],referenceAssets=[],offerVerified=false,claimsVerified=false,artDirection='',layoutPlan='',ownerApproved=false}={}){
 const issues=[];
 if(!Array.isArray(brandAssets)||brandAssets.length===0)issues.push('Brand assets or approved design system required');
 if(!Array.isArray(referenceAssets)||referenceAssets.length===0)issues.push('Real product, service or style reference required');
 if(!offerVerified)issues.push('Offer and pricing must be verified');
 if(!claimsVerified)issues.push('Claims and evidence require review');
 if(typeof artDirection!=='string'||artDirection.trim().length<25)issues.push('Specific art direction required');
 if(typeof layoutPlan!=='string'||layoutPlan.trim().length<15)issues.push('Typography, composition and placement need a layout plan');
 if(!ownerApproved)issues.push('Owner approval required before publication');
 return {readyForPublication:issues.length===0,readyForGeneration:issues.filter(x=>x!=='Owner approval required before publication').length===0,issues,
  creativeStandard:'Premium brand fidelity, authentic subject matter, controlled typography, no fabricated testimonials or misleading imagery'};
}
