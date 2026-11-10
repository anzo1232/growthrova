/** Extensible business activity identification from explicit business-supplied terms.
 * The match is a suggested workflow, never verified company classification.
 */
const MODELS=[
 {id:'transformation',pattern:/barber|hair|salon|groom|detail|renovat|makeover|landscap|cleaning|dentist|orthodont/,focus:'Show starting condition, the work and a clear finished result.',review:'Confirm the same genuine subject appears before and after; obtain consent.'},
 {id:'experience',pattern:/restaurant|cafe|coffee|hotel|hospitality|travel|tourism|event|wedding|leisure|spa/,focus:'Show the distinctive experience, genuine reaction and what to expect.',review:'Check the experience shown is representative and claims are accurate.'},
 {id:'showcase',pattern:/estate|property|realty|interior|architecture|car dealer|automotive|furniture|retail|product|ecommerce|fashion/,focus:'Lead with the strongest product or space, then details and differentiators.',review:'Keep key features visible; verify specifications, availability and price.'},
 {id:'expertise',pattern:/fitness|trainer|coach|consult|accountant|legal|lawyer|education|tutor|medical|wellness|financial|therapy|software|technology/,focus:'Start with a real customer question, give a complete explanation and show evidence.',review:'Verify qualifications, accuracy, consent and regulated claims where applicable.'},
 {id:'trust',pattern:/construction|builder|plumb|electric|roof|security|maintenance|repair|logistics|manufactur|b2b|agency/,focus:'Explain the problem, process and verifiable outcome, then the next step.',review:'Obtain client permission and substantiate promised results.'}
];
export function businessTypeStrategy({industry='',businessType='',offer=''}={}){
 const text=[businessType,industry,offer].filter(x=>typeof x==='string').join(' ').slice(0,320).toLowerCase();
 const match=MODELS.find(x=>x.pattern.test(text));
 return match?{type:match.id,focus:match.focus,review:match.review,source:'Rule-based suggestion from supplied business description',verified:false}:
 {type:'custom',focus:'Identify the customer problem, the genuine value delivered and the next action.',review:'Check the chosen footage demonstrates the offer and addresses a real customer need.',source:'Custom business strategy; no reliable category match',verified:false};
}
