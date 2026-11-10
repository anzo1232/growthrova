import {careTaskLabels} from './growthrovaCareTasks.js';

export const repeatRuleFields={enabled:'Repeat preparation',startDate:'First date (UTC)',intervalDays:'Repeat interval (days)',action:'Human action',responsiblePerson:'Responsible person',channel:'Prepared channel',wording:'Prepared wording'};
export const backgroundCareFields={enabled:'Background preparation',throughDate:'Final eligible due date (UTC)',maxOccurrences:'Maximum occurrences per unchanged rule'};
const emptyRule=()=>({enabled:false,startDate:'',intervalDays:30,action:'',responsiblePerson:'',channel:'unspecified',wording:''});
export function editableCareRules(care){
  return {repeatRules:Object.fromEntries(Object.keys(careTaskLabels).map(kind=>[kind,{...emptyRule(),...care?.repeatRules?.[kind]}])),
    background:{enabled:false,throughDate:'',maxOccurrences:12,...care?.background}};
}
export function careRuleChanges(care,draft){
  if(!draft)return [];
  const before=editableCareRules(care);
  return [
    ...Object.entries(careTaskLabels).flatMap(([kind,label])=>Object.entries(repeatRuleFields)
      .filter(([key])=>before.repeatRules[kind][key]!==draft.repeatRules[kind][key])
      .map(([key,title])=>({key:kind+'.'+key,label:label+' repeat · '+title,before:before.repeatRules[kind][key],after:draft.repeatRules[kind][key]}))),
    ...Object.entries(backgroundCareFields).filter(([key])=>before.background[key]!==draft.background[key])
      .map(([key,label])=>({key:'background.'+key,label,before:before.background[key],after:draft.background[key]}))];
}
// Only changed optional settings are added. Progress is retained on the saved
// snapshot and remains under the existing server-owned progress validation.
export function reviewedCareRules(care,draft){
  const changes=careRuleChanges(care,draft),patch={};
  if(changes.some(row=>!row.key.startsWith('background.')))patch.repeatRules=draft.repeatRules;
  if(changes.some(row=>row.key.startsWith('background.')))patch.background=draft.background;
  return patch;
}
