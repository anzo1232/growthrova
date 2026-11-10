/** Explicit campaign branding, using the existing renderer's palette/style contract.
 * Incomplete settings are saved drafts. They grant no logo/media rights or approval.
 */
import {BRAND_TEMPLATES} from './businessBrandSafety.mjs';

export const EMPTY_CAMPAIGN_BRAND=Object.freeze({name:'',primary_color:'',secondary_color:'',font_style:''});

export function normaliseCampaignBrand(value){
 if(!value||typeof value!=='object'||Array.isArray(value)||
  Object.keys(value).length!==4||Object.keys(value).some(key=>!Object.hasOwn(EMPTY_CAMPAIGN_BRAND,key)))
  throw new TypeError('Use only the campaign brand name, colours and typography.');
 const {name,primary_color,secondary_color,font_style}=value;
 if(typeof name!=='string'||Array.from(name).length>38||
  Array.from(name).some(char=>char!==' '&&/[\p{C}\p{Z}]/u.test(char)))
  throw new TypeError('Use a single-line brand name of up to 38 characters.');
 for(const colour of [primary_color,secondary_color])
  if(typeof colour!=='string'||(colour!==''&&!/^#[0-9a-fA-F]{6}$/.test(colour)))
   throw new TypeError('Enter brand colours as six-digit hex values, such as #123ABC.');
 if(typeof font_style!=='string'||(font_style!==''&&!BRAND_TEMPLATES.some(item=>item.id===font_style)))
  throw new TypeError('Choose one of the supported brand typography styles.');
 return {name,primary_color,secondary_color,font_style};
}

export function editCampaignBrand(document,patch){
 if(!patch||typeof patch!=='object'||Array.isArray(patch)||
  Object.keys(patch).some(key=>!Object.hasOwn(EMPTY_CAMPAIGN_BRAND,key)))
  throw new TypeError('Invalid campaign brand edit.');
 const current=document.brandKit??EMPTY_CAMPAIGN_BRAND;
 const brandKit=normaliseCampaignBrand({...current,...patch});
 if(Object.keys(brandKit).every(key=>brandKit[key]===current[key]))return document;
 return {...document,brandKit};
}
