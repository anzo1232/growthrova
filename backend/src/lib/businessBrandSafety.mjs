/** Readability and layout rules for Clippr Business brand templates. */
export const BRAND_TEMPLATES = Object.freeze([
  { id:"modern", title:"Editorial", detail:"Confident, balanced typography", layout:"editorial"},
  { id:"bold", title:"Impact", detail:"High-contrast, attention-grabbing", layout:"impact"},
  { id:"minimal", title:"Essential", detail:"Restrained, elegant messaging", layout:"minimal"},
  { id:"classic", title:"Heritage", detail:"Warm, considered presentation", layout:"classic"},
]);
function rgb(hex) {
  if (!/^#[\da-f]{6}$/i.test(hex||"")) return null;
  return [1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255);
}
function luminance(color) {
  const channels=rgb(color);
  if(!channels)return null;
  const [r,g,b]=channels.map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);
  return .2126*r+.7152*g+.0722*b;
}
export function contrastRatio(a,b) {
  const x=luminance(a),y=luminance(b);
  if(x==null||y==null)return 0;
  return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);
}
export function readableColour(background) {
  return contrastRatio(background,"#111111")>=contrastRatio(background,"#FFFFFF")?"#111111":"#FFFFFF";
}
export function brandContrastWarning(primary,secondary) {
  if(!rgb(primary)||!rgb(secondary))return "Choose valid six-digit brand colours.";
  if(contrastRatio(primary,secondary)<4.5) return "These colours don't have enough contrast for captions or calls to action. Choose a lighter or darker secondary colour.";
  return "";
}
export function creativeLayout(style) {
  return BRAND_TEMPLATES.find(t=>t.id===style)||BRAND_TEMPLATES[0];
}
