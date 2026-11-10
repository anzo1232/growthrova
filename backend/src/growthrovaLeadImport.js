// Bounded local CSV preparation. The private lead route remains authoritative.
export const importLimits={name:160,email:254,phone:40,source:160,sourceReference:512,
  permissionNotes:1000,qualification:1000,booking:300,notes:2000,responsiblePerson:160,
  nextAction:1000,actionDueDate:10,followUpDraft:4000};
const choices={status:['new','contacted','qualified','booked','won','lost'],
  emailPermission:['unknown','recorded','withdrawn'],whatsappPermission:['unknown','recorded','withdrawn'],
  actionState:['open','done','cancelled'],followUpChannel:['unspecified','email','whatsapp','phone','other']};
export const importHeaders=Object.keys(importLimits).concat(Object.keys(choices));
export function readImportCsv(text){
  if(text.length>200000)throw Error('Use a CSV smaller than 200,000 characters.');
  // Quoted commas, escaped quotes and embedded newlines are supported; malformed quoting is rejected.
  const records=[];let cells=[],cell='',quoted=false,closed=false;
  const field=()=>{cells.push(cell);cell='';closed=false;};
  const record=()=>{field();if(cells.some(value=>value.trim()))records.push(cells);cells=[];};
  text=text.replace(/^\uFEFF/,'');
  for(let i=0;i<text.length;i++){
    const char=text[i];
    if(quoted){if(char==='"'){if(text[i+1]==='"'){cell+='"';i++;}else{quoted=false;closed=true;}}else cell+=char;continue;}
    if(char===','){field();continue;}
    if(char==='\r'||char==='\n'){if(char==='\r'&&text[i+1]==='\n')i++;record();continue;}
    if(char==='"'&&!cell&&!closed){quoted=true;continue;}
    if(closed||char==='"')throw Error('Check CSV quotes. Quote the whole field and double any quotes inside it.');
    cell+=char;
  }
  if(quoted)throw Error('A quoted CSV field is unfinished.');
  if(cell||cells.length||closed)record();
  return records;
}
export function previewLeadCsv(text){
  const records=readImportCsv(text);
  if(records.length<2||records.length>101)throw Error('Include a header and between 1 and 100 enquiry rows.');
  const headers=records.shift().map(value=>value.trim());
  if(new Set(headers).size!==headers.length||headers.some(value=>!importHeaders.includes(value)))
    throw Error('Use unique supported column names exactly as shown.');
  if(!headers.includes('name')||!headers.includes('source')||!headers.some(value=>value==='email'||value==='phone'))
    throw Error('Include name, source and at least one of email or phone.');
  const emails=new Set(),phones=new Set();
  return records.map((values,index)=>{
    const data=Object.fromEntries(Object.keys(importLimits).map(key=>[key,'']));
    Object.assign(data,{status:'new',emailPermission:'unknown',whatsappPermission:'unknown',actionState:'open',followUpChannel:'unspecified'});
    headers.forEach((key,i)=>{if(values[i]?.trim())data[key]=values[i].trim();});
    const errors=[];
    if(values.length!==headers.length)errors.push('Column count differs from header');
    for(const [key,max] of Object.entries(importLimits))if([...data[key]].length>max)errors.push(`${key} exceeds ${max} characters`);
    for(const [key,allowed] of Object.entries(choices))if(!allowed.includes(data[key]))errors.push(`Unsupported ${key}`);
    if(!data.name||!data.source||(!data.email&&!data.phone))errors.push('Name, source and email or phone are required');
    if(data.email&&!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(data.email))errors.push('Check email');
    const phone=data.phone.replace(/[ ()+.\-]/g,'');
    if(data.phone&&!/^[0-9]{7,15}$/.test(phone))errors.push('Use 7–15 phone digits including country code');
    if((data.emailPermission==='recorded'||data.whatsappPermission==='recorded')&&!data.permissionNotes)errors.push('Recorded permission needs when, where and what was agreed');
    if(data.actionDueDate&&(!/^\d{4}-\d{2}-\d{2}$/.test(data.actionDueDate)||data.actionDueDate.startsWith('0000')||
      !Number.isFinite(Date.parse(data.actionDueDate))||new Date(data.actionDueDate).toISOString().slice(0,10)!==data.actionDueDate))errors.push('Check action date (YYYY-MM-DD)');
    if((data.actionDueDate||['done','cancelled'].includes(data.actionState))&&!data.nextAction)errors.push('Describe the next action');
    const email=data.email.toLowerCase();
    if((email&&emails.has(email))||(phone&&phones.has(phone)))errors.push('Contact repeats an earlier CSV row');
    if(!errors.length){if(email)emails.add(email);if(phone)phones.add(phone);}
    return {number:index+1,data,errors};
  });
}
