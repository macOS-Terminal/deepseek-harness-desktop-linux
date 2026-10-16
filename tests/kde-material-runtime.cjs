const vm=require('node:vm');const assert=require('node:assert/strict');const fs=require('node:fs');
const source=fs.readFileSync(0,'utf8');
(async()=>{
 for(const mode of ['x11','auto','wayland','other-desktop','wrong-owner','missing-xprop','zero-handle']){
  const calls=[];const handle=Buffer.alloc(8);handle.writeBigUInt64LE(mode==='zero-handle'?0n:0x123n);
  const win={getNativeWindowHandle:()=>handle,isDestroyed:()=>false};
  const context={Buffer,console:{warn(){}},process:{platform:'linux',pid:1234,env:{XDG_CURRENT_DESKTOP:mode==='other-desktop'?'GNOME':'KDE',DISPLAY:':0',WAYLAND_DISPLAY:'wayland-0'}},
   app:{commandLine:{getSwitchValue:()=>mode==='wayland'?'wayland':mode==='auto'?'':'x11'}},
   execFile:(bin,args,options,cb)=>{
    assert.equal(bin,'xprop');assert.ok(options.timeout);calls.push(args);
    if(mode==='missing-xprop')return cb(new Error('ENOENT'));
    cb(null,args.includes('_NET_WM_PID')?`_NET_WM_PID(CARDINAL) = ${mode==='wrong-owner'?4321:1234}\n`:'');
   }};
  vm.createContext(context);vm.runInContext(source+'\nglobalThis.run=configureKdeBlur;',context);
  const [first,second]=await Promise.all([context.run(win),context.run(win)]);
  assert.equal(first,['x11','auto'].includes(mode),mode);assert.equal(second,first);
  assert.equal(calls.length,['x11','auto'].includes(mode)?2:['wrong-owner','missing-xprop'].includes(mode)?1:0,mode);
  if(first)assert.deepEqual(Array.from(calls[1]),['-id','0x123','-f','_KDE_NET_WM_BLUR_BEHIND_REGION','32c','-set','_KDE_NET_WM_BLUR_BEHIND_REGION','0']);
 }
})().catch(e=>{console.error(e);process.exitCode=1});
