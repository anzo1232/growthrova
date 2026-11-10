/** Preview only. The server renders again from its tenant-bound catalogue. */
export function templatePreview(templates,choice){
  if(!choice)return null;
  const template=templates.find(item=>item.contentSid===choice.contentSid&&item.version===choice.version);
  if(!template)return {error:'Choose an available business template.'};
  const variables=choice.variables||{};
  const keys=template.variableLabels.map((_,index)=>String(index+1));
  if(Object.keys(variables).length!==keys.length||keys.some(key=>typeof variables[key]!=='string'||!variables[key].trim()||[...variables[key]].length>200||/[\u0000-\u001f\u007f]/.test(variables[key])||/\{\{|\}\}/.test(variables[key])))
    return {template,error:'Fill every template value using up to 200 characters, without line breaks or template markers.'};
  const wording=template.body.replace(/\{\{([1-9][0-9]*)\}\}/g,(_,key)=>variables[key]);
  if([...wording].length>1600)return {template,error:'The completed template exceeds 1600 characters.'};
  return {template,wording,selection:{contentSid:template.contentSid,version:template.version,variables}};
}
