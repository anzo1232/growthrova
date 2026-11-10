/** Clippr Business risk evidence gate: deliberately no network or paid actions.
 *
 * Development must maintain mapped commits, evidence paths, and an explicit
 * blocked-release status. Staging/production cannot pass on local unit tests.
 */
import {readFileSync,existsSync} from "node:fs";
import {execFileSync} from "node:child_process";
import {fileURLToPath} from "node:url";
import {dirname,join,resolve} from "node:path";

export const ROOT=resolve(dirname(fileURLToPath(import.meta.url)),"..");
export const MANIFEST=join(ROOT,"docs/business-risk-evidence.json");
const VALID_STATUS=new Set(["release-blocker","code-mitigated","staging-db-verified",
  "staging-api-verified","production-verified"]);
const STAGING_REQUIRED=["AUTH","TENANT","R2","CAMPAIGNS","JOBS"];
function git(args){
  return execFileSync("git",args,{cwd:ROOT,encoding:"utf8",timeout:10000}).trim();
}
export function evaluate(doc,{phase="dev",exists=existsSync,currentHistory=null,
  nextCommits=null}={}){
  const errors=[],warnings=[];
  if(!["dev","staging","production"].includes(phase))errors.push("Unknown release phase.");
  const ids=new Set(),mapped=new Set();
  if(!Array.isArray(doc.risk_definitions)||doc.risk_definitions.length<12)
    errors.push("Risk register is incomplete.");
  for(const risk of doc.risk_definitions||[]){
    if(!risk.id||ids.has(risk.id))errors.push("Duplicate or missing risk ID.");
    ids.add(risk.id);
    if(!["critical","high","medium","low"].includes(risk.severity))
      errors.push("Invalid severity for "+risk.id);
    if(!VALID_STATUS.has(risk.status))errors.push("Invalid status for "+risk.id);
    if(!risk.owner||!Array.isArray(risk.unmet)||!risk.unmet.length)
      errors.push("Missing risk owner/exit condition for "+risk.id);
    if(!Array.isArray(risk.evidence)||!risk.evidence.length)
      errors.push("Missing test evidence for "+risk.id);
    for(const file of risk.evidence||[]){
      if(typeof file!=="string"||file.includes("..")||!exists(join(ROOT,file)))
        errors.push("Evidence not found: "+risk.id+" / "+file);
    }
    // A changed status label cannot become evidence. Real staging API and
    // production verification require a specific dated artefact plus reviewer.
    const needsApi=["staging-api-verified","production-verified"].includes(risk.status);
    const proof=risk.attestations?.staging_api;
    if(needsApi && (!proof?.verified_at||!proof?.reviewer||!proof?.project_ref||
                    !proof?.evidence_file||!exists(join(ROOT,proof.evidence_file))))
      errors.push("Missing real staging API attestation for "+risk.id);
    if(risk.status==="production-verified"){
      const prod=risk.attestations?.production;
      if(!prod?.verified_at||!prod?.reviewer||!prod?.release_sha||
         !prod?.evidence_file||!exists(join(ROOT,prod.evidence_file)))
        errors.push("Missing production sign-off evidence for "+risk.id);
    }
  }
  for(const commit of doc.retrospective_commits||[]){
    if(!/^[0-9a-f]{7,40}$/.test(commit.sha)||mapped.has(commit.sha))
      errors.push("Duplicate or malformed audited commit.");
    mapped.add(commit.sha);
    if(!commit.risk_ids?.length)
      errors.push("Audited commit has no mapped risks: "+commit.sha);
    for(const id of commit.risk_ids||[]){
      if(!ids.has(id))errors.push("Unknown risk "+id+" on "+commit.sha);
    }
  }
  if(currentHistory){
    for(const sha of currentHistory){
      if(!mapped.has(sha))errors.push("Unreviewed retrospective commit: "+sha);
    }
    for(const sha of mapped){
      if(!currentHistory.includes(sha))errors.push("Stale retrospective commit: "+sha);
    }
  }
  const exceptions=new Map();
  for(const exception of doc.trailer_exceptions||[]){
    if(!/^[0-9a-f]{40}$/.test(exception.sha)||exceptions.has(exception.sha))
      errors.push("Malformed or duplicate trailer exception.");
    if(!exception.reviewed_at||!exception.reason||!exception.risk_ids?.length)
      errors.push("Trailer exception lacks dated review or risk mapping: "+exception.sha);
    for(const id of exception.risk_ids||[]){
      if(!ids.has(id))errors.push("Unknown exception risk "+id);
    }
    exceptions.set(exception.sha,exception);
  }
  for(const exception of nextCommits===null?[]:exceptions.values()){
    if(!nextCommits.some(c=>c.full_sha===exception.sha))
      errors.push("Stale trailer exception: "+exception.sha);
  }
  for(const commit of nextCommits||[]){
    const match=commit.message.match(/^Risk-ID:\s*([A-Z0-9,\s]+)$/m);
    if(!match){
      if(exceptions.has(commit.full_sha))continue;
      errors.push("New commit "+commit.sha+" is missing Risk-ID trailer.");continue;
    }
    for(const id of match[1].split(",").map(x=>x.trim()).filter(Boolean)){
      if(!ids.has(id))errors.push("Commit "+commit.sha+" cites unknown risk "+id);
    }
  }
  for(const id of doc.release_required||[]){
    if(!ids.has(id))errors.push("Missing required release risk: "+id);
  }
  const risks=doc.risk_definitions||[];
  if(phase==="staging"||phase==="production"){
    for(const id of STAGING_REQUIRED){
      const record=risks.find(r=>r.id===id);
      if(!["staging-api-verified","production-verified"].includes(record?.status))
        errors.push("Real staging API exit test outstanding: "+id);
    }
  }
  if(phase==="production"){
    if(doc.release_approved!==true)errors.push("Production release has no explicit approval.");
    for(const item of risks.filter(r=>r.severity==="critical")){
      if(item.status!=="production-verified")
        errors.push("Critical risk not production-verified: "+item.id);
    }
  }
  if(phase==="dev" && doc.release_approved===false)
    warnings.push("Business release remains explicitly BLOCKED, as intended.");
  return {ok:errors.length===0,phase,errors,warnings,
          risks:risks.length,mapped_commits:mapped.size};
}
export function loadCurrent(){
  const doc=JSON.parse(readFileSync(MANIFEST,"utf8"));
  const list=git(["log","-14","--format=%h",doc.reviewed_through]).split("\n");
  const shas=git(["rev-list","--reverse",doc.reviewed_through+"..HEAD"]).split("\n")
    .filter(Boolean);
  const future=shas.map(sha=>({sha:sha.slice(0,7),full_sha:sha,message:git(["show","-s","--format=%B",sha])}));
  return {doc,history:list,future};
}
if(process.argv[1] && resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  const phase=(process.argv.find(x=>x.startsWith("--phase="))||"--phase=dev").slice(8);
  try{
    const {doc,history,future}=loadCurrent();
    const result=evaluate(doc,{phase,currentHistory:history,nextCommits:future});
    process.stdout.write(JSON.stringify(result,null,2)+"\n");
    if(!result.ok)process.exitCode=1;
  }catch(error){
    process.stderr.write("Business risk gate configuration failed: "+error.message+"\n");
    process.exitCode=1;
  }
}
