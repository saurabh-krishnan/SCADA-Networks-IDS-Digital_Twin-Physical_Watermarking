/* Premium deck generator for the SCADA Digital-Twin Security project.
   Design direction: "cinematic control-room editorial" -- near-black canvas,
   one hot orange accent, a cool steel-blue for data, generous negative space,
   Cambria display serif + Arial, custom diagrams and framed live screenshots.
   Run from the deck/ directory so assets/ resolves.  Animations/transitions are
   added afterwards by animate.py (this script only lays out editable content). */
const pptxgen = require("pptxgenjs");

// ---------- palette ----------
const BG0="0A0C10", BG1="11141C", BG2="171B26", PANEL="141824";
const INK="F4F6FA", MUT="9AA3B4", FAINT="59627A", LINE="242B3A";
const ACC="F0592A", ACC2="54B2C9", GRN="35C76A", RED="FF5A52", AMB="F5A623", VIO="A98BFF";
const HEAD="Cambria", BODY="Arial", MONO="Consolas";

const pres = new pptxgen();
pres.defineLayout({ name:"W", width:13.333, height:7.5 });
pres.layout = "W";
pres.theme = { headFontFace: HEAD, bodyFontFace: BODY };
pres.author = "S. Saurabh Krishnan; Hemant Bhupesh; Sanjai S; Nitesh V. M.";
pres.title = "SCADA Digital-Twin Security";

const A = (o)=>Object.assign({isTextBox:true, margin:0}, o);   // text helper
let SN = 0; const TOTAL = 19;
function slide(dark=true){ const s=pres.addSlide(); s.background={color: dark?BG0:BG0}; SN++; return s; }
function shadow(){ return {type:"outer", color:"000000", opacity:0.55, blur:14, offset:5, angle:90}; }

// recurring top frame: left wordmark, right index
function topframe(s, section){
  s.addText([{text:"SCADA", options:{color:ACC,bold:true}},{text:"  /  DIGITAL-TWIN SECURITY", options:{color:FAINT}}],
    A({x:0.6,y:0.42,w:7,h:0.3,fontSize:9,fontFace:MONO,charSpacing:2,align:"left"}));
  s.addText(`${String(SN).padStart(2,"0")} / ${TOTAL}`,
    A({x:11.1,y:0.42,w:1.63,h:0.3,fontSize:9,color:FAINT,fontFace:MONO,align:"right",charSpacing:2}));
  if(section) s.addText(section.toUpperCase(),
    A({x:0.6,y:6.82,w:8,h:0.3,fontSize:8.5,color:FAINT,fontFace:MONO,align:"left",charSpacing:3}));
}
function kicker(s,t,x=0.6,y=1.2,color=ACC){ s.addText(t.toUpperCase(), A({x,y,w:11,h:0.32,fontSize:11.5,bold:true,color,fontFace:BODY,charSpacing:3,align:"left"})); }
function framedShot(s, img, x,y,w, cap){
  const iw=800, ih=455, h=w*ih/iw;
  s.addShape(pres.ShapeType.roundRect,{x:x-0.06,y:y-0.06,w:w+0.12,h:h+0.12,rectRadius:0.06,fill:{color:BG2},line:{color:LINE,width:1},shadow:shadow(),objectName:"deco"});
  s.addImage({path:img,x,y,w,h,rounding:false,objectName:"anim2"});
  if(cap) s.addText(cap, A({x,y:y+h+0.12,w,h:0.3,fontSize:9,italic:true,color:MUT,fontFace:BODY,align:"left"}));
  return {h};
}

// =====================================================================
// 1 — TITLE
let s = slide(); s.background={path:"assets/bg_hero.png"};
s.addText([{text:"CYBER-PHYSICAL SECURITY",options:{color:ACC,bold:true}},{text:"   ·   RESEARCH SHOWCASE",options:{color:MUT}}],
  A({x:0.9,y:1.55,w:11,h:0.35,fontSize:12,fontFace:MONO,charSpacing:3}));
s.addText("The lie the\nnetwork can't see.", A({x:0.86,y:2.15,w:11.6,h:2.5,fontSize:58,bold:true,color:INK,fontFace:HEAD,lineSpacingMultiple:0.98,align:"left"}));
s.addText("A digital-twin and physical-watermarking testbed for multi-layer intrusion detection in SCADA systems.",
  A({x:0.9,y:4.85,w:9.4,h:0.8,fontSize:16,color:MUT,fontFace:BODY,lineSpacingMultiple:1.1}));
s.addText([{text:"S. Saurabh Krishnan",options:{bold:true}},{text:"   ·   Hemant Bhupesh   ·   Sanjai S   ·   Nitesh V. M.",options:{color:MUT}}],
  A({x:0.9,y:6.35,w:11,h:0.3,fontSize:13,color:INK,fontFace:BODY}));
s.addText("Amrita Vishwa Vidyapeetham · Coimbatore, India", A({x:0.9,y:6.72,w:11,h:0.3,fontSize:10.5,color:FAINT,fontFace:MONO,charSpacing:1}));
s.addNotes("Title. We built a live, simulated SCADA plant and used it to show that a network-only defender is blind to attacks that lie at the sensor -- and that a digital twin, process physics and an active watermark close that gap.");

