// Controlled Mealie response fixture for semantic callback regression only.
module.exports=function(model,objects,uuid,fault,method,url,body){
 if(!model.semantic_program)return null;
 const cfg=model.semantic_program;
 if(method==='get'&&objects[url]?.listItems){
  objects[url].listItems=objects[url].listItems.map(item=>objects['/api/households/shopping/items/'+item.id]||item);
 }
 if(method==='put'&&(url==='/api/foods/merge'||url==='/api/units/merge')){
  const unitMerge=url==='/api/units/merge', resourcePath=unitMerge?'/api/units/':'/api/foods/';
  const data=JSON.parse(body),from=unitMerge?data.fromUnit:data.fromFood,to=unitMerge?data.toUnit:data.toFood;
  const target=objects[resourcePath+to];if(!target||!objects[resourcePath+from])throw Error('Unknown merge identity');
  if(fault==='merge-500')return {status:500,result:{detail:'Injected merge failure'}};
  function remap(node){if(!node||typeof node!=='object')return;
   if(unitMerge){if(node.unit?.id===from)node.unit=JSON.parse(JSON.stringify(target));if(node.unitId===from)node.unitId=to;}
   else {if(node.food?.id===from)node.food=JSON.parse(JSON.stringify(target));if(node.foodId===from)node.foodId=to;}
   for(const [key,value] of Object.entries(node))if(key!=='food')remap(value);
  }
  for(const [route,object] of Object.entries(objects)){
   if(fault==='merge-stale-list'&&route.startsWith('/api/households/shopping/'))continue;
   remap(object);
   if(fault==='merge-loses-quantity'&&object.recipeIngredient)object.recipeIngredient[0].quantity=0;
  }
  // Consolidate contribution buckets after identity remapping; preserve manual stock.
  for(const object of Object.values(objects))if(object.listItems){
   const buckets=new Map();
   for(const item of object.listItems){const key=JSON.stringify([item.foodId,item.unitId,item._contribution||('manual-'+item.id)]);
    if(buckets.has(key))buckets.get(key).quantity+=item.quantity;
    else buckets.set(key,{...item});
   }
   object.listItems=[...buckets.values()];
  }
  if(fault==='merge-collision-drops-item')for(const object of Object.values(objects))if(object.recipeIngredient){
   const seen=new Set();object.recipeIngredient=object.recipeIngredient.filter(item=>{const key=JSON.stringify([item.food.id,item.unit.id]);if(seen.has(key))return false;seen.add(key);return true;});
  }
  delete objects[resourcePath+from];return {status:200,result:{message:'Merged'}};
 }
 if(method==='post'&&url.includes('/recipe/')){
  const offset=url.lastIndexOf('/recipe/'),list=objects[url.slice(0,offset)],tail=url.slice(offset+8).split('/');
  const recipe=Object.values(objects).find(x=>x.recipeIngredient&&x.id===tail[0]);
  if(!list||!recipe)throw Error('Unknown contribution identity');
  const remove=tail[1]==='delete',data=JSON.parse(body),amount=(remove?-1:1)*(data.recipeIncrementQuantity||data.recipeDecrementQuantity);
  let association=list.recipeReferences.find(x=>x.recipeId===recipe.id);
  if(!association){association={id:uuid(),recipeId:recipe.id,recipeQuantity:0};list.recipeReferences.push(association);}
  association.recipeQuantity+=amount;
  if(fault==='wrong-reference-quantity')association.recipeQuantity+=1;
  list.recipeReferences=list.recipeReferences.filter(x=>x.recipeQuantity>0);
  for(const ingredient of recipe.recipeIngredient){
   let item=list.listItems.find(x=>x._contribution===recipe.id&&x.foodId===ingredient.food.id&&x.unitId===ingredient.unit.id);
   if(!item){item={id:uuid(),foodId:ingredient.food.id,unitId:ingredient.unit.id,quantity:0,_contribution:recipe.id};list.listItems.push(item);}
   item.quantity+=amount*ingredient.quantity*(fault==='quantity-double'?2:1);
  }
  if(remove&&fault==='remove-manual'){list.listItems.filter(x=>!x._contribution).forEach(x=>x.quantity=0);}
  list.listItems=list.listItems.filter(x=>x.quantity>0);
  return {status:200,result:list};
 }
 return null;
};
