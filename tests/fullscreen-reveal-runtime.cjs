const vm=require('node:vm'),assert=require('node:assert/strict'),fs=require('node:fs');
const source=fs.readFileSync(0,'utf8');const events={},timers=new Map();let next=0;const nodes=new Map();
const root={dataset:{fullscreen:'true'},hasAttribute(name){return Object.hasOwn(this.dataset,name.replace(/^data-/,'').replace(/-([a-z])/g,(_,c)=>c.toUpperCase()))}};
let toolbarHeight=48,focused=true;
const frame={getBoundingClientRect:()=>({left:0,top:0})};
const context={setInterval:()=>1,clearInterval(){},getComputedStyle:()=>({left:'0px',top:'0px',width:'1920px',height:toolbarHeight+'px'}),document:{hasFocus:()=>focused,documentElement:root,querySelector:s=>s.includes("_frame")?frame:null,body:{appendChild(node){nodes.set(node.id,node)}},getElementById:id=>nodes.get(id)??null,createElement:()=>({setAttribute(){},addEventListener(){}}),addEventListener:(n,cb)=>events[n]=cb},window:{innerWidth:1920,addEventListener:(n,cb)=>events[n]=cb},MutationObserver:class{constructor(cb){this.cb=cb}observe(){}},setTimeout:fn=>{timers.set(++next,fn);return next},clearTimeout:id=>timers.delete(id)};
vm.createContext(context);vm.runInContext(source+'\nglobalThis.sync=syncFullscreenReveal;',context);
context.sync();assert.equal(nodes.size,1);context.sync();assert.equal(nodes.size,1);
const move=y=>events.pointermove({pointerType:'mouse',clientX:30,clientY:y});
move(60);assert.equal(root.hasAttribute('data-dsh-reveal-controls'),false);
move(25);assert.equal(root.hasAttribute('data-dsh-reveal-controls'),false);
move(1);assert.equal(root.hasAttribute('data-dsh-reveal-controls'),true);
move(25);assert.equal(timers.size,0);
move(90);assert.equal(timers.size,1);move(20);assert.equal(timers.size,0);
move(90);for(const [id,fn] of [...timers]){timers.delete(id);fn();}assert.equal(root.hasAttribute('data-dsh-reveal-controls'),false);
move(1);events.blur();assert.equal(root.hasAttribute('data-dsh-reveal-controls'),false);
move(1);delete root.dataset.fullscreen;context.sync();assert.equal(root.hasAttribute('data-dsh-reveal-controls'),false);
move(1);assert.equal(root.hasAttribute('data-dsh-reveal-controls'),false);
root.dataset.fullscreen='true';events.pointermove({pointerType:'touch',clientX:30,clientY:1});assert.equal(root.hasAttribute('data-dsh-reveal-controls'),false);

// Sandboxed preload can run before document.documentElement exists.
const earlyEvents={};let observed=null;
const early={...context,document:{...context.document,documentElement:null,addEventListener:(n,cb)=>earlyEvents[n]=cb},window:{addEventListener(){}},MutationObserver:class{observe(node){assert.ok(node);observed=node}}};
vm.createContext(early);vm.runInContext(source,early);assert.equal(observed,null);
early.document.documentElement=root;earlyEvents.DOMContentLoaded();assert.equal(observed,root);

for(const x of [500,1919]) {
 events.blur();events.pointermove({pointerType:'mouse',clientX:x,clientY:25});assert.equal(root.hasAttribute('data-dsh-reveal-controls'),false);
 events.pointermove({pointerType:'mouse',clientX:x,clientY:1});assert.equal(root.hasAttribute('data-dsh-reveal-controls'),true);
 events.pointermove({pointerType:'mouse',clientX:x,clientY:25});assert.equal(timers.size,0);
}


move(25);assert.equal(root.hasAttribute('data-dsh-reveal-controls'),true);
events.blur();move(-1);assert.equal(root.hasAttribute('data-dsh-reveal-controls'),false);

// Follow the rendered strip rather than a fixed 48px boundary.
events.pointermove({pointerType:'mouse',clientX:500,clientY:1});
toolbarHeight=64;events.pointermove({pointerType:'mouse',clientX:500,clientY:60});assert.equal(timers.size,0);
events.pointermove({pointerType:'mouse',clientX:500,clientY:64});assert.equal(timers.size,1);
for(const [id,fn] of [...timers]){timers.delete(id);fn();}assert.equal(root.hasAttribute('data-dsh-reveal-controls'),false);

// Background-window hover must not fight the host's focus-based hide policy.
focused=false;
for(let i=0;i<20;i++){move(1);move(25);assert.equal(root.hasAttribute('data-dsh-reveal-controls'),false);assert.equal(timers.size,0);}
focused=true;move(1);assert.equal(root.hasAttribute('data-dsh-reveal-controls'),true);
focused=false;move(25);assert.equal(root.hasAttribute('data-dsh-reveal-controls'),false);