// =====================================================================
// 2 — THE BLIND SPOT
s = slide(); topframe(s,"The problem");
kicker(s,"The blind spot");
s.addText("A compromised sensor sends a\nperfect packet with a false value.", A({x:0.6,y:1.6,w:7.1,h:2.1,fontSize:30,bold:true,color:INK,fontFace:HEAD,lineSpacingMultiple:1.04,align:"left",objectName:"anim1"}));
s.addText([
  {text:"The network layer sees nothing wrong — the frame is well-formed and on time. ",options:{color:MUT}},
  {text:"Meanwhile the real process diverges.",options:{color:INK,bold:true}},
], A({x:0.6,y:3.8,w:6.9,h:1.3,fontSize:15,fontFace:BODY,lineSpacingMultiple:1.2,objectName:"anim3"}));
s.addText("Detecting this needs reasoning about the physics of the process, not just its packets.",
  A({x:0.6,y:5.3,w:6.9,h:1,fontSize:14,italic:true,color:ACC2,fontFace:BODY,lineSpacingMultiple:1.2,objectName:"anim4"}));
// right: minimal attack schematic
const px=8.35;
s.addShape(pres.ShapeType.roundRect,{x:px,y:1.55,w:4.35,h:4.7,rectRadius:0.09,fill:{color:PANEL},line:{color:LINE,width:1},shadow:shadow(),objectName:"deco"});
function node2(x,y,w,label,col){ s.addShape(pres.ShapeType.roundRect,{x,y,w,h:0.62,rectRadius:0.07,fill:{color:BG2},line:{color:col,width:1.3},objectName:"anim2"});
  s.addText(label,A({x,y,w,h:0.62,fontSize:12,bold:true,color:INK,fontFace:BODY,align:"center",valign:"middle"}));}
node2(px+0.4,2.1,1.7,"Sensor",ACC2); node2(px+2.25,2.1,1.7,"PLC",AMB); node2(px+1.35,3.5,1.7,"SCADA · HMI",GRN);
s.addShape(pres.ShapeType.line,{x:px+2.1,y:2.41,w:0.15,h:0,line:{color:RED,width:2.6,dashType:"dash",endArrowType:"triangle"},objectName:"anim2"});
s.addText("falsified value",A({x:px+1.75,y:1.72,w:1.6,h:0.3,fontSize:8.5,bold:true,color:RED,fontFace:MONO,align:"center"}));
s.addShape(pres.ShapeType.line,{x:px+2.2,y:2.72,w:0,h:0.78,line:{color:FAINT,width:2,endArrowType:"triangle"}});
s.addText("Operator sees a benign number.",A({x:px+0.4,y:4.45,w:3.55,h:0.4,fontSize:11,italic:true,color:MUT,fontFace:BODY,align:"center"}));
s.addText("The plant does not.",A({x:px+0.4,y:4.8,w:3.55,h:0.5,fontSize:14,bold:true,color:ACC,fontFace:HEAD,align:"center"}));
s.addNotes("The core motivation. A field-device compromise or a sensor-to-PLC MITM presents a plausible-but-false reading; nothing on the wire is anomalous, so a packet-only IDS misses it entirely.");

// =====================================================================
// 3 — TIMELINE
s = slide(); topframe(s,"Context");
kicker(s,"It has already happened");
s.addText("Fifteen years of attacks that reached the physical layer.", A({x:0.6,y:1.6,w:12,h:0.7,fontSize:26,bold:true,color:INK,fontFace:HEAD}));
const ty=4.2, tx0=1.2, tx1=12.1;
s.addShape(pres.ShapeType.line,{x:tx0,y:ty,w:tx1-tx0,h:0,line:{color:LINE,width:2},objectName:"deco"});
const evs=[
 {x:1.9,yr:2010,t:"Stuxnet",d:"Centrifuge sabotage via\nfalsified PLC logic & readings",c:ACC},
 {x:5.1,yr:2015,t:"Ukraine grid",d:"Breakers opened remotely;\noperators locked out",c:ACC2},
 {x:8.3,yr:2017,t:"TRITON / TRISIS",d:"Malware targeting the\nsafety-instrumented system",c:AMB},
 {x:11.0,yr:"Now",t:"This testbed",d:"A place to study and\ndetect these, reproducibly",c:GRN},
];
evs.forEach((e,i)=>{ const up = i%2===0;
  s.addShape(pres.ShapeType.ellipse,{x:e.x-0.09,y:ty-0.09,w:0.18,h:0.18,fill:{color:e.c},line:{color:BG0,width:2},objectName:"anim"+(i+1)});
  const cy = up? ty-1.55 : ty+0.35;
  s.addShape(pres.ShapeType.line,{x:e.x,y:up?cy+1.1:ty,w:0,h:up?ty-(cy+1.1):0.3,line:{color:LINE,width:1},objectName:"anim"+(i+1)});
  s.addText(String(e.yr),A({x:e.x-1.0,y:cy,w:2,h:0.3,fontSize:12,bold:true,color:e.c,fontFace:MONO,align:"center"}));
  s.addText(e.t,A({x:e.x-1.1,y:cy+0.3,w:2.2,h:0.35,fontSize:14,bold:true,color:INK,fontFace:HEAD,align:"center"}));
  s.addText(e.d,A({x:e.x-1.25,y:cy+0.68,w:2.5,h:0.7,fontSize:9.5,color:MUT,fontFace:BODY,align:"center",lineSpacingMultiple:1.05}));
});
s.addText("Dates and incidents are historical fact; the testbed is a simulation.",A({x:0.6,y:6.5,w:9,h:0.3,fontSize:9,italic:true,color:FAINT,fontFace:BODY}));
s.addNotes("Context: Stuxnet (2010), the Ukrainian grid attacks (2015/16) and TRITON (2017) all reached the physical/safety layer. Our testbed is a reproducible place to study and detect such attacks.");

