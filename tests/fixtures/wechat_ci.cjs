const fs=require('fs');
exports.Project=class {constructor(p){if(p.privateKey!=='fixture-private-key')throw Error('wrong key');this.p=p;}};
async function perform(p,kind){
 if(!p.setting.useProjectConfig||p.robot!==1)throw Error('incorrect options');
 if(p.desc==='fail')throw Error(p.project.p.privateKey);
 if(p.desc==='hang')await new Promise(()=>{setInterval(()=>{},1000);});
 if(p.desc==='malformed')return {subPackageInfo:'bad'};
 if(kind==='preview'){
  if(p.pagePath!=='pages/index/index'||p.searchQuery!=='a=1&b=2'||p.scene!==1011)throw Error('wrong preview options');
  if(p.desc!=='missing')fs.writeFileSync(p.qrcodeOutputDest, Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=','base64'));
 }else if(p.version!=='1.2.3')throw Error('wrong upload version');
 console.log('SDK chatter '+p.project.p.privateKey);
 return {subPackageInfo:[{name:'__FULL__',size:42}],pluginInfo:[]};
}
exports.preview=p=>perform(p,'preview');exports.upload=p=>perform(p,'upload');