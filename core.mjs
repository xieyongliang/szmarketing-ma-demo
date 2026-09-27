export const phases=['research','design','mockup','video','review'];
export function jsonObject(text){
  const clean=text.trim().replace(/^```(?:json)?\s*/,'').replace(/\s*```$/,'');
  const value=JSON.parse(clean); if(!value||typeof value!=='object'||Array.isArray(value))throw Error('Expected JSON object from MA');return value;
}
export function validateBrief(b){
  if(!b||!['Mug','T-shirt'].includes(b.product)||!['TikTok','Facebook'].includes(b.platform))throw Error('Invalid product or platform');
  for(const k of ['name','audience','brief'])if(typeof b[k]!=='string'||!b[k].trim()||b[k].length>4000)throw Error('Missing or oversized '+k);
  return {name:b.name.trim(),product:b.product,platform:b.platform,audience:b.audience.trim(),brief:b.brief.trim()};
}
export function canRun(job,phase){const i=phases.indexOf(phase);return i>=0&&!job.busy&&(i===0||job.steps[phases[i-1]]?.status==='done');}
export function validatePlan(p){if(!Array.isArray(p.concepts)||p.concepts.length!==2)throw Error('MA must return two concepts');for(const c of p.concepts)for(const k of ['title','print_prompt','mockup_prompt','video_prompt'])if(typeof c[k]!=='string'||!c[k].trim())throw Error('Missing concept '+k);return {...p,research:(p.research||[]).map(r=>({...r,model_confidence:r.confidence,confidence:'Source-reported / not independently verified'}))};}
export function validateReview(r){if(!Number.isFinite(r.score)||r.score<0||r.score>5||!Array.isArray(r.checks)||r.checks.some(c=>!['pass','fail','unverified'].includes(c.status)))throw Error('Invalid MA review');return {...r,verdict:(r.quality_gate?r.quality_gate==='blocked':r.checks.some(c=>c.status==='fail'))?'revise':'review_required'};}
export function turnResult(events,messageId){
  const start=events.findIndex(e=>e.id===messageId);if(start<0)return null;
  let text=null;
  for(const e of events.slice(start+1)){
    if(e.type==='user.interrupt')throw Error('Cloud turn was interrupted; no successful completion');
    if(e.type==='user.message')throw Error('Another message interrupted the expected turn');
    if(e.type==='session.error')throw Error(JSON.stringify(e.error||e));
    if(e.type==='agent.message')text=(e.content||[]).filter(c=>c.type==='text').map(c=>c.text).join('');
    if(e.type==='session.status_idle'&&text)return text;
    if(/requires_action|terminated/.test(e.type))throw Error('MA needs attention: '+e.type);
  }return null;
}