// =====================================================================
// 4 — THE TESTBED (plant screenshot + stats)
s = slide(); topframe(s,"What we built");
kicker(s,"The testbed");
s.addText("A liquid-metal boiler plant, alive at 10 Hz.", A({x:0.6,y:1.6,w:12,h:0.7,fontSize:26,bold:true,color:INK,fontFace:HEAD,objectName:"anim1"}));
framedShot(s,"assets/plant_overview.jpg",0.6,2.55,7.7,"Operator HMI — animated P&ID, live telemetry, independent safety panel.");
const stats=[["37","sensors",ACC2],["17","actuators",VIO],["5","PLCs / RTU",AMB],["72","network nodes",GRN],["10 Hz","live engine",ACC],["56","tests passing",INK]];
stats.forEach((st,i)=>{ const col=i%2,row=Math.floor(i/2); const x=8.7+col*2.05,y=2.6+row*1.35;
  s.addText(st[0],A({x,y,w:2.0,h:0.65,fontSize:30,bold:true,color:st[2],fontFace:HEAD,objectName:"anim"+(3+i)}));
  s.addText(st[1],A({x,y:y+0.62,w:2.0,h:0.35,fontSize:11,color:MUT,fontFace:BODY}));
});
s.addNotes("The platform: a simulated liquid-metal boiler plus four auxiliary subsystems, with 37 sensors, 17 actuators, five controllers and a 72-node network, running live at 10 Hz and covered by 56 automated tests.");

// =====================================================================
// 5 — THE NETWORK (network screenshot)
s = slide(); topframe(s,"What we built");
kicker(s,"The simulated network","0.6",1.2,ACC2);
s.addText("Purdue-zoned, protocol-aware, tapped.", A({x:0.6,y:1.6,w:7,h:1.1,fontSize:26,bold:true,color:INK,fontFace:HEAD,lineSpacingMultiple:1.0,objectName:"anim1"}));
s.addText([
 {text:"Modbus TCP",options:{bold:true,color:INK}},{text:" as spec-conformant ADU bytes; ",options:{color:MUT}},
 {text:"OPC UA",options:{bold:true,color:INK}},{text:" and ",options:{color:MUT}},{text:"MQTT",options:{bold:true,color:INK}},
 {text:" emulated. A discrete-event bus adds latency, loss and MITM, and mirrors supervisory traffic to the IDS through a SPAN port.",options:{color:MUT}},
], A({x:0.6,y:2.95,w:3.9,h:3,fontSize:14,fontFace:BODY,lineSpacingMultiple:1.3,valign:"top",objectName:"anim3"}));
framedShot(s,"assets/network_topology.jpg",4.9,2.1,7.8,"Live SPAN-mirrored Modbus / MQTT traffic feeding the four-layer IDS.");
s.addNotes("The network is a Purdue-zoned graph with an industrial firewall and a cellular link to a remote RTU. Modbus TCP uses real ADU bytes; OPC UA and MQTT are honestly labelled as application-level emulation. A SPAN mirror feeds the IDS exactly what a real tap would.");

// =====================================================================
// 6 — DIVIDER 01
s = slide(); s.background={path:"assets/bg_section.png"};
s.addText("01", A({x:0.9,y:2.1,w:3,h:1.6,fontSize:120,bold:true,color:"1C2230",fontFace:HEAD}));
s.addText("THE SYSTEM", A({x:0.95,y:3.9,w:11,h:0.4,fontSize:14,bold:true,color:ACC,fontFace:MONO,charSpacing:5}));
s.addText("How the plant, the twin, the detectors\nand the watermark fit together.", A({x:0.9,y:4.35,w:11,h:1.3,fontSize:28,bold:true,color:INK,fontFace:HEAD,lineSpacingMultiple:1.05}));
s.addNotes("Section 1: the system -- architecture, the control loop, and the three add-ons that make it a security platform.");

// =====================================================================
// 7 — ARCHITECTURE
s = slide(); topframe(s,"The system");
kicker(s,"Architecture");
s.addText("Five layers, watched by four observers.", A({x:0.6,y:1.6,w:12,h:0.6,fontSize:24,bold:true,color:INK,fontFace:HEAD}));
const lay=[["Supervisory — SCADA · HMI · historian · auth",FAINT],["Network bus — routing · loss · SPAN mirror",FAINT],["PLCs / RTU — PI(D) control · Modbus / MQTT",FAINT],["Field devices — sensors · actuators",FAINT],["Physical plant — ground truth",GRN]];
lay.forEach((l,i)=>{ const y=2.55+i*0.78;
  s.addShape(pres.ShapeType.roundRect,{x:0.6,y,w:6.7,h:0.64,rectRadius:0.06,fill:{color:i===4?"10231A":PANEL},line:{color:i===4?GRN:LINE,width:1},objectName:"anim"+(i+1)});
  s.addText(l[0],A({x:0.85,y,w:6.3,h:0.64,fontSize:12.5,bold:i===4,color:i===4?GRN:INK,fontFace:BODY,valign:"middle"}));
  if(i<4) s.addShape(pres.ShapeType.line,{x:3.95,y:y+0.64,w:0,h:0.14,line:{color:FAINT,width:1.4,beginArrowType:"triangle",endArrowType:"triangle"}});
});
// observers
s.addShape(pres.ShapeType.roundRect,{x:7.8,y:2.4,w:4.9,h:3.95,rectRadius:0.09,fill:{color:"1A1410"},line:{color:ACC,width:1.2,dashType:"dash"},objectName:"anim6"});
s.addText("OBSERVERS",A({x:8.05,y:2.6,w:4,h:0.3,fontSize:10,bold:true,color:ACC,fontFace:MONO,charSpacing:3}));
const obs=[["Digital twin","independent physics + residuals",GRN],["Four-layer IDS","network · process · twin · watermark",ACC2],["Correlation","dedup · classify · fuse confidence",VIO],["Response","monitor / approve / automatic",AMB]];
obs.forEach((o,i)=>{ const y=3.05+i*0.8;
  s.addShape(pres.ShapeType.ellipse,{x:8.05,y:y+0.06,w:0.2,h:0.2,fill:{color:o[2]},line:{type:"none"}});
  s.addText(o[0],A({x:8.4,y,w:4.1,h:0.32,fontSize:13,bold:true,color:INK,fontFace:BODY}));
  s.addText(o[1],A({x:8.4,y:y+0.32,w:4.1,h:0.3,fontSize:10,color:MUT,fontFace:BODY}));
});
s.addText("Invariant: the attacker touches only the network and field devices — never the twin, IDS, watermark or safety system.",
  A({x:0.6,y:6.5,w:12,h:0.35,fontSize:11,italic:true,color:ACC,fontFace:BODY,objectName:"anim7"}));
