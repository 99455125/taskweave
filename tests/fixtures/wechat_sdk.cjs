// In-memory SDK contract double; official runtime acceptance is separate.
const {EventEmitter}=require('events');
const values=new Map([['outside','preserve']]);
class Element{
 constructor(selector,page){this.selector=selector;this.page=page;this.tagName=selector==='#input'?'input':'view';}
 async text(){return this.selector==='#secret'?'x'.repeat(4080)+process.env.TW_WECHAT_SECRET:this.page.state.marker;} async value(){return this.page.state.input;}
 async attribute(name){return name==='id'?this.selector.slice(1):'';}
 async property(name){return this.page.state[name]||0;}
 async tap(){if(process.env.TW_WECHAT_BREAK_PROTOCOL==='1'){process.stdout.write('not-json\n');await new Promise(resolve=>setTimeout(resolve,1000));}if(process.env.TW_WECHAT_STALL==='1')await new Promise(resolve=>setTimeout(resolve,1000));this.page.state.count++;} async input(value){this.page.state.input=value;}
 async scrollTo(x,y){this.page.state.scroll=[x,y];}
 async touchstart(){this.page.state.touch='start';}async touchmove(){this.page.state.touch='move';}async touchend(){this.page.state.touch='end';}
 async callMethod(method,...args){if(method!=='increment')throw Error('unsupported');this.page.state.count+=(args[0]||1);return this.page.state.count;}
}
class Page{
 constructor(path){this.path=path;this.query={};this.state={marker:'owned-fixture',input:'',count:0};}
 async $(selector){return selector==='#missing'?null:new Element(selector,this);}
 async data(path){if(process.env.TW_WECHAT_READ_STALL==='1')await new Promise(resolve=>setTimeout(resolve,200));return this.state[path];}
}
class Mini extends EventEmitter{
 constructor(){super();this.page=new Page('pages/main/main');this.mocks=new Set();this.readyDelay=Number(process.env.TW_WECHAT_READY_DELAY||0);}
 async currentPage(){if(this.readyDelay-->0)throw Error("Cannot destructure property 'rawPath' of 't.getPageMetaByWebviewId(...)' as it is null.");return this.page;}async pageStack(){return [this.page];}
 async navigateTo(url){this.page=new Page(url.replace(/^\//,'').split('?')[0]);return this.page;}
 async redirectTo(url){return this.navigateTo(url);}async reLaunch(url){return this.navigateTo(url);}async switchTab(url){return this.navigateTo(url);}
 async navigateBack(){return this.navigateTo('/pages/main/main');}
 async pageScrollTo(y){this.page.state.scrollTop=y;}
 async callWxMethod(method,...args){
  if(method==='getAccountInfoSync')return {miniProgram:{appId:'touristappid'}};
  if(method==='getStorageInfoSync')return {keys:[...values.keys()]};
  if(method==='getStorageSync')return values.get(args[0])||'';
  if(method==='setStorageSync'){values.set(args[0],args[1]);return;}
  if(method==='removeStorageSync'){values.delete(args[0]);return;}
  if(method==='clearStorageSync'){values.clear();return;}
  throw Error('unexpected wx method');
 }
 async mockWxMethod(method,value){this.mocks.add(method);this.emit('console',process.env.TW_WECHAT_SECRET?'x'.repeat(4080)+JSON.stringify(JSON.stringify(process.env.TW_WECHAT_SECRET)): {message:'mock installed',method});}
 async restoreWxMethod(method){if(process.env.TW_WECHAT_RESTORE_FAIL==='1')throw Error('restore failed');this.mocks.delete(method);}
 async screenshot(){return 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=';}
 disconnect(){this.disconnected=true;}async close(){this.windowClosed=true;this.disconnect();}
}
exports.connect=async()=>new Mini();
