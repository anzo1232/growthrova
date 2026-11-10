export const careTaskLabels={retention:'Retention',review:'Review request'};
export const careTaskFields={action:'Human action',responsiblePerson:'Responsible person',dueDate:'Due date (UTC)',state:'Task state',channel:'Prepared channel',wording:'Prepared wording'};
export const emptyCareTask=()=>({action:'',responsiblePerson:'',dueDate:'',state:'open',channel:'unspecified',wording:''});
export const emptyCustomerCare=()=>({booking:{state:'unrecorded',scheduledDate:'',outcomeDate:'',reference:'',evidence:''},retention:emptyCareTask(),review:emptyCareTask()});

// Only task fields are editable here. Booking and automation metadata stay on
// the full saved snapshot, including historically absent optional fields.
export function editableCareTasks(care){
  return Object.fromEntries(Object.keys(careTaskLabels).map(kind=>[kind,{...(care?.[kind]||emptyCareTask())}]));
}
export function careTaskChanges(care,draft){
  if(!draft)return [];
  const original=editableCareTasks(care);
  return Object.keys(careTaskLabels).flatMap(kind=>Object.keys(careTaskFields)
    .filter(key=>original[kind][key]!==draft[kind][key])
    .map(key=>({kind,key,before:original[kind][key],after:draft[kind][key]})));
}
