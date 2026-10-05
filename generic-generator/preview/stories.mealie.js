// Generated symbolic concurrent CRUD. Callback data is runtime-only.
// @provengo summon rest
// @provengo summon rtv
bthread("verify:P1:api/admin/backups:1", function(){
for (let stage of ["readback", "create", "read", "delete"]) {
let step=sync({waitFor:EventSet("step-or-finish:P1:api/admin/backups:1",function(e){return e.data && e.data.owner==="P1:api/admin/backups:1" && ((e.name==="SBT:CrudStep" && e.data.stage===stage) || e.name==="SBT:WorkerFinished");})});
if(step.name==="SBT:WorkerFinished") return;
if(stage==="create" || stage==="readback") {
sbtHttp_1(step.data.values);
}
sync({request:Event("SBT:CrudVerified",{owner:"P1:api/admin/backups:1",stage:stage,ok:true})});
}
});
bthread("crud:P1:api/admin/backups:1", function() {
let __args={}; let __parentBindings={};
function finish(reason){ sync({request:Event("SBT:WorkerFinished",{process:1,entity:"api/admin/backups",owner:"P1:api/admin/backups:1",reason:reason})}); }
function verified(stage){ sync({request:Event("SBT:CrudStep",{owner:"P1:api/admin/backups:1",process:1,entity:"api/admin/backups",stage:stage,values:Object.assign({},__args)})});sync({waitFor:EventSet("verified:P1:api/admin/backups:1",function(e){return e.name==="SBT:CrudVerified" && e.data.owner==="P1:api/admin/backups:1" && e.data.stage===stage;})}); }
sbtHttp_2(__args);
__args["fileName"]="@{sbt_P1_api_admin_backups_1_fileName}";
sbtHttp_3(__args);
verified("readback");
verified("create");
sync({request:Event("SBT:InstanceReady",{process:1,entity:"api/admin/backups",owner:"P1:api/admin/backups:1",values:Object.assign({},__args)})});
sbtHttp_4(__args);
verified("read");
sbtHttp_5(__args);
verified("delete");
finish("complete");
});
bthread("children:P1:api/admin/groups:1", function(){
let finished={}; let cleanup=false; let remaining=2;
while(remaining>0 || !cleanup){
let event=sync({waitFor:EventSet("child-finish:P1:api/admin/groups:1",function(e){return e.data && ((e.name==="SBT:WorkerFinished" && ["P1:api/admin/groups/{group_id}/ai-providers/providers:1", "P1:api/admin/households:1"].indexOf(e.data.owner)>=0) || (e.name==="SBT:CleanupReady" && e.data.owner==="P1:api/admin/groups:1"));})});
if(event.name==="SBT:CleanupReady") cleanup=true;
else if(!finished[event.data.owner]){finished[event.data.owner]=true; remaining--;}
}
sync({request:Event("SBT:ChildrenFinished",{owner:"P1:api/admin/groups:1"})});
});
bthread("verify:P1:api/admin/groups:1", function(){
for (let stage of ["readback", "create", "read", "update", "delete"]) {
let step=sync({waitFor:EventSet("step-or-finish:P1:api/admin/groups:1",function(e){return e.data && e.data.owner==="P1:api/admin/groups:1" && ((e.name==="SBT:CrudStep" && e.data.stage===stage) || e.name==="SBT:WorkerFinished");})});
if(step.name==="SBT:WorkerFinished") return;
if(stage==="create" || stage==="readback") {
sbtHttp_6(step.data.values);
}
if(stage==="update") sbtHttp_7(step.data.values);
sync({request:Event("SBT:CrudVerified",{owner:"P1:api/admin/groups:1",stage:stage,ok:true})});
}
});
bthread("crud:P1:api/admin/groups:1", function() {
let __args={}; let __parentBindings={};
function finish(reason){ sync({request:Event("SBT:WorkerFinished",{process:1,entity:"api/admin/groups",owner:"P1:api/admin/groups:1",reason:reason})}); }
function verified(stage){ sync({request:Event("SBT:CrudStep",{owner:"P1:api/admin/groups:1",process:1,entity:"api/admin/groups",stage:stage,values:Object.assign({},__args)})});sync({waitFor:EventSet("verified:P1:api/admin/groups:1",function(e){return e.name==="SBT:CrudVerified" && e.data.owner==="P1:api/admin/groups:1" && e.data.stage===stage;})}); }
  let __p1_apiAdminGroups_1_name = "name_14269";
__args["name"]=__p1_apiAdminGroups_1_name;
sbtHttp_8(__args);
__args["itemId"]="@{sbt_P1_api_admin_groups_1_itemId}";
sbtHttp_9(__args);
verified("readback");
verified("create");
sync({request:Event("SBT:InstanceReady",{process:1,entity:"api/admin/groups",owner:"P1:api/admin/groups:1",values:Object.assign({},__args)})});
sbtHttp_10(__args);
verified("read");
sbtHttp_11(__args);
verified("update");
sync({request:Event("SBT:CleanupReady",{owner:"P1:api/admin/groups:1"})});
sync({waitFor:EventSet("children-done:P1:api/admin/groups:1",function(e){return e.name==="SBT:ChildrenFinished" && e.data.owner==="P1:api/admin/groups:1";})});
sbtHttp_12(__args);
verified("delete");
finish("complete");
});
bthread("verify:P1:api/admin/users:1", function(){
for (let stage of ["readback", "create", "read", "update", "delete"]) {
let step=sync({waitFor:EventSet("step-or-finish:P1:api/admin/users:1",function(e){return e.data && e.data.owner==="P1:api/admin/users:1" && ((e.name==="SBT:CrudStep" && e.data.stage===stage) || e.name==="SBT:WorkerFinished");})});
if(step.name==="SBT:WorkerFinished") return;
if(stage==="create" || stage==="readback") {
sbtHttp_13(step.data.values);
}
if(stage==="update") sbtHttp_14(step.data.values);
sync({request:Event("SBT:CrudVerified",{owner:"P1:api/admin/users:1",stage:stage,ok:true})});
}
});
bthread("crud:P1:api/admin/users:1", function() {
let __args={}; let __parentBindings={};
function finish(reason){ sync({request:Event("SBT:WorkerFinished",{process:1,entity:"api/admin/users",owner:"P1:api/admin/users:1",reason:reason})}); }
function verified(stage){ sync({request:Event("SBT:CrudStep",{owner:"P1:api/admin/users:1",process:1,entity:"api/admin/users",stage:stage,values:Object.assign({},__args)})});sync({waitFor:EventSet("verified:P1:api/admin/users:1",function(e){return e.name==="SBT:CrudVerified" && e.data.owner==="P1:api/admin/users:1" && e.data.stage===stage;})}); }
  let __p1_apiAdminUsers_1_email = "email_5572";
  let __p1_apiAdminUsers_1_fullName = "fullName_20234";
  let __p1_apiAdminUsers_1_password = "password_58994";
  let __p1_apiAdminUsers_1_username = "username_7684";
__args["email"]=__p1_apiAdminUsers_1_email;
__args["fullName"]=__p1_apiAdminUsers_1_fullName;
__args["password"]=__p1_apiAdminUsers_1_password;
__args["username"]=__p1_apiAdminUsers_1_username;
sbtHttp_15(__args);
__args["itemId"]="@{sbt_P1_api_admin_users_1_itemId}";
sbtHttp_16(__args);
verified("readback");
verified("create");
sync({request:Event("SBT:InstanceReady",{process:1,entity:"api/admin/users",owner:"P1:api/admin/users:1",values:Object.assign({},__args)})});
sbtHttp_17(__args);
verified("read");
sbtHttp_18(__args);
verified("update");
sbtHttp_19(__args);
verified("delete");
finish("complete");
});
bthread("verify:P1:api/foods:1", function(){
for (let stage of ["readback", "create", "read", "update", "delete"]) {
let step=sync({waitFor:EventSet("step-or-finish:P1:api/foods:1",function(e){return e.data && e.data.owner==="P1:api/foods:1" && ((e.name==="SBT:CrudStep" && e.data.stage===stage) || e.name==="SBT:WorkerFinished");})});
if(step.name==="SBT:WorkerFinished") return;
if(stage==="create" || stage==="readback") {
sbtHttp_20(step.data.values);
}
if(stage==="update") sbtHttp_21(step.data.values);
sync({request:Event("SBT:CrudVerified",{owner:"P1:api/foods:1",stage:stage,ok:true})});
}
});
bthread("crud:P1:api/foods:1", function() {
let __args={}; let __parentBindings={};
function finish(reason){ sync({request:Event("SBT:WorkerFinished",{process:1,entity:"api/foods",owner:"P1:api/foods:1",reason:reason})}); }
function verified(stage){ sync({request:Event("SBT:CrudStep",{owner:"P1:api/foods:1",process:1,entity:"api/foods",stage:stage,values:Object.assign({},__args)})});sync({waitFor:EventSet("verified:P1:api/foods:1",function(e){return e.name==="SBT:CrudVerified" && e.data.owner==="P1:api/foods:1" && e.data.stage===stage;})}); }
  let __p1_apiFoods_1_name = "name_68432";
__args["name"]=__p1_apiFoods_1_name;
sbtHttp_22(__args);
__args["itemId"]="@{sbt_P1_api_foods_1_itemId}";
sbtHttp_23(__args);
verified("readback");
verified("create");
sync({request:Event("SBT:InstanceReady",{process:1,entity:"api/foods",owner:"P1:api/foods:1",values:Object.assign({},__args)})});
sbtHttp_24(__args);
verified("read");
sbtHttp_25(__args);
verified("update");
sbtHttp_26(__args);
verified("delete");
finish("complete");
});
bthread("verify:P1:api/groups/ai-providers/providers:1", function(){
for (let stage of ["readback", "create", "read", "update", "delete"]) {
let step=sync({waitFor:EventSet("step-or-finish:P1:api/groups/ai-providers/providers:1",function(e){return e.data && e.data.owner==="P1:api/groups/ai-providers/providers:1" && ((e.name==="SBT:CrudStep" && e.data.stage===stage) || e.name==="SBT:WorkerFinished");})});
if(step.name==="SBT:WorkerFinished") return;
if(stage==="create" || stage==="readback") {
sbtHttp_27(step.data.values);
}
if(stage==="update") sbtHttp_28(step.data.values);
sync({request:Event("SBT:CrudVerified",{owner:"P1:api/groups/ai-providers/providers:1",stage:stage,ok:true})});
}
});
bthread("crud:P1:api/groups/ai-providers/providers:1", function() {
let __args={}; let __parentBindings={};
function finish(reason){ sync({request:Event("SBT:WorkerFinished",{process:1,entity:"api/groups/ai-providers/providers",owner:"P1:api/groups/ai-providers/providers:1",reason:reason})}); }
function verified(stage){ sync({request:Event("SBT:CrudStep",{owner:"P1:api/groups/ai-providers/providers:1",process:1,entity:"api/groups/ai-providers/providers",stage:stage,values:Object.assign({},__args)})});sync({waitFor:EventSet("verified:P1:api/groups/ai-providers/providers:1",function(e){return e.name==="SBT:CrudVerified" && e.data.owner==="P1:api/groups/ai-providers/providers:1" && e.data.stage===stage;})}); }
  let __p1_apiGroupsAiProvidersProviders_1_model = "model_98787";
  let __p1_apiGroupsAiProvidersProviders_1_name = "name_5139";
__args["model"]=__p1_apiGroupsAiProvidersProviders_1_model;
__args["name"]=__p1_apiGroupsAiProvidersProviders_1_name;
sbtHttp_29(__args);
__args["providerId"]="@{sbt_P1_api_groups_ai_providers_providers_1_providerId}";
sbtHttp_30(__args);
verified("readback");
verified("create");
sync({request:Event("SBT:InstanceReady",{process:1,entity:"api/groups/ai-providers/providers",owner:"P1:api/groups/ai-providers/providers:1",values:Object.assign({},__args)})});
sbtHttp_31(__args);
verified("read");
sbtHttp_32(__args);
verified("update");
sbtHttp_33(__args);
verified("delete");
finish("complete");
});
bthread("verify:P1:api/groups/labels:1", function(){
for (let stage of ["readback", "create", "read", "update", "delete"]) {
let step=sync({waitFor:EventSet("step-or-finish:P1:api/groups/labels:1",function(e){return e.data && e.data.owner==="P1:api/groups/labels:1" && ((e.name==="SBT:CrudStep" && e.data.stage===stage) || e.name==="SBT:WorkerFinished");})});
if(step.name==="SBT:WorkerFinished") return;
if(stage==="create" || stage==="readback") {
sbtHttp_34(step.data.values);
}
if(stage==="update") sbtHttp_35(step.data.values);
sync({request:Event("SBT:CrudVerified",{owner:"P1:api/groups/labels:1",stage:stage,ok:true})});
}
});
bthread("crud:P1:api/groups/labels:1", function() {
let __args={}; let __parentBindings={};
function finish(reason){ sync({request:Event("SBT:WorkerFinished",{process:1,entity:"api/groups/labels",owner:"P1:api/groups/labels:1",reason:reason})}); }
function verified(stage){ sync({request:Event("SBT:CrudStep",{owner:"P1:api/groups/labels:1",process:1,entity:"api/groups/labels",stage:stage,values:Object.assign({},__args)})});sync({waitFor:EventSet("verified:P1:api/groups/labels:1",function(e){return e.name==="SBT:CrudVerified" && e.data.owner==="P1:api/groups/labels:1" && e.data.stage===stage;})}); }
  let __p1_apiGroupsLabels_1_name = "name_43022";
__args["name"]=__p1_apiGroupsLabels_1_name;
sbtHttp_36(__args);
__args["itemId"]="@{sbt_P1_api_groups_labels_1_itemId}";
sbtHttp_37(__args);
verified("readback");
verified("create");
sync({request:Event("SBT:InstanceReady",{process:1,entity:"api/groups/labels",owner:"P1:api/groups/labels:1",values:Object.assign({},__args)})});
sbtHttp_38(__args);
verified("read");
sbtHttp_39(__args);
verified("update");
sbtHttp_40(__args);
verified("delete");
finish("complete");
});
bthread("verify:P1:api/households/cookbooks:1", function(){
for (let stage of ["readback", "create", "read", "update", "delete"]) {
let step=sync({waitFor:EventSet("step-or-finish:P1:api/households/cookbooks:1",function(e){return e.data && e.data.owner==="P1:api/households/cookbooks:1" && ((e.name==="SBT:CrudStep" && e.data.stage===stage) || e.name==="SBT:WorkerFinished");})});
if(step.name==="SBT:WorkerFinished") return;
if(stage==="create" || stage==="readback") {
sbtHttp_41(step.data.values);
}
if(stage==="update") sbtHttp_42(step.data.values);
sync({request:Event("SBT:CrudVerified",{owner:"P1:api/households/cookbooks:1",stage:stage,ok:true})});
}
});
bthread("crud:P1:api/households/cookbooks:1", function() {
let __args={}; let __parentBindings={};
function finish(reason){ sync({request:Event("SBT:WorkerFinished",{process:1,entity:"api/households/cookbooks",owner:"P1:api/households/cookbooks:1",reason:reason})}); }
function verified(stage){ sync({request:Event("SBT:CrudStep",{owner:"P1:api/households/cookbooks:1",process:1,entity:"api/households/cookbooks",stage:stage,values:Object.assign({},__args)})});sync({waitFor:EventSet("verified:P1:api/households/cookbooks:1",function(e){return e.name==="SBT:CrudVerified" && e.data.owner==="P1:api/households/cookbooks:1" && e.data.stage===stage;})}); }
  let __p1_apiHouseholdsCookbooks_1_name = "name_64850";
__args["name"]=__p1_apiHouseholdsCookbooks_1_name;
sbtHttp_43(__args);
__args["itemId"]="@{sbt_P1_api_households_cookbooks_1_itemId}";
sbtHttp_44(__args);
verified("readback");
verified("create");
sync({request:Event("SBT:InstanceReady",{process:1,entity:"api/households/cookbooks",owner:"P1:api/households/cookbooks:1",values:Object.assign({},__args)})});
sbtHttp_45(__args);
verified("read");
sbtHttp_46(__args);
verified("update");
sbtHttp_47(__args);
verified("delete");
finish("complete");
});
bthread("verify:P1:api/households/events/notifications:1", function(){
for (let stage of ["readback", "create", "read", "update", "delete"]) {
let step=sync({waitFor:EventSet("step-or-finish:P1:api/households/events/notifications:1",function(e){return e.data && e.data.owner==="P1:api/households/events/notifications:1" && ((e.name==="SBT:CrudStep" && e.data.stage===stage) || e.name==="SBT:WorkerFinished");})});
if(step.name==="SBT:WorkerFinished") return;
if(stage==="create" || stage==="readback") {
sbtHttp_48(step.data.values);
}
if(stage==="update") sbtHttp_49(step.data.values);
sync({request:Event("SBT:CrudVerified",{owner:"P1:api/households/events/notifications:1",stage:stage,ok:true})});
}
});
bthread("crud:P1:api/households/events/notifications:1", function() {
let __args={}; let __parentBindings={};
function finish(reason){ sync({request:Event("SBT:WorkerFinished",{process:1,entity:"api/households/events/notifications",owner:"P1:api/households/events/notifications:1",reason:reason})}); }
function verified(stage){ sync({request:Event("SBT:CrudStep",{owner:"P1:api/households/events/notifications:1",process:1,entity:"api/households/events/notifications",stage:stage,values:Object.assign({},__args)})});sync({waitFor:EventSet("verified:P1:api/households/events/notifications:1",function(e){return e.name==="SBT:CrudVerified" && e.data.owner==="P1:api/households/events/notifications:1" && e.data.stage===stage;})}); }
  let __p1_apiHouseholdsEventsNotifications_1_name = "name_84919";
__args["name"]=__p1_apiHouseholdsEventsNotifications_1_name;
sbtHttp_50(__args);
__args["itemId"]="@{sbt_P1_api_households_events_notifications_1_itemId}";
sbtHttp_51(__args);
verified("readback");
verified("create");
sync({request:Event("SBT:InstanceReady",{process:1,entity:"api/households/events/notifications",owner:"P1:api/households/events/notifications:1",values:Object.assign({},__args)})});
sbtHttp_52(__args);
verified("read");
sbtHttp_53(__args);
verified("update");
sbtHttp_54(__args);
verified("delete");
finish("complete");
});
bthread("verify:P1:api/households/mealplans:1", function(){
for (let stage of ["readback", "create", "read", "update", "delete"]) {
let step=sync({waitFor:EventSet("step-or-finish:P1:api/households/mealplans:1",function(e){return e.data && e.data.owner==="P1:api/households/mealplans:1" && ((e.name==="SBT:CrudStep" && e.data.stage===stage) || e.name==="SBT:WorkerFinished");})});
if(step.name==="SBT:WorkerFinished") return;
if(stage==="create" || stage==="readback") {
sbtHttp_55(step.data.values);
}
if(stage==="update") sbtHttp_56(step.data.values);
sync({request:Event("SBT:CrudVerified",{owner:"P1:api/households/mealplans:1",stage:stage,ok:true})});
}
});
bthread("crud:P1:api/households/mealplans:1", function() {
let __args={}; let __parentBindings={};
function finish(reason){ sync({request:Event("SBT:WorkerFinished",{process:1,entity:"api/households/mealplans",owner:"P1:api/households/mealplans:1",reason:reason})}); }
function verified(stage){ sync({request:Event("SBT:CrudStep",{owner:"P1:api/households/mealplans:1",process:1,entity:"api/households/mealplans",stage:stage,values:Object.assign({},__args)})});sync({waitFor:EventSet("verified:P1:api/households/mealplans:1",function(e){return e.name==="SBT:CrudVerified" && e.data.owner==="P1:api/households/mealplans:1" && e.data.stage===stage;})}); }
  let __p1_apiHouseholdsMealplans_1_date = "2025-03-17";
__args["date"]=__p1_apiHouseholdsMealplans_1_date;
sbtHttp_57(__args);
__args["itemId"]="@{sbt_P1_api_households_mealplans_1_itemId}";
sbtHttp_58(__args);
verified("readback");
verified("create");
sync({request:Event("SBT:InstanceReady",{process:1,entity:"api/households/mealplans",owner:"P1:api/households/mealplans:1",values:Object.assign({},__args)})});
sbtHttp_59(__args);
verified("read");
sbtHttp_60(__args);
verified("update");
sbtHttp_61(__args);
verified("delete");
finish("complete");
});
bthread("verify:P1:api/households/mealplans/rules:1", function(){
for (let stage of ["readback", "create", "read", "update", "delete"]) {
let step=sync({waitFor:EventSet("step-or-finish:P1:api/households/mealplans/rules:1",function(e){return e.data && e.data.owner==="P1:api/households/mealplans/rules:1" && ((e.name==="SBT:CrudStep" && e.data.stage===stage) || e.name==="SBT:WorkerFinished");})});
if(step.name==="SBT:WorkerFinished") return;
if(stage==="create" || stage==="readback") {
sbtHttp_62(step.data.values);
}
if(stage==="update") sbtHttp_63(step.data.values);
sync({request:Event("SBT:CrudVerified",{owner:"P1:api/households/mealplans/rules:1",stage:stage,ok:true})});
}
});
bthread("crud:P1:api/households/mealplans/rules:1", function() {
let __args={}; let __parentBindings={};
function finish(reason){ sync({request:Event("SBT:WorkerFinished",{process:1,entity:"api/households/mealplans/rules",owner:"P1:api/households/mealplans/rules:1",reason:reason})}); }
function verified(stage){ sync({request:Event("SBT:CrudStep",{owner:"P1:api/households/mealplans/rules:1",process:1,entity:"api/households/mealplans/rules",stage:stage,values:Object.assign({},__args)})});sync({waitFor:EventSet("verified:P1:api/households/mealplans/rules:1",function(e){return e.name==="SBT:CrudVerified" && e.data.owner==="P1:api/households/mealplans/rules:1" && e.data.stage===stage;})}); }
sbtHttp_64(__args);
__args["itemId"]="@{sbt_P1_api_households_mealplans_rules_1_itemId}";
sbtHttp_65(__args);
verified("readback");
verified("create");
sync({request:Event("SBT:InstanceReady",{process:1,entity:"api/households/mealplans/rules",owner:"P1:api/households/mealplans/rules:1",values:Object.assign({},__args)})});
sbtHttp_66(__args);
verified("read");
sbtHttp_67(__args);
verified("update");
sbtHttp_68(__args);
verified("delete");
finish("complete");
});
bthread("verify:P1:api/households/recipe-actions:1", function(){
for (let stage of ["readback", "create", "read", "update", "delete"]) {
let step=sync({waitFor:EventSet("step-or-finish:P1:api/households/recipe-actions:1",function(e){return e.data && e.data.owner==="P1:api/households/recipe-actions:1" && ((e.name==="SBT:CrudStep" && e.data.stage===stage) || e.name==="SBT:WorkerFinished");})});
if(step.name==="SBT:WorkerFinished") return;
if(stage==="create" || stage==="readback") {
sbtHttp_69(step.data.values);
}
if(stage==="update") sbtHttp_70(step.data.values);
sync({request:Event("SBT:CrudVerified",{owner:"P1:api/households/recipe-actions:1",stage:stage,ok:true})});
}
});
bthread("crud:P1:api/households/recipe-actions:1", function() {
let __args={}; let __parentBindings={};
function finish(reason){ sync({request:Event("SBT:WorkerFinished",{process:1,entity:"api/households/recipe-actions",owner:"P1:api/households/recipe-actions:1",reason:reason})}); }
function verified(stage){ sync({request:Event("SBT:CrudStep",{owner:"P1:api/households/recipe-actions:1",process:1,entity:"api/households/recipe-actions",stage:stage,values:Object.assign({},__args)})});sync({waitFor:EventSet("verified:P1:api/households/recipe-actions:1",function(e){return e.name==="SBT:CrudVerified" && e.data.owner==="P1:api/households/recipe-actions:1" && e.data.stage===stage;})}); }
  let __p1_apiHouseholdsRecipeActions_1_actionType = "link";
  let __p1_apiHouseholdsRecipeActions_1_title = "title_42221";
  let __p1_apiHouseholdsRecipeActions_1_url = "url_62185";
__args["actionType"]=__p1_apiHouseholdsRecipeActions_1_actionType;
__args["title"]=__p1_apiHouseholdsRecipeActions_1_title;
__args["url"]=__p1_apiHouseholdsRecipeActions_1_url;
sbtHttp_71(__args);
__args["itemId"]="@{sbt_P1_api_households_recipe_actions_1_itemId}";
sbtHttp_72(__args);
verified("readback");
verified("create");
sync({request:Event("SBT:InstanceReady",{process:1,entity:"api/households/recipe-actions",owner:"P1:api/households/recipe-actions:1",values:Object.assign({},__args)})});
sbtHttp_73(__args);
verified("read");
sbtHttp_74(__args);
verified("update");
sbtHttp_75(__args);
verified("delete");
finish("complete");
});
bthread("children:P1:api/households/shopping/lists:1", function(){
let finished={}; let cleanup=false; let remaining=1;
while(remaining>0 || !cleanup){
let event=sync({waitFor:EventSet("child-finish:P1:api/households/shopping/lists:1",function(e){return e.data && ((e.name==="SBT:WorkerFinished" && ["P1:api/households/shopping/items:1"].indexOf(e.data.owner)>=0) || (e.name==="SBT:CleanupReady" && e.data.owner==="P1:api/households/shopping/lists:1"));})});
if(event.name==="SBT:CleanupReady") cleanup=true;
else if(!finished[event.data.owner]){finished[event.data.owner]=true; remaining--;}
}
sync({request:Event("SBT:ChildrenFinished",{owner:"P1:api/households/shopping/lists:1"})});
});
bthread("verify:P1:api/households/shopping/lists:1", function(){
for (let stage of ["readback", "create", "read", "delete"]) {
let step=sync({waitFor:EventSet("step-or-finish:P1:api/households/shopping/lists:1",function(e){return e.data && e.data.owner==="P1:api/households/shopping/lists:1" && ((e.name==="SBT:CrudStep" && e.data.stage===stage) || e.name==="SBT:WorkerFinished");})});
if(step.name==="SBT:WorkerFinished") return;
if(stage==="create" || stage==="readback") {
sbtHttp_76(step.data.values);
}
sync({request:Event("SBT:CrudVerified",{owner:"P1:api/households/shopping/lists:1",stage:stage,ok:true})});
}
});
bthread("crud:P1:api/households/shopping/lists:1", function() {
let __args={}; let __parentBindings={};
function finish(reason){ sync({request:Event("SBT:WorkerFinished",{process:1,entity:"api/households/shopping/lists",owner:"P1:api/households/shopping/lists:1",reason:reason})}); }
function verified(stage){ sync({request:Event("SBT:CrudStep",{owner:"P1:api/households/shopping/lists:1",process:1,entity:"api/households/shopping/lists",stage:stage,values:Object.assign({},__args)})});sync({waitFor:EventSet("verified:P1:api/households/shopping/lists:1",function(e){return e.name==="SBT:CrudVerified" && e.data.owner==="P1:api/households/shopping/lists:1" && e.data.stage===stage;})}); }
sbtHttp_77(__args);
__args["itemId"]="@{sbt_P1_api_households_shopping_lists_1_itemId}";
sbtHttp_78(__args);
verified("readback");
verified("create");
sync({request:Event("SBT:InstanceReady",{process:1,entity:"api/households/shopping/lists",owner:"P1:api/households/shopping/lists:1",values:Object.assign({},__args)})});
sbtHttp_79(__args);
verified("read");
sync({request:Event("SBT:CleanupReady",{owner:"P1:api/households/shopping/lists:1"})});
sync({waitFor:EventSet("children-done:P1:api/households/shopping/lists:1",function(e){return e.name==="SBT:ChildrenFinished" && e.data.owner==="P1:api/households/shopping/lists:1";})});
sbtHttp_80(__args);
verified("delete");
finish("complete");
});
bthread("verify:P1:api/households/webhooks:1", function(){
for (let stage of ["readback", "create", "read", "update", "delete"]) {
let step=sync({waitFor:EventSet("step-or-finish:P1:api/households/webhooks:1",function(e){return e.data && e.data.owner==="P1:api/households/webhooks:1" && ((e.name==="SBT:CrudStep" && e.data.stage===stage) || e.name==="SBT:WorkerFinished");})});
if(step.name==="SBT:WorkerFinished") return;
if(stage==="create" || stage==="readback") {
sbtHttp_81(step.data.values);
}
if(stage==="update") sbtHttp_82(step.data.values);
sync({request:Event("SBT:CrudVerified",{owner:"P1:api/households/webhooks:1",stage:stage,ok:true})});
}
});
bthread("crud:P1:api/households/webhooks:1", function() {
let __args={}; let __parentBindings={};
function finish(reason){ sync({request:Event("SBT:WorkerFinished",{process:1,entity:"api/households/webhooks",owner:"P1:api/households/webhooks:1",reason:reason})}); }
function verified(stage){ sync({request:Event("SBT:CrudStep",{owner:"P1:api/households/webhooks:1",process:1,entity:"api/households/webhooks",stage:stage,values:Object.assign({},__args)})});sync({waitFor:EventSet("verified:P1:api/households/webhooks:1",function(e){return e.name==="SBT:CrudVerified" && e.data.owner==="P1:api/households/webhooks:1" && e.data.stage===stage;})}); }
  let __p1_apiHouseholdsWebhooks_1_scheduledTime = "scheduledTime_14834";
__args["scheduledTime"]=__p1_apiHouseholdsWebhooks_1_scheduledTime;
__args["name"]="";
sbtHttp_83(__args);
__args["itemId"]="@{sbt_P1_api_households_webhooks_1_itemId}";
sbtHttp_84(__args);
verified("readback");
verified("create");
sync({request:Event("SBT:InstanceReady",{process:1,entity:"api/households/webhooks",owner:"P1:api/households/webhooks:1",values:Object.assign({},__args)})});
sbtHttp_85(__args);
verified("read");
sbtHttp_86(__args);
verified("update");
sbtHttp_87(__args);
verified("delete");
finish("complete");
});
bthread("verify:P1:api/organizers/categories:1", function(){
for (let stage of ["readback", "create", "read", "update", "delete"]) {
let step=sync({waitFor:EventSet("step-or-finish:P1:api/organizers/categories:1",function(e){return e.data && e.data.owner==="P1:api/organizers/categories:1" && ((e.name==="SBT:CrudStep" && e.data.stage===stage) || e.name==="SBT:WorkerFinished");})});
if(step.name==="SBT:WorkerFinished") return;
if(stage==="create" || stage==="readback") {
sbtHttp_88(step.data.values);
}
if(stage==="update") sbtHttp_89(step.data.values);
sync({request:Event("SBT:CrudVerified",{owner:"P1:api/organizers/categories:1",stage:stage,ok:true})});
}
});
bthread("crud:P1:api/organizers/categories:1", function() {
let __args={}; let __parentBindings={};
function finish(reason){ sync({request:Event("SBT:WorkerFinished",{process:1,entity:"api/organizers/categories",owner:"P1:api/organizers/categories:1",reason:reason})}); }
function verified(stage){ sync({request:Event("SBT:CrudStep",{owner:"P1:api/organizers/categories:1",process:1,entity:"api/organizers/categories",stage:stage,values:Object.assign({},__args)})});sync({waitFor:EventSet("verified:P1:api/organizers/categories:1",function(e){return e.name==="SBT:CrudVerified" && e.data.owner==="P1:api/organizers/categories:1" && e.data.stage===stage;})}); }
  let __p1_apiOrganizersCategories_1_name = "name_37975";
__args["name"]=__p1_apiOrganizersCategories_1_name;
sbtHttp_90(__args);
__args["itemId"]="@{sbt_P1_api_organizers_categories_1_itemId}";
sbtHttp_91(__args);
verified("readback");
verified("create");
sync({request:Event("SBT:InstanceReady",{process:1,entity:"api/organizers/categories",owner:"P1:api/organizers/categories:1",values:Object.assign({},__args)})});
sbtHttp_92(__args);
verified("read");
sbtHttp_93(__args);
verified("update");
sbtHttp_94(__args);
verified("delete");
finish("complete");
});
bthread("verify:P1:api/organizers/tags:1", function(){
for (let stage of ["readback", "create", "read", "update", "delete"]) {
let step=sync({waitFor:EventSet("step-or-finish:P1:api/organizers/tags:1",function(e){return e.data && e.data.owner==="P1:api/organizers/tags:1" && ((e.name==="SBT:CrudStep" && e.data.stage===stage) || e.name==="SBT:WorkerFinished");})});
if(step.name==="SBT:WorkerFinished") return;
if(stage==="create" || stage==="readback") {
sbtHttp_95(step.data.values);
}
if(stage==="update") sbtHttp_96(step.data.values);
sync({request:Event("SBT:CrudVerified",{owner:"P1:api/organizers/tags:1",stage:stage,ok:true})});
}
});
bthread("crud:P1:api/organizers/tags:1", function() {
let __args={}; let __parentBindings={};
function finish(reason){ sync({request:Event("SBT:WorkerFinished",{process:1,entity:"api/organizers/tags",owner:"P1:api/organizers/tags:1",reason:reason})}); }
function verified(stage){ sync({request:Event("SBT:CrudStep",{owner:"P1:api/organizers/tags:1",process:1,entity:"api/organizers/tags",stage:stage,values:Object.assign({},__args)})});sync({waitFor:EventSet("verified:P1:api/organizers/tags:1",function(e){return e.name==="SBT:CrudVerified" && e.data.owner==="P1:api/organizers/tags:1" && e.data.stage===stage;})}); }
  let __p1_apiOrganizersTags_1_name = "name_4123";
__args["name"]=__p1_apiOrganizersTags_1_name;
sbtHttp_97(__args);
__args["itemId"]="@{sbt_P1_api_organizers_tags_1_itemId}";
sbtHttp_98(__args);
verified("readback");
verified("create");
sync({request:Event("SBT:InstanceReady",{process:1,entity:"api/organizers/tags",owner:"P1:api/organizers/tags:1",values:Object.assign({},__args)})});
sbtHttp_99(__args);
verified("read");
sbtHttp_100(__args);
verified("update");
sbtHttp_101(__args);
verified("delete");
finish("complete");
});
bthread("verify:P1:api/organizers/tools:1", function(){
for (let stage of ["readback", "create", "read", "update", "delete"]) {
let step=sync({waitFor:EventSet("step-or-finish:P1:api/organizers/tools:1",function(e){return e.data && e.data.owner==="P1:api/organizers/tools:1" && ((e.name==="SBT:CrudStep" && e.data.stage===stage) || e.name==="SBT:WorkerFinished");})});
if(step.name==="SBT:WorkerFinished") return;
if(stage==="create" || stage==="readback") {
sbtHttp_102(step.data.values);
}
if(stage==="update") sbtHttp_103(step.data.values);
sync({request:Event("SBT:CrudVerified",{owner:"P1:api/organizers/tools:1",stage:stage,ok:true})});
}
});
bthread("crud:P1:api/organizers/tools:1", function() {
let __args={}; let __parentBindings={};
function finish(reason){ sync({request:Event("SBT:WorkerFinished",{process:1,entity:"api/organizers/tools",owner:"P1:api/organizers/tools:1",reason:reason})}); }
function verified(stage){ sync({request:Event("SBT:CrudStep",{owner:"P1:api/organizers/tools:1",process:1,entity:"api/organizers/tools",stage:stage,values:Object.assign({},__args)})});sync({waitFor:EventSet("verified:P1:api/organizers/tools:1",function(e){return e.name==="SBT:CrudVerified" && e.data.owner==="P1:api/organizers/tools:1" && e.data.stage===stage;})}); }
  let __p1_apiOrganizersTools_1_name = "name_1015";
__args["name"]=__p1_apiOrganizersTools_1_name;
sbtHttp_104(__args);
__args["itemId"]="@{sbt_P1_api_organizers_tools_1_itemId}";
sbtHttp_105(__args);
verified("readback");
verified("create");
sync({request:Event("SBT:InstanceReady",{process:1,entity:"api/organizers/tools",owner:"P1:api/organizers/tools:1",values:Object.assign({},__args)})});
sbtHttp_106(__args);
verified("read");
sbtHttp_107(__args);
verified("update");
sbtHttp_108(__args);
verified("delete");
finish("complete");
});
bthread("children:P1:api/recipes:1", function(){
let finished={}; let cleanup=false; let remaining=2;
while(remaining>0 || !cleanup){
let event=sync({waitFor:EventSet("child-finish:P1:api/recipes:1",function(e){return e.data && ((e.name==="SBT:WorkerFinished" && ["P1:api/comments:1", "P1:api/recipes/timeline/events:1"].indexOf(e.data.owner)>=0) || (e.name==="SBT:CleanupReady" && e.data.owner==="P1:api/recipes:1"));})});
if(event.name==="SBT:CleanupReady") cleanup=true;
else if(!finished[event.data.owner]){finished[event.data.owner]=true; remaining--;}
}
sync({request:Event("SBT:ChildrenFinished",{owner:"P1:api/recipes:1"})});
});
bthread("verify:P1:api/recipes:1", function(){
for (let stage of ["readback", "create", "read", "update", "delete"]) {
let step=sync({waitFor:EventSet("step-or-finish:P1:api/recipes:1",function(e){return e.data && e.data.owner==="P1:api/recipes:1" && ((e.name==="SBT:CrudStep" && e.data.stage===stage) || e.name==="SBT:WorkerFinished");})});
if(step.name==="SBT:WorkerFinished") return;
if(stage==="create" || stage==="readback") {
sbtHttp_109(step.data.values);
}
if(stage==="update") sbtHttp_110(step.data.values);
sync({request:Event("SBT:CrudVerified",{owner:"P1:api/recipes:1",stage:stage,ok:true})});
}
});
bthread("crud:P1:api/recipes:1", function() {
let __args={}; let __parentBindings={};
function finish(reason){ sync({request:Event("SBT:WorkerFinished",{process:1,entity:"api/recipes",owner:"P1:api/recipes:1",reason:reason})}); }
function verified(stage){ sync({request:Event("SBT:CrudStep",{owner:"P1:api/recipes:1",process:1,entity:"api/recipes",stage:stage,values:Object.assign({},__args)})});sync({waitFor:EventSet("verified:P1:api/recipes:1",function(e){return e.name==="SBT:CrudVerified" && e.data.owner==="P1:api/recipes:1" && e.data.stage===stage;})}); }
  let __p1_apiRecipes_1_name = "name_8442";
__args["name"]=__p1_apiRecipes_1_name;
sbtHttp_111(__args);
__args["slug"]="@{sbt_P1_api_recipes_1_slug}";
sbtHttp_112(__args);
verified("readback");
verified("create");
sync({request:Event("SBT:InstanceReady",{process:1,entity:"api/recipes",owner:"P1:api/recipes:1",values:Object.assign({},__args)})});
sbtHttp_113(__args);
verified("read");
sbtHttp_114(__args);
verified("update");
sync({request:Event("SBT:CleanupReady",{owner:"P1:api/recipes:1"})});
sync({waitFor:EventSet("children-done:P1:api/recipes:1",function(e){return e.name==="SBT:ChildrenFinished" && e.data.owner==="P1:api/recipes:1";})});
sbtHttp_115(__args);
verified("delete");
finish("complete");
});
bthread("verify:P1:api/shared/recipes:1", function(){
for (let stage of ["readback", "create", "read", "delete"]) {
let step=sync({waitFor:EventSet("step-or-finish:P1:api/shared/recipes:1",function(e){return e.data && e.data.owner==="P1:api/shared/recipes:1" && ((e.name==="SBT:CrudStep" && e.data.stage===stage) || e.name==="SBT:WorkerFinished");})});
if(step.name==="SBT:WorkerFinished") return;
if(stage==="create" || stage==="readback") {
sbtHttp_116(step.data.values);
}
sync({request:Event("SBT:CrudVerified",{owner:"P1:api/shared/recipes:1",stage:stage,ok:true})});
}
});
bthread("crud:P1:api/shared/recipes:1", function() {
let __args={}; let __parentBindings={};
function finish(reason){ sync({request:Event("SBT:WorkerFinished",{process:1,entity:"api/shared/recipes",owner:"P1:api/shared/recipes:1",reason:reason})}); }
function verified(stage){ sync({request:Event("SBT:CrudStep",{owner:"P1:api/shared/recipes:1",process:1,entity:"api/shared/recipes",stage:stage,values:Object.assign({},__args)})});sync({waitFor:EventSet("verified:P1:api/shared/recipes:1",function(e){return e.name==="SBT:CrudVerified" && e.data.owner==="P1:api/shared/recipes:1" && e.data.stage===stage;})}); }
  let __p1_apiSharedRecipes_1_recipeId = "recipeId_51445";
__args["recipeId"]=__p1_apiSharedRecipes_1_recipeId;
sbtHttp_117(__args);
__args["itemId"]="@{sbt_P1_api_shared_recipes_1_itemId}";
sbtHttp_118(__args);
verified("readback");
verified("create");
sync({request:Event("SBT:InstanceReady",{process:1,entity:"api/shared/recipes",owner:"P1:api/shared/recipes:1",values:Object.assign({},__args)})});
sbtHttp_119(__args);
verified("read");
sbtHttp_120(__args);
verified("delete");
finish("complete");
});
bthread("verify:P1:api/units:1", function(){
for (let stage of ["readback", "create", "read", "update", "delete"]) {
let step=sync({waitFor:EventSet("step-or-finish:P1:api/units:1",function(e){return e.data && e.data.owner==="P1:api/units:1" && ((e.name==="SBT:CrudStep" && e.data.stage===stage) || e.name==="SBT:WorkerFinished");})});
if(step.name==="SBT:WorkerFinished") return;
if(stage==="create" || stage==="readback") {
sbtHttp_121(step.data.values);
}
if(stage==="update") sbtHttp_122(step.data.values);
sync({request:Event("SBT:CrudVerified",{owner:"P1:api/units:1",stage:stage,ok:true})});
}
});
bthread("crud:P1:api/units:1", function() {
let __args={}; let __parentBindings={};
function finish(reason){ sync({request:Event("SBT:WorkerFinished",{process:1,entity:"api/units",owner:"P1:api/units:1",reason:reason})}); }
function verified(stage){ sync({request:Event("SBT:CrudStep",{owner:"P1:api/units:1",process:1,entity:"api/units",stage:stage,values:Object.assign({},__args)})});sync({waitFor:EventSet("verified:P1:api/units:1",function(e){return e.name==="SBT:CrudVerified" && e.data.owner==="P1:api/units:1" && e.data.stage===stage;})}); }
  let __p1_apiUnits_1_name = "name_73174";
__args["name"]=__p1_apiUnits_1_name;
sbtHttp_123(__args);
__args["itemId"]="@{sbt_P1_api_units_1_itemId}";
sbtHttp_124(__args);
verified("readback");
verified("create");
sync({request:Event("SBT:InstanceReady",{process:1,entity:"api/units",owner:"P1:api/units:1",values:Object.assign({},__args)})});
sbtHttp_125(__args);
verified("read");
sbtHttp_126(__args);
verified("update");
sbtHttp_127(__args);
verified("delete");
finish("complete");
});
bthread("verify:P1:api/users/api-tokens:1", function(){
for (let stage of ["create", "delete"]) {
let step=sync({waitFor:EventSet("step-or-finish:P1:api/users/api-tokens:1",function(e){return e.data && e.data.owner==="P1:api/users/api-tokens:1" && ((e.name==="SBT:CrudStep" && e.data.stage===stage) || e.name==="SBT:WorkerFinished");})});
if(step.name==="SBT:WorkerFinished") return;
sync({request:Event("SBT:CrudVerified",{owner:"P1:api/users/api-tokens:1",stage:stage,ok:true})});
}
});
bthread("crud:P1:api/users/api-tokens:1", function() {
let __args={}; let __parentBindings={};
function finish(reason){ sync({request:Event("SBT:WorkerFinished",{process:1,entity:"api/users/api-tokens",owner:"P1:api/users/api-tokens:1",reason:reason})}); }
function verified(stage){ sync({request:Event("SBT:CrudStep",{owner:"P1:api/users/api-tokens:1",process:1,entity:"api/users/api-tokens",stage:stage,values:Object.assign({},__args)})});sync({waitFor:EventSet("verified:P1:api/users/api-tokens:1",function(e){return e.name==="SBT:CrudVerified" && e.data.owner==="P1:api/users/api-tokens:1" && e.data.stage===stage;})}); }
  let __p1_apiUsersApiTokens_1_name = "name_21958";
__args["name"]=__p1_apiUsersApiTokens_1_name;
sbtHttp_128(__args);
__args["tokenId"]="@{sbt_P1_api_users_api_tokens_1_tokenId}";
verified("create");
sync({request:Event("SBT:InstanceReady",{process:1,entity:"api/users/api-tokens",owner:"P1:api/users/api-tokens:1",values:Object.assign({},__args)})});
sbtHttp_129(__args);
verified("delete");
finish("complete");
});
bthread("bind:P1:api/admin/groups/{group_id}/ai-providers/providers:1", function(){
let available={}; let candidates=[]; let required=["api/admin/groups"];
while(true){
let first=available[required[0]]||[];
candidates=first.filter(function(anchor){return required.every(function(type){
return (available[type]||[]).some(function(parent){return anchor.values.realm===undefined || parent.values.realm===undefined || parent.values.realm===anchor.values.realm;});});});
if(candidates.length) break;
let ready=sync({waitFor:EventSet("any-parent:P1:api/admin/groups/{group_id}/ai-providers/providers:1",function(e){return e.name==="SBT:InstanceReady" && e.data && e.data.process===1 && required.indexOf(e.data.entity)>=0;})});
if(!available[ready.data.entity]) available[ready.data.entity]=[];
available[ready.data.entity].push({owner:ready.data.owner,values:ready.data.values});
}
let parents={};
let options=candidates.map(function(parent,index){return Event("SBT:BindParent",{child:"P1:api/admin/groups/{group_id}/ai-providers/providers:1",type:required[0],index:index});});
let chosen=sync({request:options});
let anchor=candidates[chosen.data.index]; parents[required[0]]=anchor.values;
for(let i=1;i<required.length;i++){
let type=required[i]; let matches=available[type].filter(function(parent){return anchor.values.realm===undefined || parent.values.realm===undefined || parent.values.realm===anchor.values.realm;});
let choices=matches.map(function(parent,index){return Event("SBT:BindParent",{child:"P1:api/admin/groups/{group_id}/ai-providers/providers:1",type:type,index:index});});
let picked=sync({request:choices}); parents[type]=matches[picked.data.index].values;
}
sync({request:Event("SBT:ParentsBound",{owner:"P1:api/admin/groups/{group_id}/ai-providers/providers:1",parents:parents})});
});
bthread("verify:P1:api/admin/groups/{group_id}/ai-providers/providers:1", function(){
for (let stage of ["readback", "create", "read", "update", "delete"]) {
let step=sync({waitFor:EventSet("step-or-finish:P1:api/admin/groups/{group_id}/ai-providers/providers:1",function(e){return e.data && e.data.owner==="P1:api/admin/groups/{group_id}/ai-providers/providers:1" && ((e.name==="SBT:CrudStep" && e.data.stage===stage) || e.name==="SBT:WorkerFinished");})});
if(step.name==="SBT:WorkerFinished") return;
if(stage==="create" || stage==="readback") {
sbtHttp_130(step.data.values);
}
if(stage==="update") sbtHttp_131(step.data.values);
sync({request:Event("SBT:CrudVerified",{owner:"P1:api/admin/groups/{group_id}/ai-providers/providers:1",stage:stage,ok:true})});
}
});
bthread("crud:P1:api/admin/groups/{group_id}/ai-providers/providers:1", function() {
let __args={}; let __parentBindings={};
function finish(reason){ sync({request:Event("SBT:WorkerFinished",{process:1,entity:"api/admin/groups/{group_id}/ai-providers/providers",owner:"P1:api/admin/groups/{group_id}/ai-providers/providers:1",reason:reason})}); }
function verified(stage){ sync({request:Event("SBT:CrudStep",{owner:"P1:api/admin/groups/{group_id}/ai-providers/providers:1",process:1,entity:"api/admin/groups/{group_id}/ai-providers/providers",stage:stage,values:Object.assign({},__args)})});sync({waitFor:EventSet("verified:P1:api/admin/groups/{group_id}/ai-providers/providers:1",function(e){return e.name==="SBT:CrudVerified" && e.data.owner==="P1:api/admin/groups/{group_id}/ai-providers/providers:1" && e.data.stage===stage;})}); }
let bound=sync({waitFor:EventSet("bound:P1:api/admin/groups/{group_id}/ai-providers/providers:1",function(e){return e.name==="SBT:ParentsBound" && e.data.owner==="P1:api/admin/groups/{group_id}/ai-providers/providers:1";})});
__parentBindings=bound.data.parents;
{
if(__args.realm===undefined && __parentBindings["api/admin/groups"].realm!==undefined) __args.realm=__parentBindings["api/admin/groups"].realm;
__args["groupId"]=__parentBindings["api/admin/groups"]["itemId"];
}
  let __p1_apiAdminGroupsGroupIdAiProvidersProviders_1_model = "model_13381";
  let __p1_apiAdminGroupsGroupIdAiProvidersProviders_1_name = "name_60971";
__args["groupId"]=__args["groupId"];
__args["model"]=__p1_apiAdminGroupsGroupIdAiProvidersProviders_1_model;
__args["name"]=__p1_apiAdminGroupsGroupIdAiProvidersProviders_1_name;
sbtHttp_132(__args);
__args["providerId"]="@{sbt_P1_api_admin_groups__group_id__ai_providers_providers_1_providerId}";
sbtHttp_133(__args);
verified("readback");
verified("create");
sync({request:Event("SBT:InstanceReady",{process:1,entity:"api/admin/groups/{group_id}/ai-providers/providers",owner:"P1:api/admin/groups/{group_id}/ai-providers/providers:1",values:Object.assign({},__args)})});
sbtHttp_134(__args);
verified("read");
sbtHttp_135(__args);
verified("update");
sbtHttp_136(__args);
verified("delete");
finish("complete");
});
bthread("bind:P1:api/admin/households:1", function(){
let available={}; let candidates=[]; let required=["api/admin/groups"];
while(true){
let first=available[required[0]]||[];
candidates=first.filter(function(anchor){return required.every(function(type){
return (available[type]||[]).some(function(parent){return anchor.values.realm===undefined || parent.values.realm===undefined || parent.values.realm===anchor.values.realm;});});});
if(candidates.length) break;
let ready=sync({waitFor:EventSet("any-parent:P1:api/admin/households:1",function(e){return e.name==="SBT:InstanceReady" && e.data && e.data.process===1 && required.indexOf(e.data.entity)>=0;})});
if(!available[ready.data.entity]) available[ready.data.entity]=[];
available[ready.data.entity].push({owner:ready.data.owner,values:ready.data.values});
}
let parents={};
let options=candidates.map(function(parent,index){return Event("SBT:BindParent",{child:"P1:api/admin/households:1",type:required[0],index:index});});
let chosen=sync({request:options});
let anchor=candidates[chosen.data.index]; parents[required[0]]=anchor.values;
for(let i=1;i<required.length;i++){
let type=required[i]; let matches=available[type].filter(function(parent){return anchor.values.realm===undefined || parent.values.realm===undefined || parent.values.realm===anchor.values.realm;});
let choices=matches.map(function(parent,index){return Event("SBT:BindParent",{child:"P1:api/admin/households:1",type:type,index:index});});
let picked=sync({request:choices}); parents[type]=matches[picked.data.index].values;
}
sync({request:Event("SBT:ParentsBound",{owner:"P1:api/admin/households:1",parents:parents})});
});
bthread("verify:P1:api/admin/households:1", function(){
for (let stage of ["readback", "create", "read", "update", "delete"]) {
let step=sync({waitFor:EventSet("step-or-finish:P1:api/admin/households:1",function(e){return e.data && e.data.owner==="P1:api/admin/households:1" && ((e.name==="SBT:CrudStep" && e.data.stage===stage) || e.name==="SBT:WorkerFinished");})});
if(step.name==="SBT:WorkerFinished") return;
if(stage==="create" || stage==="readback") {
sbtHttp_137(step.data.values);
}
if(stage==="update") sbtHttp_138(step.data.values);
sync({request:Event("SBT:CrudVerified",{owner:"P1:api/admin/households:1",stage:stage,ok:true})});
}
});
bthread("crud:P1:api/admin/households:1", function() {
let __args={}; let __parentBindings={};
function finish(reason){ sync({request:Event("SBT:WorkerFinished",{process:1,entity:"api/admin/households",owner:"P1:api/admin/households:1",reason:reason})}); }
function verified(stage){ sync({request:Event("SBT:CrudStep",{owner:"P1:api/admin/households:1",process:1,entity:"api/admin/households",stage:stage,values:Object.assign({},__args)})});sync({waitFor:EventSet("verified:P1:api/admin/households:1",function(e){return e.name==="SBT:CrudVerified" && e.data.owner==="P1:api/admin/households:1" && e.data.stage===stage;})}); }
let bound=sync({waitFor:EventSet("bound:P1:api/admin/households:1",function(e){return e.name==="SBT:ParentsBound" && e.data.owner==="P1:api/admin/households:1";})});
__parentBindings=bound.data.parents;
{
if(__args.realm===undefined && __parentBindings["api/admin/groups"].realm!==undefined) __args.realm=__parentBindings["api/admin/groups"].realm;
__args["groupId"]=__parentBindings["api/admin/groups"]["itemId"];
}
  let __p1_apiAdminHouseholds_1_name = "name_50193";
__args["groupId"]=__args["groupId"];
__args["name"]=__p1_apiAdminHouseholds_1_name;
sbtHttp_139(__args);
__args["itemId"]="@{sbt_P1_api_admin_households_1_itemId}";
sbtHttp_140(__args);
verified("readback");
verified("create");
sync({request:Event("SBT:InstanceReady",{process:1,entity:"api/admin/households",owner:"P1:api/admin/households:1",values:Object.assign({},__args)})});
sbtHttp_141(__args);
verified("read");
sbtHttp_142(__args);
verified("update");
sbtHttp_143(__args);
verified("delete");
finish("complete");
});
bthread("bind:P1:api/comments:1", function(){
let available={}; let candidates=[]; let required=["api/recipes"];
while(true){
let first=available[required[0]]||[];
candidates=first.filter(function(anchor){return required.every(function(type){
return (available[type]||[]).some(function(parent){return anchor.values.realm===undefined || parent.values.realm===undefined || parent.values.realm===anchor.values.realm;});});});
if(candidates.length) break;
let ready=sync({waitFor:EventSet("any-parent:P1:api/comments:1",function(e){return e.name==="SBT:InstanceReady" && e.data && e.data.process===1 && required.indexOf(e.data.entity)>=0;})});
if(!available[ready.data.entity]) available[ready.data.entity]=[];
available[ready.data.entity].push({owner:ready.data.owner,values:ready.data.values});
}
let parents={};
let options=candidates.map(function(parent,index){return Event("SBT:BindParent",{child:"P1:api/comments:1",type:required[0],index:index});});
let chosen=sync({request:options});
let anchor=candidates[chosen.data.index]; parents[required[0]]=anchor.values;
for(let i=1;i<required.length;i++){
let type=required[i]; let matches=available[type].filter(function(parent){return anchor.values.realm===undefined || parent.values.realm===undefined || parent.values.realm===anchor.values.realm;});
let choices=matches.map(function(parent,index){return Event("SBT:BindParent",{child:"P1:api/comments:1",type:type,index:index});});
let picked=sync({request:choices}); parents[type]=matches[picked.data.index].values;
}
sync({request:Event("SBT:ParentsBound",{owner:"P1:api/comments:1",parents:parents})});
});
bthread("verify:P1:api/comments:1", function(){
for (let stage of ["readback", "create", "read", "update", "delete"]) {
let step=sync({waitFor:EventSet("step-or-finish:P1:api/comments:1",function(e){return e.data && e.data.owner==="P1:api/comments:1" && ((e.name==="SBT:CrudStep" && e.data.stage===stage) || e.name==="SBT:WorkerFinished");})});
if(step.name==="SBT:WorkerFinished") return;
if(stage==="create" || stage==="readback") {
sbtHttp_144(step.data.values);
}
if(stage==="update") sbtHttp_145(step.data.values);
sync({request:Event("SBT:CrudVerified",{owner:"P1:api/comments:1",stage:stage,ok:true})});
}
});
bthread("crud:P1:api/comments:1", function() {
let __args={}; let __parentBindings={};
function finish(reason){ sync({request:Event("SBT:WorkerFinished",{process:1,entity:"api/comments",owner:"P1:api/comments:1",reason:reason})}); }
function verified(stage){ sync({request:Event("SBT:CrudStep",{owner:"P1:api/comments:1",process:1,entity:"api/comments",stage:stage,values:Object.assign({},__args)})});sync({waitFor:EventSet("verified:P1:api/comments:1",function(e){return e.name==="SBT:CrudVerified" && e.data.owner==="P1:api/comments:1" && e.data.stage===stage;})}); }
let bound=sync({waitFor:EventSet("bound:P1:api/comments:1",function(e){return e.name==="SBT:ParentsBound" && e.data.owner==="P1:api/comments:1";})});
__parentBindings=bound.data.parents;
{
if(__args.realm===undefined && __parentBindings["api/recipes"].realm!==undefined) __args.realm=__parentBindings["api/recipes"].realm;
__args["recipeId"]=__parentBindings["api/recipes"]["slug"];
}
  let __p1_apiComments_1_text = "text_13431";
__args["recipeId"]=__args["recipeId"];
__args["text"]=__p1_apiComments_1_text;
sbtHttp_146(__args);
__args["itemId"]="@{sbt_P1_api_comments_1_itemId}";
sbtHttp_147(__args);
verified("readback");
verified("create");
sync({request:Event("SBT:InstanceReady",{process:1,entity:"api/comments",owner:"P1:api/comments:1",values:Object.assign({},__args)})});
sbtHttp_148(__args);
verified("read");
sbtHttp_149(__args);
verified("update");
sbtHttp_150(__args);
verified("delete");
finish("complete");
});
bthread("bind:P1:api/households/shopping/items:1", function(){
let available={}; let candidates=[]; let required=["api/households/shopping/lists"];
while(true){
let first=available[required[0]]||[];
candidates=first.filter(function(anchor){return required.every(function(type){
return (available[type]||[]).some(function(parent){return anchor.values.realm===undefined || parent.values.realm===undefined || parent.values.realm===anchor.values.realm;});});});
if(candidates.length) break;
let ready=sync({waitFor:EventSet("any-parent:P1:api/households/shopping/items:1",function(e){return e.name==="SBT:InstanceReady" && e.data && e.data.process===1 && required.indexOf(e.data.entity)>=0;})});
if(!available[ready.data.entity]) available[ready.data.entity]=[];
available[ready.data.entity].push({owner:ready.data.owner,values:ready.data.values});
}
let parents={};
let options=candidates.map(function(parent,index){return Event("SBT:BindParent",{child:"P1:api/households/shopping/items:1",type:required[0],index:index});});
let chosen=sync({request:options});
let anchor=candidates[chosen.data.index]; parents[required[0]]=anchor.values;
for(let i=1;i<required.length;i++){
let type=required[i]; let matches=available[type].filter(function(parent){return anchor.values.realm===undefined || parent.values.realm===undefined || parent.values.realm===anchor.values.realm;});
let choices=matches.map(function(parent,index){return Event("SBT:BindParent",{child:"P1:api/households/shopping/items:1",type:type,index:index});});
let picked=sync({request:choices}); parents[type]=matches[picked.data.index].values;
}
sync({request:Event("SBT:ParentsBound",{owner:"P1:api/households/shopping/items:1",parents:parents})});
});
bthread("verify:P1:api/households/shopping/items:1", function(){
for (let stage of ["readback", "create", "read", "update", "delete"]) {
let step=sync({waitFor:EventSet("step-or-finish:P1:api/households/shopping/items:1",function(e){return e.data && e.data.owner==="P1:api/households/shopping/items:1" && ((e.name==="SBT:CrudStep" && e.data.stage===stage) || e.name==="SBT:WorkerFinished");})});
if(step.name==="SBT:WorkerFinished") return;
if(stage==="create" || stage==="readback") {
sbtHttp_151(step.data.values);
}
if(stage==="update") sbtHttp_152(step.data.values);
sync({request:Event("SBT:CrudVerified",{owner:"P1:api/households/shopping/items:1",stage:stage,ok:true})});
}
});
bthread("crud:P1:api/households/shopping/items:1", function() {
let __args={}; let __parentBindings={};
function finish(reason){ sync({request:Event("SBT:WorkerFinished",{process:1,entity:"api/households/shopping/items",owner:"P1:api/households/shopping/items:1",reason:reason})}); }
function verified(stage){ sync({request:Event("SBT:CrudStep",{owner:"P1:api/households/shopping/items:1",process:1,entity:"api/households/shopping/items",stage:stage,values:Object.assign({},__args)})});sync({waitFor:EventSet("verified:P1:api/households/shopping/items:1",function(e){return e.name==="SBT:CrudVerified" && e.data.owner==="P1:api/households/shopping/items:1" && e.data.stage===stage;})}); }
let bound=sync({waitFor:EventSet("bound:P1:api/households/shopping/items:1",function(e){return e.name==="SBT:ParentsBound" && e.data.owner==="P1:api/households/shopping/items:1";})});
__parentBindings=bound.data.parents;
{
if(__args.realm===undefined && __parentBindings["api/households/shopping/lists"].realm!==undefined) __args.realm=__parentBindings["api/households/shopping/lists"].realm;
__args["shoppingListId"]=__parentBindings["api/households/shopping/lists"]["itemId"];
}
__args["shoppingListId"]=__args["shoppingListId"];
sbtHttp_153(__args);
__args["itemId"]="@{sbt_P1_api_households_shopping_items_1_itemId}";
sbtHttp_154(__args);
verified("readback");
verified("create");
sync({request:Event("SBT:InstanceReady",{process:1,entity:"api/households/shopping/items",owner:"P1:api/households/shopping/items:1",values:Object.assign({},__args)})});
sbtHttp_155(__args);
verified("read");
sbtHttp_156(__args);
verified("update");
sbtHttp_157(__args);
verified("delete");
finish("complete");
});
bthread("bind:P1:api/recipes/timeline/events:1", function(){
let available={}; let candidates=[]; let required=["api/recipes"];
while(true){
let first=available[required[0]]||[];
candidates=first.filter(function(anchor){return required.every(function(type){
return (available[type]||[]).some(function(parent){return anchor.values.realm===undefined || parent.values.realm===undefined || parent.values.realm===anchor.values.realm;});});});
if(candidates.length) break;
let ready=sync({waitFor:EventSet("any-parent:P1:api/recipes/timeline/events:1",function(e){return e.name==="SBT:InstanceReady" && e.data && e.data.process===1 && required.indexOf(e.data.entity)>=0;})});
if(!available[ready.data.entity]) available[ready.data.entity]=[];
available[ready.data.entity].push({owner:ready.data.owner,values:ready.data.values});
}
let parents={};
let options=candidates.map(function(parent,index){return Event("SBT:BindParent",{child:"P1:api/recipes/timeline/events:1",type:required[0],index:index});});
let chosen=sync({request:options});
let anchor=candidates[chosen.data.index]; parents[required[0]]=anchor.values;
for(let i=1;i<required.length;i++){
let type=required[i]; let matches=available[type].filter(function(parent){return anchor.values.realm===undefined || parent.values.realm===undefined || parent.values.realm===anchor.values.realm;});
let choices=matches.map(function(parent,index){return Event("SBT:BindParent",{child:"P1:api/recipes/timeline/events:1",type:type,index:index});});
let picked=sync({request:choices}); parents[type]=matches[picked.data.index].values;
}
sync({request:Event("SBT:ParentsBound",{owner:"P1:api/recipes/timeline/events:1",parents:parents})});
});
bthread("verify:P1:api/recipes/timeline/events:1", function(){
for (let stage of ["readback", "create", "read", "update", "delete"]) {
let step=sync({waitFor:EventSet("step-or-finish:P1:api/recipes/timeline/events:1",function(e){return e.data && e.data.owner==="P1:api/recipes/timeline/events:1" && ((e.name==="SBT:CrudStep" && e.data.stage===stage) || e.name==="SBT:WorkerFinished");})});
if(step.name==="SBT:WorkerFinished") return;
if(stage==="create" || stage==="readback") {
sbtHttp_158(step.data.values);
}
if(stage==="update") sbtHttp_159(step.data.values);
sync({request:Event("SBT:CrudVerified",{owner:"P1:api/recipes/timeline/events:1",stage:stage,ok:true})});
}
});
bthread("crud:P1:api/recipes/timeline/events:1", function() {
let __args={}; let __parentBindings={};
function finish(reason){ sync({request:Event("SBT:WorkerFinished",{process:1,entity:"api/recipes/timeline/events",owner:"P1:api/recipes/timeline/events:1",reason:reason})}); }
function verified(stage){ sync({request:Event("SBT:CrudStep",{owner:"P1:api/recipes/timeline/events:1",process:1,entity:"api/recipes/timeline/events",stage:stage,values:Object.assign({},__args)})});sync({waitFor:EventSet("verified:P1:api/recipes/timeline/events:1",function(e){return e.name==="SBT:CrudVerified" && e.data.owner==="P1:api/recipes/timeline/events:1" && e.data.stage===stage;})}); }
let bound=sync({waitFor:EventSet("bound:P1:api/recipes/timeline/events:1",function(e){return e.name==="SBT:ParentsBound" && e.data.owner==="P1:api/recipes/timeline/events:1";})});
__parentBindings=bound.data.parents;
{
if(__args.realm===undefined && __parentBindings["api/recipes"].realm!==undefined) __args.realm=__parentBindings["api/recipes"].realm;
__args["recipeId"]=__parentBindings["api/recipes"]["slug"];
}
  let __p1_apiRecipesTimelineEvents_1_eventType = "comment";
  let __p1_apiRecipesTimelineEvents_1_subject = "subject_45462";
__args["recipeId"]=__args["recipeId"];
__args["eventType"]=__p1_apiRecipesTimelineEvents_1_eventType;
__args["subject"]=__p1_apiRecipesTimelineEvents_1_subject;
sbtHttp_160(__args);
__args["itemId"]="@{sbt_P1_api_recipes_timeline_events_1_itemId}";
sbtHttp_161(__args);
verified("readback");
verified("create");
sync({request:Event("SBT:InstanceReady",{process:1,entity:"api/recipes/timeline/events",owner:"P1:api/recipes/timeline/events:1",values:Object.assign({},__args)})});
sbtHttp_162(__args);
verified("read");
sbtHttp_163(__args);
verified("update");
sbtHttp_164(__args);
verified("delete");
finish("complete");
});