s.addNotes("Architecture: a strictly layered stack advanced at 10 Hz, observed by the twin, the four-layer IDS, the correlation engine and the response engine. A key invariant, checked by tests, is that the attacker can only reach the network and field devices.");

// =====================================================================
// 8 — THE 10 Hz LOOP (flowchart)
s = slide(); topframe(s,"The system");
kicker(s,"The 10 Hz loop");
s.addText("One tick, in a fixed order.", A({x:0.6,y:1.6,w:12,h:0.6,fontSize:24,bold:true,color:INK,fontFace:HEAD}));
const steps=[["1","Attack lab applies manipulations",ACC],["2","Physical plant integrates (ground truth)",GRN],["3","Hard-wired safety (SIS) may trip",GRN],["4","Field I/O — sensors sample, PLCs scan",FAINT],["5","Network bus delivers (SPAN mirror)",FAINT],["6","SCADA polling · historian · twin feeds",FAINT],["7","Digital twin + watermark update",FAINT],["8","IDS (4 layers) → correlation",FAINT],["9","Response engine → snapshot",ACC]];
steps.forEach((st,i)=>{ const y=2.5+i*0.47;
  s.addShape(pres.ShapeType.roundRect,{x:0.6,y,w:6.9,h:0.4,rectRadius:0.05,fill:{color:PANEL},line:{color:(st[2]===FAINT?LINE:st[2]),width:1},objectName:"anim"+(i+1)});
  s.addShape(pres.ShapeType.ellipse,{x:0.73,y:y+0.08,w:0.24,h:0.24,fill:{color:st[2]===FAINT?BG2:st[2]},line:{type:"none"},objectName:"anim"+(i+1)});
  s.addText(st[0],A({x:0.73,y:y+0.08,w:0.24,h:0.24,fontSize:10,bold:true,color:st[2]===FAINT?MUT:BG0,fontFace:MONO,align:"center",valign:"middle"}));
  s.addText(st[1],A({x:1.15,y,w:6.2,h:0.4,fontSize:11.5,color:INK,fontFace:BODY,valign:"middle"}));
});
// right callout
s.addShape(pres.ShapeType.roundRect,{x:8.1,y:2.5,w:4.6,h:3.85,rectRadius:0.09,fill:{color:PANEL},line:{color:LINE,width:1},shadow:shadow(),objectName:"anim10"});
s.addText("What they never see",A({x:8.4,y:2.75,w:4,h:0.4,fontSize:14,bold:true,color:ACC,fontFace:HEAD}));
s.addText([
 {text:"Green steps read the ",options:{color:MUT}},{text:"true plant state.",options:{color:GRN,bold:true,breakLine:true}},
 {text:"\nThe attacker (step 1) acts only through network and field hooks.",options:{color:MUT,breakLine:true}},
 {text:"\nThe IDS (steps 5–8) sees only the SPAN mirror — the same bytes a real tap would capture.",options:{color:MUT}},
], A({x:8.4,y:3.25,w:4.0,h:3,fontSize:13,fontFace:BODY,lineSpacingMultiple:1.25,valign:"top"}));
s.addNotes("The engine runs a fixed per-tick sequence at 10 Hz. The attacker manipulates before the physics step; the safety system and the plant read the real state; the IDS only ever sees the SPAN mirror. Ground-truth labels never reach the detectors.");

// =====================================================================
// 9 — INDEPENDENT TWIN
s = slide(); topframe(s,"The system · add-on 01");
kicker(s,"The independent twin",0.6,1.2,GRN);
s.addText("A model that won't absorb a lie.", A({x:0.6,y:1.6,w:7.4,h:1.1,fontSize:28,bold:true,color:INK,fontFace:HEAD,lineSpacingMultiple:1.0,objectName:"anim1"}));
s.addText([
 {text:"The twin runs its ",options:{color:MUT}},{text:"own RK4 physics",options:{color:INK,bold:true}},
 {text:" with datasheet parameters — it never reads the plant's hidden state. Each tick it predicts, then fuses each measurement through a ",options:{color:MUT}},
 {text:"gate",options:{color:GRN,bold:true}},{text:".",options:{color:MUT}},
], A({x:0.6,y:3.0,w:6.3,h:1.6,fontSize:14.5,fontFace:BODY,lineSpacingMultiple:1.3,valign:"top",objectName:"anim3"}));
s.addText("A reading that jumps outside the gate (|z| < 5) is rejected — so a stealthy lie shows up as a growing residual instead of quietly corrupting the estimate.",
  A({x:0.6,y:4.9,w:6.3,h:1.4,fontSize:13,italic:true,color:ACC2,fontFace:BODY,lineSpacingMultiple:1.25,objectName:"anim4"}));
