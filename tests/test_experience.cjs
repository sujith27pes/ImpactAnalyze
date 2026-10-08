'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const view=require('../studio/static/experience.js');

test('readable source buttons keep the exact evidence pointer and withhold missing references',()=>{
  const report={graph:{evidence:{'E-internal':{path:'src/app.py',repository:'Payments API',start:10,end:14}}}};
  const html=view.citations(['E-internal','E-internal','E-missing'],report);
  assert.match(html,/app\.py · lines 10–14/);
  assert.match(html,/Payments API/);
  assert.match(html,/data-cite="E-internal"/);
  assert.equal((html.match(/<button /g)||[]).length,1);
  const visible=html.replace(/<[^>]*>/g,'');
  assert.doesNotMatch(visible,/E-internal|E-missing/);
  assert.equal(view.citations(['E-missing'],report),'');
});

test('proposed-version sources work and untrusted source metadata is escaped',()=>{
  const source={path:'src/<img onerror=x>.py',repository:'<script>alert(1)</script>',start:2,end:2};
  const report={counterfactual:{evidence:{'E-"injected':source}}};
  assert.equal(view.source('E-"injected',report),source);
  const html=view.citations(['E-"injected'],report);
  assert.match(html,/line 2/);
  assert.match(html,/&lt;script&gt;/);
  assert.match(html,/data-cite="E-&quot;injected"/);
  assert.doesNotMatch(html,/<img|<script/);
});

test('AI failure guidance describes the reported cause without implying source analysis failed',()=>{
  const unavailable=view.ai({status:'PROVIDER_UNAVAILABLE',http_status:503});
  assert.match(unavailable.title,/temporarily unavailable/);
  assert.match(unavailable.description,/source analysis is still available/);
  assert.match(unavailable.next,/cooldown/);
  assert.match(view.ai({status:'PROVIDER_UNAVAILABLE',http_status:401}).next,/API key/);
  assert.match(view.ai({status:'REJECTED_OR_FAILED',failure_reason:'INVALID_CITATIONS'}).title,/could not verify/);
  assert.match(view.ai({status:'REJECTED_OR_FAILED',failure_reason:'TRUNCATED_OUTPUT'}).title,/complete/);
  assert.match(view.ai({status:'REJECTED_OR_FAILED',error_type:'ReadTimeout'}).title,/too long/);
  const legacy=view.ai({status:'REJECTED_OR_FAILED',error_type:'ValueError'});
  assert.doesNotMatch(legacy.title,/timeout|key|citation/i);
});

test('only a validated AI draft is presented as ready',()=>{
  assert.equal(view.ai({status:'GROUNDED_DRAFT',analysis:{summary:'Draft'}}).tone,'ready');
  assert.equal(view.ai({status:'REJECTED_OR_FAILED',analysis:{summary:'Unaccepted'}}).tone,'attention');
  assert.equal(view.ai({status:'GROUNDED_DRAFT'}).tone,'attention');
  assert.match(view.ai({status:'PROVIDER_PENDING'}).next,/not resubmitted automatically/);
  assert.doesNotMatch(view.job('COMPLETED'),/tests passed/i);
});
