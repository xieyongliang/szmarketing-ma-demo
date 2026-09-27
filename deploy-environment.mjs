// Inject a user-approved demo key without logging it or putting it in argv.
import {mkdtemp,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
if(!process.env.ARK_API_KEY)throw Error('Provide ARK_API_KEY through the process environment');
const dir=await mkdtemp(join(tmpdir(),'sz-cloud-env-'));
try{
 const path=join(dir,'config.json');
 await writeFile(path,JSON.stringify({Type:'cloud',Networking:{Type:'unrestricted'},Env:{ARK_API_KEY:process.env.ARK_API_KEY}}),{mode:0o600});
 const call=promisify(execFile)('arkcli',['agent','env','create','--name','arkcli-sz-autonomous-demo-20260925','--config','@'+path,'--format','json'],{timeout:90000,maxBuffer:2000000,env:{...process.env,ARKCLI_NO_UPDATE_NOTIFIER:'1',ARKCLI_CALLER_TYPE:'ai_agent',ARKCLI_CALLER_NAME:'codex',ARKCLI_SKILL_NAME:'arkcli-agent'}});
 call.child.stdin.end();
 const {stdout}=await call;const result=JSON.parse(stdout);const id=result.Result?.Id||result.id;
 if(!id)throw Error('Environment not confirmed; inspect account before retrying');
 console.log(JSON.stringify({environment_id:id,credential:'injected; value withheld'}));
}catch{console.error('Environment creation not confirmed; response withheld to protect credentials. Inspect account before retrying.');process.exitCode=1;}
finally{await rm(dir,{recursive:true,force:true});}