// right: equation card + demo numbers
s.addShape(pres.ShapeType.roundRect,{x:7.35,y:2.0,w:5.35,h:4.35,rectRadius:0.1,fill:{color:PANEL},line:{color:LINE,width:1},shadow:shadow(),objectName:"anim2"});
s.addText("r  =  observed  −  predicted",A({x:7.7,y:2.4,w:4.7,h:0.45,fontSize:17,bold:true,color:INK,fontFace:MONO}));
s.addText("z  =  ( r − bias ) / σ",A({x:7.7,y:2.95,w:4.7,h:0.45,fontSize:17,color:AMB,fontFace:MONO}));
s.addShape(pres.ShapeType.line,{x:7.7,y:3.7,w:4.65,h:0,line:{color:LINE,width:1}});
s.addText("IN THE LIVE FALSE-DATA DEMO",A({x:7.7,y:3.85,w:4.7,h:0.3,fontSize:9.5,bold:true,color:FAINT,fontFace:MONO,charSpacing:2}));
s.addText([{text:"real 459.8 °C",options:{bold:true,color:GRN,fontSize:19,breakLine:true}},
  {text:"vs falsified 442.3 °C shown to the operator",options:{color:MUT,fontSize:12,breakLine:true}}],
  A({x:7.7,y:4.25,w:4.7,h:1,valign:"top"}));
s.addText("twin residual  z = −24.9",A({x:7.7,y:5.55,w:4.7,h:0.5,fontSize:20,bold:true,color:ACC,fontFace:HEAD}));
s.addNotes("Add-on 1: the independent twin. The gate is the crucial idea -- continuously correcting toward measurements would let a slow lie pass; gating keeps the twin anchored to physics, so the lie becomes a large residual (z = -24.9 in the live demo).");

// =====================================================================
// 10 — FOUR-LAYER IDS
s = slide(); topframe(s,"The system · add-on 02");
kicker(s,"Four layers, one verdict",0.6,1.2,ACC2);
s.addText("Each layer covers another's blind spot.", A({x:0.6,y:1.6,w:12,h:0.6,fontSize:24,bold:true,color:INK,fontFace:HEAD}));
const dets=[["NETWORK",ACC2,"rogue devices · spoofing · floods · replay · unauthorised writes"],
  ["PROCESS",VIO,"limits · frozen signals · rate-of-change · setpoint deviation · energy balance"],
  ["TWIN",GRN,"persistent & sudden residuals · correlated multi-sensor anomalies"],
  ["WATERMARK",AMB,"missing or abnormal response to the injected excitation"]];
dets.forEach((d,i)=>{ const col=i%2,row=Math.floor(i/2); const x=0.6+col*6.15,y=2.5+row*1.35;
  s.addShape(pres.ShapeType.roundRect,{x,y,w:5.85,h:1.15,rectRadius:0.08,fill:{color:PANEL},line:{color:d[1],width:1.2},shadow:shadow(),objectName:"anim"+(i+1)});
  s.addText(d[0],A({x:x+0.3,y:y+0.16,w:5.2,h:0.4,fontSize:16,bold:true,color:d[1],fontFace:BODY,charSpacing:2}));
  s.addText(d[2],A({x:x+0.3,y:y+0.58,w:5.3,h:0.5,fontSize:11.5,color:MUT,fontFace:BODY,valign:"top"}));
});
s.addShape(pres.ShapeType.roundRect,{x:0.6,y:5.5,w:12.1,h:0.95,rectRadius:0.08,fill:{color:"1A1410"},line:{color:ACC,width:1},objectName:"anim5"});
s.addText([{text:"Correlation engine:  ",options:{bold:true,color:ACC}},
  {text:"deduplicates findings into one incident, fuses confidence  C = 1 − Π(1 − c",options:{color:INK}},
  {text:"i",options:{color:INK,subscript:true}},{text:"),  raises severity per corroborating layer, and classifies.",options:{color:INK}}],
  A({x:0.9,y:5.5,w:11.5,h:0.95,fontSize:13,fontFace:BODY,valign:"middle"}));
s.addNotes("Add-on 2: four independent detectors feed one correlation engine, which deduplicates evidence into a single classified incident and fuses confidence probabilistically -- so a coordinated attack no single layer sees in full still surfaces as one high-confidence incident.");

// =====================================================================
// 11 — WATERMARKING
s = slide(); topframe(s,"The system · add-on 03");
kicker(s,"Physical watermarking",0.6,1.2,AMB);
s.addText("Probe the process, then listen for the echo.", A({x:0.6,y:1.6,w:12,h:0.6,fontSize:24,bold:true,color:INK,fontFace:HEAD}));
const w3=[["INJECT",ACC,"A bounded PRBS excitation is added to the pump command inside the PLC's secured block. The exported register still reports the base value."],
  ["PREDICT",ACC2,"Two shadow copies of the twin's hydraulics compute the expected response to the excitation."],
  ["COMPARE",GRN,"Observed flow & pressure are matched to the expected response by correlation ρ, gain and SNR."]];
w3.forEach((w,i)=>{ const x=0.6+i*4.1;
  s.addShape(pres.ShapeType.roundRect,{x,y:2.6,w:3.8,h:2.75,rectRadius:0.09,fill:{color:PANEL},line:{color:LINE,width:1},shadow:shadow(),objectName:"anim"+(i+1)});
  s.addText(String(i+1),A({x:x+0.3,y:2.8,w:0.7,h:0.7,fontSize:30,bold:true,color:w[1],fontFace:HEAD}));
  s.addText(w[0],A({x:x+1.0,y:2.95,w:2.6,h:0.45,fontSize:15,bold:true,color:w[1],fontFace:BODY,charSpacing:2,valign:"middle"}));
  s.addText(w[2],A({x:x+0.3,y:3.65,w:3.2,h:1.6,fontSize:12,color:MUT,fontFace:BODY,valign:"top",lineSpacingMultiple:1.2}));
  if(i<2) s.addShape(pres.ShapeType.line,{x:x+3.82,y:3.97,w:0.26,h:0,line:{color:FAINT,width:2,endArrowType:"triangle"}});
});
s.addText([{text:"Decision:  ",options:{bold:true,color:INK}},{text:"consistent",options:{bold:true,color:GRN}},{text:"  /  ",options:{color:FAINT}},
  {text:"suspicious",options:{bold:true,color:RED}},{text:"  /  ",options:{color:FAINT}},{text:"inconclusive",options:{bold:true,color:AMB}},
  {text:"      Self-suspends on a safety trip, saturation or poor measurement quality — never forces an unsafe perturbation.",options:{color:MUT,fontSize:11.5}}],
  A({x:0.6,y:5.7,w:12.1,h:0.6,fontSize:14,fontFace:BODY,objectName:"anim4"}));
