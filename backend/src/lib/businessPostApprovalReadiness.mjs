/** A daily PNG can be reviewed only against a loaded, matching quality report.
 * The server independently verifies the report hash and current kit identity. */
const STATIC_PICTURE_FORMATS=new Set([
 'image advert','image ad','image post','static image','static post','single image',
 'photo','photo post','graphic','static graphic','educational graphic',
 'promotional graphic','text and image post'
]);

export function postApprovalReadiness({post,qualityReport,manifest}={}){
 if(!post)return {ready:false,message:'Choose a saved post to review.'};
 const format=String(post.format||'').trim().toLowerCase().replace(/\s+/g,' ');
 if(!STATIC_PICTURE_FORMATS.has(format))return {ready:false,message:'This format needs its complete matching media before approval. A single picture preview is not sufficient.'};
 if(!/^[a-f0-9]{64}$/.test(manifest?.fileSHA256?.['creative-quality-report.json']||''))
  return {ready:false,message:'The saved quality review has not loaded. Approval stays unavailable until it can be checked.'};
 if(!Array.isArray(qualityReport?.posts))return {ready:false,message:'The saved quality review has not loaded. Approval stays unavailable until it can be checked.'};
 const matches=qualityReport.posts.filter(row=>row&&Number.isInteger(row.day)&&row.day===post.day);
 if(matches.length!==1||matches[0].channel!==post.channel||matches[0].format!==post.format)
  return {ready:false,message:'The quality review does not match this saved post. Refresh the current campaign before approval.'};
 const review=matches[0];
 if(review.status!=='awaiting_human_creative_review'||!Array.isArray(review.issues)||review.issues.length)
  return {ready:false,message:'This post needs its quality issues resolved before approval.'};
 return {ready:true,message:'Basic checks passed. Review the actual picture, wording and usage rights.'};
}
