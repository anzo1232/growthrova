import test from 'node:test';import assert from 'node:assert/strict';
import {editorialLayout} from '../src/lib/businessEditorialLayout.mjs';
function dir(key,hook,evidence){
 return {id:key,hook,evidence:{kind:key,quote:evidence,label:'official site paragraph'}};
}
test('Charcoal hero reduces long source headline to short high-impact art direction',()=>{
 const result=editorialLayout(dir('method','The mangal: how Berenjak grills koobideh',
  'The ground lamb kabab is shaped around a skewer and grilled over the mangal.'),'Berenjak');
 assert.equal(result.headline,'THE MANGAL.');
 assert.equal(result.eyebrow,'CHARCOAL · CRAFT');
 assert.equal(result.status,'visual-reference-only');
 assert.equal(result.rightsVerified,false);
});
test('Berenjak bread and Soho heritage do not invent menu claims',()=>{
 const bread=editorialLayout(dir('bread','Sangak: bread baked on hot river stones',
  'Baked on a bed of hot river stones, sangak has an uneven texture.'),'Berenjak');
 assert.equal(bread.headline,'SANGAK.');
 const city=editorialLayout(dir('heritage',"Inspired by Tehran's kabab houses",
   'Whether our take on the hole in the wall kababi you find all over Tehran or a townhouse'),'Berenjak');
 assert.equal(city.headline,'FROM TEHRAN.');
});
test('An ungrounded hook is not allowed to make up a specific Persian dish',()=>{
 const generic=editorialLayout(dir('other','Something exciting about the business',
  'A brief statement about new creative services in the city.'),'Example Studio');
 assert.doesNotMatch(generic.headline,/KOOBIDEH|SANGAK|TEHRAN/);
});
test('Missing evidence cannot become a layout',()=>{
 assert.throws(()=>editorialLayout({hook:'Free Michelin stars'},'Example'),/Sourced direction/);
});