s.addNotes("Add-on 3: active defence. We inject a secret, bounded signal and check the process actually responds to it. A replay or smoothing attack that erases the signature is flagged. Baseline correlation is ~0.80 (flow) and ~0.95 (pressure).");

// =====================================================================
// 12 — DIVIDER 02
s = slide(); s.background={path:"assets/bg_section.png"};
s.addText("02", A({x:0.9,y:2.1,w:3,h:1.6,fontSize:120,bold:true,color:"1C2230",fontFace:HEAD}));
s.addText("THE EVIDENCE", A({x:0.95,y:3.9,w:11,h:0.4,fontSize:14,bold:true,color:ACC,fontFace:MONO,charSpacing:5}));
s.addText("Ten attacks, one honest question:\nwhich layers actually catch them?", A({x:0.9,y:4.35,w:11,h:1.3,fontSize:28,bold:true,color:INK,fontFace:HEAD,lineSpacingMultiple:1.05}));
s.addNotes("Section 2: the evidence -- the attack laboratory, a live demonstration, and the quantitative results.");

// =====================================================================
// 13 — ATTACK LAB
s = slide(); topframe(s,"The evidence");
kicker(s,"The attack laboratory");
s.addText("Ten reproducible scenarios.", A({x:0.6,y:1.6,w:12,h:0.6,fontSize:24,bold:true,color:INK,fontFace:HEAD}));
const atk=["False sensor-data injection","Frozen sensor readings","Actuator-response manipulation","Unauthorised setpoint write","Command replay","Supervisory-link DoS","Insider / out-of-policy write","Digital-twin model tamper","Watermark interference","Coordinated process + network"];
atk.forEach((a,i)=>{ const col=i%2,row=Math.floor(i/2); const x=0.6+col*6.15,y=2.5+row*0.72;
  s.addShape(pres.ShapeType.roundRect,{x,y,w:5.85,h:0.6,rectRadius:0.06,fill:{color:PANEL},line:{color:LINE,width:0.75},objectName:"anim"+(row+1)});
  s.addShape(pres.ShapeType.ellipse,{x:x+0.22,y:y+0.17,w:0.26,h:0.26,fill:{color:ACC},line:{type:"none"}});
  s.addText(String(i+1),A({x:x+0.22,y:y+0.17,w:0.26,h:0.26,fontSize:10,bold:true,color:BG0,fontFace:MONO,align:"center",valign:"middle"}));
  s.addText(a,A({x:x+0.62,y,w:5.1,h:0.6,fontSize:12.5,color:INK,fontFace:BODY,valign:"middle"}));
});
s.addText("Each records its seed, makes real changes, exposes a ground-truth label, and supports stop/recover. Detection must come from evidence — starting a scenario raises no alert by itself.",
  A({x:0.6,y:6.35,w:12.1,h:0.5,fontSize:11,italic:true,color:ACC2,fontFace:BODY,objectName:"anim6"}));
s.addNotes("Ten reproducible attacks. The key property: during telemetry falsification the real plant keeps running on real actuator action while only the observed values are faked -- and ground-truth labels never reach the detectors.");

// =====================================================================
// 14 — LIVE FDI (twin screenshot)
s = slide(); topframe(s,"The evidence · live");
kicker(s,"Live — false data injection");
s.addText("The twin tells the truth the sensor hides.", A({x:0.6,y:1.6,w:12,h:0.6,fontSize:24,bold:true,color:INK,fontFace:HEAD,objectName:"anim1"}));
framedShot(s,"assets/twin_divergence.jpg",0.6,2.5,7.9,"Observed (blue) is pulled to the fake value; the twin prediction (orange) keeps tracking reality.");
const dnum=[["459.8 °C",GRN,"real hot-leg temperature"],["442.3 °C",RED,"shown to the operator"],["z = −24.9",ACC,"twin residual, CUSUM saturated"],["96 %",VIO,"incident confidence"]];
dnum.forEach((d,i)=>{ const y=2.55+i*1.0;
  s.addText(d[0],A({x:8.9,y,w:3.8,h:0.5,fontSize:24,bold:true,color:d[1],fontFace:HEAD,objectName:"anim"+(3+i)}));
  s.addText(d[2],A({x:8.92,y:y+0.5,w:3.8,h:0.35,fontSize:11,color:MUT,fontFace:BODY}));
});
s.addNotes("The money shot. A -18C bias is injected on the hot-leg sensor. The real temperature rises while the operator sees the fake value; the independent twin flags it at z = -24.9 and the engine raises a critical incident at 96% confidence.");

