// Native HTTP fixture with independent per-token scope checks; not a Mealie server.
const http=require('http'),crypto=require('crypto');
const port=Number(process.env.IDENTITY_TEST_PORT||19876),fault=process.env.IDENTITY_TEST_FAULT||'';
const groups={},households={},users={},recipes={},lists={},tokens={};
const admin={id:crypto.randomUUID(),email:'admin@example.invalid',admin:true,groupId:crypto.randomUUID(),householdId:crypto.randomUUID(),password:'admin-pass'};
users[admin.email]=admin;let max=0,active=0,requestCount=0,leaked=false;
const clone=x=>JSON.parse(JSON.stringify(x));
const uuid=()=>crypto.randomUUID();
const server=http.createServer((req,res)=>{active++;max=Math.max(max,active);requestCount++;let raw='';req.on('data',b=>raw+=b);req.on('end',()=>{
 let code=200,result={};try{
 const p=req.url.split('?')[0],method=req.method,body=raw?(req.headers['content-type']?.startsWith('application/x-www-form-urlencoded')?Object.fromEntries(new URLSearchParams(raw)):JSON.parse(raw)):{};
 if(p==='/api/auth/token'){
  const u=users[body.username];if(!u||u.password!==body.password){code=401;result={detail:'Invalid credentials'};}else{let token=uuid();tokens[token]=u;result={access_token:token,token_type:'bearer'};}
 }else{
 const user=tokens[(req.headers.authorization||'').replace('Bearer ','')];if(!user){code=401;throw 'unauthorized';}
 if(p==='/api/users/self')result={...user,password:undefined,tokens:[]};
 else if(p.startsWith('/api/admin/')&&!user.admin){code=403;throw 'admin required';}
 else if(p==='/api/admin/groups'&&method==='POST'){code=201;result={id:uuid(),name:body.name};groups[result.id]=result;}
 else if(p==='/api/admin/households'&&method==='POST'){code=201;result={id:uuid(),name:body.name,groupId:body.groupId};households[result.id]=result;}
 else if(p==='/api/admin/users'&&method==='POST'){
  const g=Object.values(groups).find(g=>g.name===body.group),h=Object.values(households).find(h=>h.name===body.household&&h.groupId===g?.id);if(!g||!h){code=422;throw 'invalid scope';}
  code=201;result={...body,id:uuid(),groupId:g.id,householdId:h.id,admin:fault==='regular-admin'?true:false};users[body.email]=result;result={...result,password:undefined};
 }else if(p==='/api/recipes'&&method==='POST'){
  const slug=body.name.toLowerCase(),r={id:uuid(),name:body.name,slug,userId:user.id,groupId:user.groupId,householdId:user.householdId,description:'',settings:{public:false,locked:false},recipeIngredient:[],recipeInstructions:[]};recipes[r.id]=r;code=201;result=slug;
 }else if(p.startsWith('/api/recipes/')){
  let slug=p.slice('/api/recipes/'.length).replace(/\/duplicate$/,'');let r=Object.values(recipes).find(r=>r.slug===slug||r.id===slug);
  if(!r||(r.groupId!==user.groupId&&fault!=='scope-leak')){code=404;throw 'not found';}
  if(method==='GET')result=(leaked&&fault==='write-leak'&&r.description?.endsWith('-source-final'))?{...r,description:'LEAKED_COPY_STATE'}:r;
  else if(method==='POST'&&p.endsWith('/duplicate')){code=201;result={...clone(r),id:uuid(),slug:body.name,name:body.name,userId:fault==='copy-owner'?r.userId:user.id,groupId:user.groupId,householdId:user.householdId};result.recipeIngredient.forEach(i=>i.referenceId=uuid());recipes[result.id]=result;}
  else if(method==='PUT'){recipes[r.id]={...r,...clone(body)};result=recipes[r.id];if(fault==='write-leak'&&body.description?.endsWith('-copy-final')){leaked=true;}if(fault==='write-leak'&&body.description?.endsWith('-copy-final'))for(const other of Object.values(recipes))if(other.id!==r.id&&other.userId!==user.id)other.description=body.description;}
  else if(method==='DELETE'){if(r.userId!==user.id&&fault!=='delete-owner'){code=403;throw 'not owner';}delete recipes[r.id];result=r;}
  else{code=404;throw 'unsupported';}
 }else if(p==='/api/households/shopping/lists'&&method==='POST'){code=201;result={id:uuid(),...body,userId:user.id,groupId:user.groupId,householdId:user.householdId,listItems:[],recipeReferences:[]};lists[result.id]=result;
 }else if(p.startsWith('/api/households/shopping/lists/')){
  const seg=p.slice('/api/households/shopping/lists/'.length).split('/'),l=lists[seg[0]];if(!l||l.householdId!==user.householdId){code=404;throw 'not found';}
  if(method==='GET')result=l;else if(method==='POST'&&seg[1]==='recipe'){
   const r=recipes[seg[2]];if(!r||r.groupId!==user.groupId){code=(fault==='missing-add-500'&&!r)?500:404;throw 'foreign recipe';}
   l.recipeReferences.push({id:uuid(),recipeId:r.id,recipeQuantity:1});result=l;
  }else{code=404;throw 'unsupported';}
 }else{code=404;throw 'unknown';}
 }
 }catch(e){if(code===200)code=500;result={detail:String(e)};}
 const output=JSON.stringify(result);res.writeHead(code,{'Content-Type':'application/json'});res.end(output);active--;
 });});
server.listen(port,'127.0.0.1',()=>console.log('READY'));
process.on('SIGTERM',()=>{console.log(JSON.stringify({requests:requestCount,maximum_active:max}));server.close(()=>process.exit(0));});
