import test from 'node:test';
import assert from 'node:assert/strict';
import {runImagegenQueue} from './orchestrate_imagegen.mjs';

function options(entry, command, onReviewReady) {
  return {initialPlan:{dispatch:[entry],scheduler:{effective_concurrency:1}},
    command, onReviewReady, readInput:async()=>({prompt:'bound prompt'}),
    imagegen:async()=>({path:'/tmp/synthetic.png'}),selectArtifact:async r=>r.path};
}

test('local composition waits for base review; legacy keeps final stage',async()=>{
  for (const stage of ['composition','final']) {
    const calls=[], notices=[];
    const entry={id:'sample',action:'compose',...(stage==='composition'?{review_stage:stage}:{})};
    await runImagegenQueue(options(entry,async args=>{
      calls.push(args);
      return args[0]==='status'?{dispatch:[]}:{packets:[{job:'sample'}],errors:[]};
    },value=>notices.push(value)));
    assert.deepEqual(calls[0],['review-prepare','--job','sample','--stage',stage]);
    assert.equal(notices.length,1);
    assert.equal(notices[0].stage,stage);
  }
});

test('local composition preparation errors do not announce a review',async()=>{
  let notices=0;
  const result=await runImagegenQueue(options({id:'sample',action:'compose',review_stage:'composition'},
    async args=>args[0]==='status'?{dispatch:[]}:{errors:[{error:'SOURCE_BLOCKED'}]},()=>notices++));
  assert.equal(notices,0);
  assert.ok(result.errors.some(item=>item.error.includes('SOURCE_BLOCKED')));
});

test('model ingestion callback preserves the composition stage',async()=>{
  const notices=[];
  await runImagegenQueue(options({id:'sample',action:'image_gen',prompt_hash:'bound',review_stage:'composition'},
    async args=>{
      if(args[0]==='transition') return {status:'generating',attempt_id:'a',prompt_hash:'bound'};
      if(args[0]==='ingest') return {status:'generated',dispatch:[],scheduler:{effective_concurrency:1}};
      return {};
    },value=>notices.push(value)));
  assert.equal(notices[0].stage,'composition');
});
