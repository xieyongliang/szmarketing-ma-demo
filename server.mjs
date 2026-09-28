import http from 'node:http';
import {readFile,writeFile,mkdir,rename} from 'node:fs/promises';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {randomUUID} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {phases,jsonObject,validateBrief,canRun,validatePlan,validateReview,turnResult} from './core.mjs';
import {cloudLimits,runCloud} from './cloud.mjs';
const root=fileURLToPath(new URL('.',import.meta.url));process.chdir(root);
const port=Number(process.env.PORT||8790), exec=promisify(execFile), base='https://ark.ap-southeast.bytepluses.com/api/v3';
await mkdir('data',{recursive:true});
let jobs={};try{jobs=JSON.parse(await readFile('data/jobs.json','utf8'));}catch(e){if(e.code!=='ENOENT')throw e;}
for(const j of Object.values(jobs))if(j.busy){j.busy=false;if(j.cloud){j.cloud.status='error';j.cloud.error='Local observer restarted. Resume observation of the same Cloud Session.';}for(const s of Object.values(j.steps))if(s.status==='running'){s.status='error';s.error='Server restarted. Inspect retained session/task before retrying.';}}
let saveQueue=Promise.resolve();function save(){const snapshot=JSON.stringify(jobs,null,2);saveQueue=saveQueue.then(async()=>{await writeFile('data/jobs.tmp',snapshot,{mode:0o600});await rename('data/jobs.tmp','data/jobs.json');});return saveQueue;}
function safeError(e){return String(e.message||e).replace(/Bearer\s+\S+/gi,'Bearer [redacted]').replaceAll(process.env.ARK_API_KEY||'__no_key__','[redacted]').slice(0,1200);}
async function cli(args,skill='arkcli-agent',timeout=90000){
  let stdout;
  try{const pending=exec('arkcli',[...args,'--format','json'],{timeout,maxBuffer:8e6,env:{...process.env,ARKCLI_NO_UPDATE_NOTIFIER:'1',ARKCLI_CALLER_TYPE:'ai_agent',ARKCLI_CALLER_NAME:'codex',ARKCLI_SKILL_NAME:skill}});pending.child.stdin.end();({stdout}=await pending);}
  catch(e){let detail;try{detail=JSON.parse(e.stdout).error?.message;}catch{}throw Error(detail||e.stderr?.trim()||'ArkCLI failed or timed out; inspect the retained session/task.');}
  const x=JSON.parse(stdout);if(x.ok===false)throw Error(x.error?.message||'ArkCLI failed');return x;
}
function idOf(x){return x.Result?.Id||x.result?.id||x.id;}
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function ma(job,prompt,step){
  if(!job.session){const s=await cli(['agent','session','create','--agent-id',process.env.MA_AGENT_ID,'--environment-id',process.env.MA_ENVIRONMENT_ID,'--title',`sz-${job.id}`]);job.session=idOf(s);if(!job.session)throw Error('No session ID returned');await save();}
  if(!step.sent){
    if(step.sendStarted)throw Error('Previous send has uncertain outcome. Inspect '+job.session+' before sending again.');
    const history=await cli(['agent','session','events','list',job.session,'--order','desc','--limit','1']);
    step.cursor=(history.data||[])[0]?.id||null;
    step.sendStarted=true;await save();
    step.sent=await cli(['agent','session','events','send',job.session,'--type','user.message','--text',prompt]);await save();
  }
  // Correlate to the accepted user event: this deployment ignores --after.
  const messageId=step.sent.data?.[0]?.id;
  if(!messageId)throw Error('Missing accepted user event ID; inspect '+job.session);
  if(step.completedFor===messageId&&step.completedText)return jsonObject(step.completedText);
  for(let i=0;i<180;i++){
    const r=await cli(['agent','session','events','list',job.session,'--order','asc','--limit','100','--page-all']);
    const events=r.data;if(!Array.isArray(events))throw Error('Unrecognized MA event response');
    const text=turnResult(events,messageId);
    if(text){step.completedText=text;step.completedFor=messageId;await save();return jsonObject(text);}
    await save();await pause(2000);
  }throw Error('MA observation timeout; inspect session '+job.session+' before retry. No automatic resend.');
}
async function api(path,body){
 if(!process.env.ARK_API_KEY){
  const actions={'/images/generations':'arkruntime.generate_images','/responses':'arkruntime.create_responses','/contents/generations/tasks':'arkruntime.create_content_generation_task'};
  const action=actions[path]||(!body&&path.startsWith('/contents/generations/tasks/')?'arkruntime.get_content_generation_task':null);
  if(!action)throw Error('Unsupported model API route');
  return cli(['api',action,'--params',JSON.stringify(body||{id:path.split('/').at(-1)})],'arkcli-api-explorer',300000);
 }
 const r=await fetch(base+path,{method:body?'POST':'GET',headers:{Authorization:`Bearer ${process.env.ARK_API_KEY}`,'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(240000)});const x=await r.json();if(!r.ok)throw Error(`Model API ${r.status}: ${JSON.stringify(x)}`);return x;
}
async function image(prompt,reference){
 const model=process.env.IMAGE_MODEL||'seedream-4-5-251128';
 const x=await api('/images/generations',{model,prompt,size:'2K',response_format:'url',watermark:true,...(reference?{image:reference}:{})});const url=x.data?.[0]?.url;if(!url)throw Error('Image generation returned no URL');return {url,usage:x.usage,model};
}
async function observe(job){
 const content=[{type:'input_text',text:'Inspect these actual assets for a POD campaign. Image 1 must be isolated flat 2D artwork, not a product photo: explicitly report whether it satisfies this requirement. Image 2 is the product mockup. Report observable print text, visual fidelity across print/mockup/video, product deformation, video actions, visible claims and uncertainty. Do not infer sales, policy approval or print DPI. Clearly state whether audio was accessible. Return factual observations only.'},{type:'input_image',image_url:job.steps.design.result.url},{type:'input_image',image_url:job.steps.mockup.result.url},{type:'input_video',video_url:job.steps.video.result.url,fps:1}];
 const x=await api('/responses',{model:process.env.VISION_MODEL||'seed-2-0-lite-260428',stream:false,input:[{role:'user',content}]});
 if(x.status!=='completed')throw Error('Video understanding did not complete: '+x.status);
 const text=(x.output||[]).flatMap(o=>o.content||[]).filter(c=>c.type==='output_text').map(c=>c.text).join('\n');if(!text)throw Error('No visual evidence returned');return {text,response_id:x.id,usage:x.usage};
}
async function run(job,phase){const step=job.steps[phase]={status:'running',started:new Date().toISOString(),...(job.steps[phase]||{} )};step.status='running';delete step.error;job.busy=true;await save();
 try{
  const c=job.steps.research?.result?.concepts?.[job.selected||0];
  if(phase==='research')step.result=validatePlan(await ma(job,`Plan this campaign. Use at most 3 web searches. Return the planning JSON schema. Separate verified observations from hypotheses. Brief: ${JSON.stringify(job.brief)}`,step));
  if(phase==='design'){step.prompt=job.prompts?.design||`Create ONLY a flat 2D graphic artwork on a plain white canvas. NOT a product photo. Do not draw any cup, mug, handle, shirt, model, room, tabletop, shadows, curved surface or mockup. Brief: ${job.brief.brief}. Creative direction (extract illustration, typography and colors ONLY, ignore any substrate or print-production instructions): ${c.print_prompt}. Final output must be the isolated flat artwork itself, edge-on product views are forbidden.`;step.result=await image(step.prompt);}
  if(phase==='mockup'){step.prompt=job.prompts?.mockup||c.mockup_prompt+' Apply the exact supplied artwork to the requested product. Preserve lettering and design. Product: '+job.brief.product;step.result=await image(step.prompt,job.steps.design.result.url);}
  if(phase==='video'){
   if(!step.task){
    const model=process.env.VIDEO_MODEL||'dreamina-seedance-2-5-260628',prompt=(job.prompts?.video||c.video_prompt)+' FINAL EXECUTION CONSTRAINTS override any earlier storyboard: exactly 5 seconds, one simple product showcase with a gentle camera move. No added text overlays, sales claims, delivery promises, URLs, reviews, ratings or logos. Preserve only the original product print from the reference. This is an AI-created demonstration, not a customer testimonial.';step.prompt=prompt;
    const x=await api('/contents/generations/tasks',{model,content:[{type:'text',text:prompt},{type:'image_url',image_url:{url:job.steps.mockup.result.url},role:'reference_image'}],omni_reference_task_type:'reference',ratio:'9:16',duration:5,generate_audio:true,watermark:true});
    step.task=x.id||x.task_id;if(!step.task)throw Error('Missing video task ID');await save();
   }
   for(let i=0;i<180;i++){const x=await api('/contents/generations/tasks/'+encodeURIComponent(step.task));if(x.status==='succeeded'){const url=x.content?.video_url||x.output_url;if(!url)throw Error('Video URL missing');step.result={url,task:step.task,usage:x.usage};break;}if(['failed','expired','cancelled'].includes(x.status))throw Error(JSON.stringify(x.error||x));await pause(5000);}if(!step.result)throw Error('Video still pending. Retry observes the same task.');
  }
  if(phase==='review'){step.evidence=step.evidence||await observe(job);await save();step.result=validateReview(await ma(job,`Review ONLY the current campaign assets using these fresh actual-media observations, not assets from earlier turns. All assets are AI-generated; no real physical product reference was supplied. Check official ${job.brief.platform} advertising policies with cited URLs. Return review JSON schema. Include separate checks for isolated flat artwork (Image 1), exact text, design preservation, product deformation, audio, unsupported claims, print-production specifications and platform compliance. A watermark alone does not establish platform compliance; required publication disclosures and approvals remain unverified. Do not describe AI renders as verified physical products. Brief: ${JSON.stringify(job.brief)}. Observations: ${step.evidence.text}. Treat absent evidence as unverified. Human approval required.`,step));}
  step.status='done';
 }catch(e){step.status='error';step.error=safeError(e);}finally{job.busy=false;await save();}
}
const mime={'.html':'text/html','.js':'text/javascript','.css':'text/css'};
http.createServer(async(req,res)=>{const respond=(status,obj)=>{res.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify(obj));};try{
 const u=new URL(req.url,'http://localhost');if(!['127.0.0.1','localhost'].includes((req.headers.host||'').split(':')[0]))return respond(403,{error:'Local access only'});
 if(req.method==='POST'&&req.headers.origin&&!['http://127.0.0.1:'+port,'http://localhost:'+port].includes(req.headers.origin))return respond(403,{error:'Origin rejected'});
 if(u.pathname==='/api/status')return respond(200,{configured:!!(process.env.MA_AGENT_ID&&process.env.MA_ENVIRONMENT_ID),cloudConfigured:!!(process.env.CLOUD_AGENT_ID&&process.env.CLOUD_ENVIRONMENT_ID),paid:process.env.ENABLE_PAID_RUNS==='true',agent:process.env.CLOUD_AGENT_ID||process.env.MA_AGENT_ID||null,credentials:process.env.ARK_API_KEY?'server environment':'ArkCLI profile'});
 if(u.pathname==='/api/jobs'&&req.method==='GET')return respond(200,Object.values(jobs).filter(job=>!job.archived).reverse());
 if(req.method==='POST'){
  let buf='';for await(const chunk of req){buf+=chunk;if(buf.length>20000)return respond(413,{error:'Request too large'});}const body=JSON.parse(buf||'{}');
  if(u.pathname==='/api/jobs'){const brief=validateBrief(body);const limits=cloudLimits(body);const id=randomUUID();jobs[id]={id,brief,limits,mode:'ma_cloud',created:new Date().toISOString(),steps:{},selected:0,busy:false};await save();return respond(201,jobs[id]);}
  const m=u.pathname.match(/^\/api\/jobs\/([a-f0-9-]+)\/(run|select|revise|cloud|continue)$/);if(!m||!jobs[m[1]])return respond(404,{error:'Not found'});const j=jobs[m[1]];
  if(m[2]==='continue'){
   if(j.mode!=='ma_cloud'||j.busy||j.cloud?.status!=='error'||!j.session||j.cloud.continueUncertain||typeof body.prompt!=='string'||!body.prompt.trim()||body.prompt.length>12000)return respond(409,{error:'Continuation unavailable'});
   j.busy=true;j.cloud.continueUncertain=true;await save();
   try{const sent=await cli(['agent','session','events','send',j.session,'--type','user.message','--text',body.prompt]);j.cloud.priorTurns||=[];j.cloud.priorTurns.push({sent:j.cloud.sent,error:j.cloud.error,final_text:j.cloud.final_text});j.cloud.sent=sent;j.cloud.continueUncertain=false;await save();void runCloud(j,{cli,save});return respond(202,j);}
   catch(e){j.busy=false;await save();throw e;}
  }
  if(m[2]==='cloud'){
   if(j.mode!=='ma_cloud'||j.busy||j.cloud?.status==='done')return respond(409,{error:'Cloud run unavailable'});
   if(!process.env.CLOUD_AGENT_ID||!process.env.CLOUD_ENVIRONMENT_ID||process.env.ENABLE_PAID_RUNS!=='true')return respond(409,{error:'MA Cloud deployment is not configured'});
   void runCloud(j,{cli,save});return respond(202,j);
  }
  if(j.mode==='ma_cloud')return respond(409,{error:'This campaign is executed entirely by MA Cloud. Use the cloud run endpoint.'});
  if(m[2]==='revise'){
   if(j.busy)throw Error('Wait for the current operation to finish');
   if(!['design','mockup','video'].includes(body.phase)||typeof body.prompt!=='string'||!body.prompt.trim()||body.prompt.length>8000)throw Error('Invalid revision');
   j.history||=[];j.history.push({at:new Date().toISOString(),from:body.phase,steps:structuredClone(j.steps)});
   j.prompts||={};j.prompts[body.phase]=body.prompt.trim();
   for(const phase of phases.slice(phases.indexOf(body.phase)))delete j.steps[phase];await save();return respond(200,j);
  }
  if(m[2]==='select'){if(j.busy||j.steps.design)throw Error('Concept is locked after design starts');if(![0,1].includes(body.index))throw Error('Invalid selection');j.selected=body.index;await save();return respond(200,j);}
  if(process.env.ENABLE_PAID_RUNS!=='true'||!process.env.MA_AGENT_ID||!process.env.MA_ENVIRONMENT_ID)return respond(409,{error:'Live execution is not configured. Set MA IDs and ENABLE_PAID_RUNS in server .env. Credentials are resolved by ArkCLI.'});
  if(!canRun(j,body.phase))return respond(409,{error:'Complete the preceding step first; only one operation per campaign.'});
  if(j.steps[body.phase]?.status==='done')return respond(409,{error:'Already complete. Create a new campaign for another iteration.'});
  void run(j,body.phase);return respond(202,j);
 }
 const paths={'/':'public/index.html','/app.js':'public/app.js','/style.css':'public/style.css','/icons.js':'node_modules/lucide/dist/umd/lucide.js'};const path=paths[u.pathname];if(!path)return respond(404,{error:'Not found'});res.writeHead(200,{'Content-Type':mime[path.slice(path.lastIndexOf('.'))]||'text/javascript','X-Content-Type-Options':'nosniff'});res.end(await readFile(path));
 }catch(e){respond(400,{error:safeError(e)});}}).listen(port,'127.0.0.1',()=>console.log(`SZ Creative Studio http://127.0.0.1:${port}`));