// =====================================================================
// 15 — DETECTION CORRELATED (security screenshot)
s = slide(); topframe(s,"The evidence · live");
kicker(s,"Correlated, then contained");
s.addText("Two layers fire. One incident. An automatic response.", A({x:0.6,y:1.6,w:12,h:0.6,fontSize:23,bold:true,color:INK,fontFace:HEAD,objectName:"anim1"}));
framedShot(s,"assets/security_center.jpg",5.0,2.4,7.7,"Alert feed, the correlated critical incident, and the executed responses.");
const flow3=[["PROCESS + TWIN fire",ACC2,"energy-balance + sudden-residual evidence — the network stays silent"],
  ["Correlated incident",VIO,"“False data injection” · critical · 96% confidence"],
  ["Automatic response",GRN,"mark suspicious · secure-channel failover · preserve evidence"]];
flow3.forEach((f,i)=>{ const y=2.55+i*1.3;
  s.addShape(pres.ShapeType.roundRect,{x:0.6,y,w:4.0,h:1.1,rectRadius:0.08,fill:{color:PANEL},line:{color:f[1],width:1},objectName:"anim"+(2+i)});
  s.addText(f[0],A({x:0.82,y:y+0.14,w:3.6,h:0.4,fontSize:13.5,bold:true,color:f[1],fontFace:BODY}));
  s.addText(f[2],A({x:0.82,y:y+0.52,w:3.6,h:0.5,fontSize:10.5,color:MUT,fontFace:BODY,valign:"top",lineSpacingMultiple:1.1}));
  if(i<2) s.addShape(pres.ShapeType.line,{x:2.6,y:y+1.1,w:0,h:0.2,line:{color:FAINT,width:1.6,endArrowType:"triangle"}});
});
s.addNotes("Detection to containment. The process and twin layers fire -- not the network -- and the correlation engine raises one critical incident; in automatic mode the response engine marks the sensor suspicious, fails over to a secure channel and preserves evidence.");

// =====================================================================
// 16 — RESULTS TABLE
s = slide(); topframe(s,"The evidence");
kicker(s,"Results");
s.addText("Detection F1 by configuration.", A({x:0.6,y:1.6,w:12,h:0.6,fontSize:24,bold:true,color:INK,fontFace:HEAD}));
const hdr=["Scenario","Net only","Net+Proc","+Twin","Full+WM","Latency"];
const rows=[["A. Normal operation","—","—","—","—","—"],
 ["B. False data injection","miss","0.94","0.94","0.94","0.2 s"],
 ["C. Watermark interference","miss","miss","0.71","0.96","1.1 s"],
 ["D. Unauthorised setpoint","0.91","0.91","0.91","0.91","0.0 s"],
 ["E. Command replay","0.93","0.93","0.93","0.93","0.5 s"],
 ["F. Coordinated","0.91","0.91","0.91","0.91","0.5 s"]];
const tbl=[hdr.map(h=>({text:h,options:{bold:true,color:INK,fill:{color:BG2},fontFace:BODY,fontSize:12,align:"center",valign:"middle"}}))];
rows.forEach((r,ri)=>{ tbl.push(r.map((c,ci)=>{ let color=ci===0?INK:MUT; if(c==="miss")color=RED; else if(/^0\.9/.test(c))color=GRN; else if(c==="0.71")color=AMB;
  return {text:c,options:{color,bold:ci===0,fontFace:BODY,fontSize:12,align:ci===0?"left":"center",valign:"middle",fill:{color:ri%2?PANEL:"10131B"}}};}));});
s.addTable(tbl,{x:0.6,y:2.55,w:12.1,colW:[3.7,1.7,1.7,1.5,1.7,1.8],rowH:0.52,border:{type:"solid",color:BG0,pt:1.5},objectName:"anim1"});
s.addText([{text:"Network-only is blind to B and C",options:{bold:true,color:ACC}},
  {text:"  — field-bus lies leave no network evidence. Process + twin recover B in 0.2 s; the watermark lifts C from 0.71 to 0.96.",options:{color:MUT}}],
  A({x:0.6,y:6.2,w:12.1,h:0.6,fontSize:13,fontFace:BODY,objectName:"anim2"}));
s.addNotes("The headline table. Read left to right: adding layers recovers the attacks the network cannot see, while command-path attacks (D, E, F) are caught by the network alone. The watermark specifically rescues scenario C.");

// =====================================================================
// 17 — KEY FINDING (chart)
s = slide(); topframe(s,"The evidence");
kicker(s,"The key finding");
s.addText("Zero, or ninety-four.", A({x:0.6,y:1.6,w:7,h:0.7,fontSize:30,bold:true,color:INK,fontFace:HEAD,objectName:"anim1"}));
s.addText("For telemetry-falsification attacks, a packet-only IDS scores nothing. The extra layers do all the work.",
  A({x:0.6,y:2.35,w:6.0,h:1,fontSize:14,color:MUT,fontFace:BODY,lineSpacingMultiple:1.25,objectName:"anim2"}));
const chart=[{name:"Network only",labels:["False data injection","Watermark interference"],values:[0.0,0.0]},
  {name:"Full stack + watermark",labels:["False data injection","Watermark interference"],values:[0.94,0.96]}];
s.addChart(pres.ChartType.bar,chart,{x:0.5,y:3.4,w:6.6,h:3.5,barDir:"col",barGrouping:"clustered",chartColors:[RED,GRN],
  showLegend:true,legendPos:"t",legendColor:MUT,legendFontFace:"+mn-lt",legendFontSize:11,showTitle:false,
  valAxisMinVal:0,valAxisMaxVal:1,valAxisMajorUnit:0.25,showValue:true,dataLabelPosition:"outEnd",dataLabelColor:INK,
  dataLabelFontFace:"+mn-lt",dataLabelFontSize:11,dataLabelFormatCode:"0.00",catAxisLabelColor:MUT,catAxisLabelFontFace:"+mn-lt",
  catAxisLabelFontSize:10,valAxisLabelColor:MUT,valAxisLabelFontFace:"+mn-lt",valAxisLabelFontSize:9,
  valGridLine:{color:LINE,size:1},catGridLine:{style:"none"},valAxisLineColor:LINE,catAxisLineColor:LINE,objectName:"anim3"});
