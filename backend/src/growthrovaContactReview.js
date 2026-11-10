import {matchesEnquiry} from './growthrovaLeadRegister.js';

export const enquiryReviews={active:'Active enquiries',stale:'New or Contacted without an update for seven days',
  unplanned:'Active without an open human action',overdue:'Overdue human actions',today:'Human actions due today'};
export const actionTimingLabels={overdue:'Overdue',today:'Due today',upcoming:'Upcoming',undated:'No due date'};

export function matchesReview(lead,review){
  if(!review)return true;
  const saved=lead.review;
  if(!saved)return false;
  return ['active','stale','unplanned'].includes(review)?saved[review]===true:
    ['overdue','today'].includes(review)&&saved.actionTiming===review;
}

export function contactReview(contacts,filters={}){
  const {query='',status='',source='',campaign='',review='',assignment='',sort='newest'}=filters;
  const rows=contacts.filter(lead=>{
    if(campaign&&lead.campaignId!==campaign||!matchesReview(lead,review))return false;
    if(assignment==='unassigned'&&(!lead.review||lead.review.responsiblePerson)||
       assignment==='assigned'&&!lead.review?.responsiblePerson)return false;
    return matchesEnquiry({...lead,data:{...lead.data,responsiblePerson:[lead.campaignName,lead.review?.responsiblePerson].filter(Boolean).join('\n')}},
      {query,status,source});
  });
  rows.sort((a,b)=>(sort==='name'?a.data.name.localeCompare(b.data.name):
    sort==='oldest'?a.updated-b.updated:b.updated-a.updated)||a.id.localeCompare(b.id));
  return rows;
}
