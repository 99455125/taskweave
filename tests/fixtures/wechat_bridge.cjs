// Real Node protocol boundary double; never a simulator acceptance substitute.
const readline=require('readline');
const mode=process.env.TW_WECHAT_PROTOCOL_MODE||'';
let revision=1;
readline.createInterface({input:process.stdin}).on('line',line=>{
  const req=JSON.parse(line);
  if(mode==='exit')process.exit(7);
  if(mode==='missing')return;
  if(mode==='malformed'){process.stdout.write('not-json\n');return;}
  if(mode==='oversize'){process.stdout.write('x'.repeat(1048577)+'\n');return;}
  if(req.method==='navigate')revision++;
  const result={session_id:'fixture-session',page_path:'pages/main/main',page_revision:revision,result:{method:req.method,params:req.params}};
  const reply=JSON.stringify({id:mode==='wrong-id'?'foreign':req.id,result})+'\n';
  process.stdout.write(reply);
  if(mode==='duplicate')setTimeout(()=>process.stdout.write(reply),20);
  if(mode==='stderr')process.stderr.write('fixture-secret'.repeat(20000));
});