s.addShape(pres.ShapeType.roundRect,{x:7.5,y:2.3,w:5.2,h:4.5,rectRadius:0.1,fill:{color:PANEL},line:{color:LINE,width:1},shadow:shadow(),objectName:"anim4"});
s.addText("THE WHOLE ARGUMENT",A({x:7.8,y:2.55,w:4.6,h:0.3,fontSize:10,bold:true,color:ACC,fontFace:MONO,charSpacing:2}));
const take=[["Command-path attacks",ACC2,"caught by the network layer."],["Telemetry falsification",GRN,"invisible there — caught by process + twin."],["Erased signatures",AMB,"caught by the active watermark."]];
take.forEach((t,i)=>{ const y=3.05+i*1.15;
  s.addText(t[0],A({x:7.8,y,w:4.6,h:0.35,fontSize:15,bold:true,color:t[1],fontFace:BODY}));
  s.addText(t[2],A({x:7.8,y:y+0.38,w:4.6,h:0.6,fontSize:12.5,color:MUT,fontFace:BODY,lineSpacingMultiple:1.15,valign:"top"}));
});
s.addNotes("The single most important result. Each layer covers a blind spot of the others, and only the full stack fused by correlation covers all four attack families.");

// =====================================================================
// 18 — AUTHOR CONTRIBUTIONS
s = slide(); topframe(s,"Credits");
kicker(s,"Who built what");
s.addText("Author contributions.", A({x:0.6,y:1.6,w:12,h:0.6,fontSize:24,bold:true,color:INK,fontFace:HEAD}));
const contrib=[["S. Saurabh Krishnan",GRN,"Digital twin — model, gated correction, residual/CUSUM analysis — and the experiment & evaluation framework and 56-test suite."],
 ["Hemant Bhupesh",ACC2,"Plant & network simulation — boiler and subsystems, device abstractions, PLC/RTU control, the safety system and the protocol layer."],
 ["Sanjai S",VIO,"Multi-layer IDS and correlation, the ten attack scenarios, and the automated defensive-response engine."],
 ["Nitesh V. M.",AMB,"Physical watermarking, the React operator HMI, the FastAPI/WebSocket backend and persistence, and documentation."]];
contrib.forEach((c,i)=>{ const col=i%2,row=Math.floor(i/2); const x=0.6+col*6.15,y=2.6+row*1.9;
  s.addShape(pres.ShapeType.roundRect,{x,y,w:5.85,h:1.65,rectRadius:0.08,fill:{color:PANEL},line:{color:LINE,width:1},shadow:shadow(),objectName:"anim"+(i+1)});
  s.addShape(pres.ShapeType.ellipse,{x:x+0.3,y:y+0.3,w:0.22,h:0.22,fill:{color:c[1]},line:{type:"none"}});
  s.addText(c[0],A({x:x+0.65,y:y+0.22,w:5,h:0.4,fontSize:15,bold:true,color:INK,fontFace:HEAD}));
  s.addText(c[2],A({x:x+0.3,y:y+0.68,w:5.3,h:0.9,fontSize:11.5,color:MUT,fontFace:BODY,valign:"top",lineSpacingMultiple:1.2}));
});
s.addNotes("Author contributions across the four team members.");

// =====================================================================
// 19 — CLOSING
s = slide(); s.background={path:"assets/bg_close.png"};
s.addText("DEFENCE IN THE PHYSICS",A({x:0.9,y:1.9,w:11,h:0.4,fontSize:13,bold:true,color:ACC,fontFace:MONO,charSpacing:5}));
s.addText("A network-only defender is blind.\nA twin, the physics and a watermark can see.", A({x:0.86,y:2.4,w:11.6,h:1.8,fontSize:34,bold:true,color:INK,fontFace:HEAD,lineSpacingMultiple:1.06}));
s.addText("Full multi-layer stack: sensor falsification detected in 0.2 s (F1 0.94) where network-only scores 0.00. Live at 10 Hz, reproducible, 56 tests.",
  A({x:0.9,y:4.5,w:10.5,h:0.9,fontSize:14,color:MUT,fontFace:BODY,lineSpacingMultiple:1.2}));
s.addText([{text:"Thank you.",options:{bold:true,color:INK,fontSize:18}}], A({x:0.9,y:5.6,w:6,h:0.4,fontFace:HEAD}));
s.addText([{text:"S. Saurabh Krishnan · Hemant Bhupesh · Sanjai S · Nitesh V. M.",options:{color:MUT,breakLine:true}},
  {text:"Amrita Vishwa Vidyapeetham, Coimbatore · educational research simulation",options:{color:FAINT,fontSize:10}}],
  A({x:0.9,y:6.25,w:11.5,h:0.7,fontSize:12,fontFace:BODY}));
s.addText("Refs: Stuxnet (Symantec, 2011) · Mo & Sinopoli (Allerton 2009) · Mo et al. (IEEE CSM 2015) · Cárdenas et al. (ASIACCS 2011) · Urbina et al. (CCS 2016) · Goh et al. (CRITIS 2016) · Lee et al. (E-ISAC/SANS 2016).",
  A({x:0.9,y:7.0,w:11.6,h:0.3,fontSize:7.5,color:FAINT,fontFace:BODY}));
s.addNotes("Close. The thesis in one line: defence must live in the physics, not just the packets. Headline numbers and references. Thank the audience and invite questions.");

pres.writeFile({ fileName: process.argv[2] || "presentation.pptx" }).then(f=>console.log("WROTE "+f)).catch(e=>{console.error(e);process.exit(1);});
