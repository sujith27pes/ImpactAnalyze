'use strict';
// Pure presentation helpers: never alter evidence, gate, or execution status.
const ImpactExperience={
  escape(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));},
  source(id,report){return report?.graph?.evidence?.[id]||report?.counterfactual?.evidence?.[id];},
  fileLabel(path){return path.split('/').pop()==='.impact-contracts.json'?'Connection declaration':path.split('/').pop();},
  citations(ids,report){
    const buttons=[...new Set(ids||[])].map(id=>{
      const source=this.source(id,report);if(!source)return '';
      const lines=source.start===source.end?`line ${source.start}`:`lines ${source.start}–${source.end}`;
      const title=`View ${source.repository||'repository'} / ${source.path}, ${lines}`;
      return `<button class="cite" data-cite="${this.escape(id)}" aria-label="${this.escape(title)}" title="${this.escape(title)}"><strong>${this.escape(this.fileLabel(source.path))} · ${lines}</strong><small>${this.escape(source.repository||'Captured source')}</small></button>`;
    }).join('');
    return buttons?`<div class="source-links"><span class="source-label">View supporting source</span><div class="source-buttons">${buttons}</div></div>`:'';
  },
  relationship(resolution,kind){
    return ({PARSER_RESOLVED:'Found in source code',STATIC_RULE:'Found by a source rule',DECLARED:'Declared by the project owner',DECLARED_MATCH:'Matching owner declarations',COARSE_FILE_SCOPE:'Shared file: review needed',COARSE_BUILD_SCOPE:'Shared build: review needed'})[resolution]||({HTTP_TEST_REFERENCE:'Test references this endpoint',HTTP_ROUTE:'HTTP endpoint connection'})[kind]||'Source relationship: review needed';
  },
  job(state){return ({QUEUED:'Waiting to start',RUNNING:'Reading source and analyzing the change',WAITING_PROVIDER:'Waiting for AI service capacity',COMPLETED:'Source analysis finished',FAILED:'Analysis could not finish',CANCELLED:'Analysis cancelled'})[state]||'Checking analysis progress';},
  ai(ai){
    const base={label:'AI advice unavailable',title:'We could not use an AI response',description:'The source analysis is still available. No AI advice has been accepted for this report.',next:'Continue reviewing the source results. You can run a new analysis to try AI again.',tone:'attention'};
    if(ai.analysis&&ai.status==='GROUNDED_DRAFT')return {...base,label:'AI suggestions ready',title:'AI suggestions for your review',description:'These suggestions use the displayed source references. Confirm their interpretation before using them.',tone:'ready'};
    if(ai.status==='NOT_CONFIGURED')return {...base,label:'AI not connected',title:'Source analysis is ready; AI is not connected',description:'You can review affected systems, source references and suggested existing tests now.',next:'Ask the application maintainer to connect the AI service, or continue with the source results.'};
    if(ai.status==='PROVIDER_UNAVAILABLE'){
      const meanings={401:['AI key was rejected','Ask the application maintainer to check the NVIDIA API key.'],403:['AI access was refused','Ask the application maintainer to check model access for the NVIDIA account.'],402:['AI account allowance unavailable','Check the NVIDIA account allowance before trying again.'],429:['AI request limit reached','Wait for the cooldown shown in AI status, then run a new analysis.'],503:['AI service is temporarily unavailable','Wait for the cooldown shown in AI status, then run a new analysis.']};
      const meaning=meanings[ai.http_status]||['AI service could not complete the request','Continue with the source results. Check AI status before trying again.'];
      return {...base,title:meaning[0],next:meaning[1]};
    }
    if(ai.status==='PROVIDER_PENDING')return {...base,label:'AI response still pending',title:'The AI service has not finished this request',next:'Use the source report now. Ask the application maintainer to check the pending request; it is not resubmitted automatically.'};
    if(['BUDGET_EXCEEDED','INSUFFICIENT_EVIDENCE'].includes(ai.status))return {...base,title:ai.status==='BUDGET_EXCEEDED'?'This request exceeds the configured AI allowance':'Not enough cited source fits the AI request',next:'Narrow the change and confirm the selected project. The source report can still be reviewed.'};
    const reason=ai.failure_reason||({ReadTimeout:'TIMEOUT',ConnectTimeout:'TIMEOUT',ValidationError:'INVALID_FORMAT'})[ai.error_type];
    if(reason==='TIMEOUT')return {...base,title:'The AI service took too long to respond',next:'Review the source results now. After the cooldown, run a new analysis to try again.'};
    if(reason==='TRANSPORT_ERROR')return {...base,title:'We could not reach the AI service',next:'Check connectivity and AI status. Your source report is available.'};
    if(reason==='TRUNCATED_OUTPUT')return {...base,title:'The AI reply ended before it was complete',next:'Use a smaller request, or ask the maintainer to review the response allowance.'};
    if(reason==='INVALID_CITATIONS')return {...base,title:'The AI reply included source references we could not verify',next:'That AI reply was withheld. Continue with the verified source results and review any unresolved relationships.'};
    if(['INVALID_FORMAT','INVALID_RESPONSE'].includes(reason))return {...base,title:'The AI reply did not pass the response checks',next:'That AI reply was withheld. Continue with the source results, or run a new analysis after the cooldown.'};
    return base;
  }
};
if(typeof module!=='undefined'&&module.exports)module.exports=ImpactExperience;
