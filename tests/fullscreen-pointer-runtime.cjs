const vm=require('node:vm'),assert=require('node:assert/strict'),fs=require('node:fs');
const source=JSON.parse(fs.readFileSync(0,'utf8'));
(async()=>{
 let fullscreen=false,maximized=true,platform='x11',cursorReads=0;
 const sender={mainFrame:{},getZoomFactor:()=>1.25};const event={sender,senderFrame:sender.mainFrame};
 const window={getContentBounds:()=>({x:3841,y:621}),isFocused:()=>true,isFullScreen:()=>fullscreen,isMaximized:()=>maximized,maximize:()=>maximized=true,unmaximize:()=>maximized=false};
 const ctx={window,process:{env:{XDG_SESSION_TYPE:'wayland'}},app:{commandLine:{getSwitchValue:()=>platform}},screen:{getCursorScreenPoint:()=>{cursorReads++;return {x:3966,y:646}}}};
 vm.createContext(ctx);vm.runInContext('globalThis.handle=(event,action)=>{'+source.main+'}',ctx);
 let result=ctx.handle(event,'pointer-state');assert.equal(result.x,100);assert.equal(result.y,20);assert.equal(result.domPointer,false);
 assert.equal(ctx.handle({...event,senderFrame:{}},'pointer-state'),false);
 platform='wayland';const reads=cursorReads;result=ctx.handle(event,'pointer-state');assert.equal(result.domPointer,true);assert.equal(result.x,undefined);assert.equal(cursorReads,reads);
 ctx.handle(event,'titlebar-double-click');assert.equal(maximized,false);ctx.handle(event,'titlebar-double-click');assert.equal(maximized,true);
 fullscreen=true;ctx.handle(event,'titlebar-double-click');assert.equal(maximized,true);
 const events={};const root={dataset:{},hasAttribute(name){return Object.hasOwn(this.dataset,name.replace(/^data-/,'').replace(/-([a-z])/g,(_,c)=>c.toUpperCase()))}};
 let state={fullscreen:true,maximized:false,focused:true,domPointer:true};let synced=0;
 const preload={document:{hasFocus:()=>state.focused,documentElement:root,body:null,querySelector:()=>null,addEventListener:(n,cb)=>events[n]=cb},window:{innerWidth:1920,addEventListener:(n,cb)=>events[n]=cb},electron:{ipcRenderer:{invoke:async()=>state}},CHANNEL:'test',syncTilingFullscreen(){synced++;if(root.dataset.dshWindowFullscreen==='true')root.dataset.fullscreen='true';else delete root.dataset.fullscreen;},setInterval:()=>1,clearInterval(){},setTimeout:()=>1,clearTimeout(){},MutationObserver:class{observe(){}}};
 vm.createContext(preload);vm.runInContext(source.preload+'\nglobalThis.poll=pollFullscreenPointer;',preload);
 await preload.poll();assert.equal(root.dataset.dshDomPointer,'');assert.equal(root.dataset.fullscreen,'true');assert.equal(synced,1);
 events.pointermove({clientX:1500,clientY:1});assert.equal(root.dataset.dshRevealControls,'');
 state={...state,focused:false};await preload.poll();assert.equal(root.dataset.dshRevealControls,undefined);
 // Exercise both Wayland DOM hover and XWayland's edge + native poll.
 for(const domPointer of [true,false]){
  state={...state,fullscreen:true,domPointer,x:1500,y:1};
  for(let i=0;i<20;i++){events.pointermove({clientX:1500,clientY:1});assert.equal(root.dataset.dshRevealControls,undefined);await preload.poll();assert.equal(root.dataset.dshRevealControls,undefined);}
 }
 state={...state,focused:true};await preload.poll();assert.equal(root.dataset.dshRevealControls,'');
 state={...state,focused:false,fullscreen:false,domPointer:false};await preload.poll();assert.equal(root.dataset.fullscreen,undefined);assert.equal(root.dataset.dshDomPointer,undefined);
})().catch(e=>{console.error(e);process.exit(1)});
