'use strict';
// The private key only arrives over stdin. SDK chatter cannot forge our receipt.
const fs = require('fs');
const path = require('path');
const write = process.stdout.write.bind(process.stdout);
console.log = console.info = console.debug = (...args) => console.error(...args);
(async () => {
  const chunks = []; let length = 0;
  for await (const chunk of process.stdin) {
    length += chunk.length;
    if (length > 131072) throw Error('INPUT_TOO_LARGE');
    chunks.push(chunk);
  }
  const request = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  const sdkRoot = path.join(request.module_root, 'node_modules', 'miniprogram-ci');
  if (require(path.join(sdkRoot, 'package.json')).version !== '2.1.48') throw Error('SDK_VERSION');
  const ci = require(sdkRoot);
  const project = new ci.Project({appid:request.appid,type:'miniProgram',projectPath:request.project_path,
    privateKey:request.private_key,ignores:['node_modules/**/*']});
  const options = request.options;
  const params = {project,desc:options.desc || '',robot:options.robot || 1,
    setting:{useProjectConfig:true},onProgressUpdate:()=>{}};
  let result;
  if (request.action === 'preview') {
    Object.assign(params,{qrcodeFormat:'image',qrcodeOutputDest:request.qrcode_path});
    for (const [key, target] of [['page_path','pagePath'],['search_query','searchQuery'],['scene','scene']]) {
      if (options[key] !== undefined) params[target] = options[key];
    }
    result = await ci.preview(params);
  } else if (request.action === 'upload') {
    params.version = options.version;
    result = await ci.upload(params);
  } else throw Error('ACTION_INVALID');
  if (!result || !Array.isArray(result.subPackageInfo) || !Array.isArray(result.pluginInfo)) throw Error('RECEIPT_INVALID');
  if(result.subPackageInfo.length>500 || result.pluginInfo.length>500) throw Error('RECEIPT_TOO_LARGE');
  const receipt = {sub_packages:result.subPackageInfo.map(({name,size})=>({name,size})),
    plugins:result.pluginInfo.map(({pluginProviderAppid,version})=>({pluginProviderAppid,version}))};
  write('TASKWEAVE_CI:'+JSON.stringify(receipt)+'\n');
})().catch(() => {console.error('WECHAT_CI_FAILED');process.exitCode=1;});
