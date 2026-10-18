#!/usr/bin/env python3
"""Generate the illustrated chapter's SVG diagrams; Python standard library only."""
from pathlib import Path
from html import escape
import json
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'figures'
G='#1f7a6d'; T='#6a3d9a'; P='#c4661f'; F='#1d5f9e'; R='#b03a2e'; K='#333333'; GR='#777777'
BG={G:'#e9f3f0',T:'#f1ecf7',P:'#fbefe6',F:'#eaf1f8',R:'#faeeeb',GR:'#f3f3f3',K:'#eeeeee'}
manifest=[]
class Fig:
 def __init__(self,n,title,h=330):
  self.n=n;self.title=title;self.h=h
  self.s=[f'<svg xmlns="http://www.w3.org/2000/svg" width="760" height="{h}" viewBox="0 0 760 {h}" role="img" aria-label="{escape(title)}">',f'<title>{escape(title)}</title>', '<rect width="760" height="100%" fill="white"/>', '<defs>']
  for c in [G,T,P,F,R,K,GR]:
   self.s.append(f'<marker id="a{c[1:]}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="{c}"/></marker>')
  self.s.append('</defs><g font-family="DejaVu Sans, sans-serif" fill="#333333" font-size="16">')
 def text(self,x,y,s,color=K,size=16,bold=False,anchor='start'):
  for i,line in enumerate(s.split('\n')):
   self.s.append(f'<text x="{x}" y="{y+i*(size+6)}" text-anchor="{anchor}" font-size="{size}" fill="{color}"'+(' font-weight="bold"' if bold else '')+f'>{escape(line)}</text>')
 def rect(self,x,y,w,h,c=G,fill=None,dash=False):
  self.s.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="3" fill="{fill or BG[c]}" stroke="{c}" stroke-width="1.5"'+(' stroke-dasharray="6 4"' if dash else '')+'/>')
 def line(self,x,y,x2,y2,c=GR,arrow=True,dash=False):
  self.s.append(f'<path d="M{x} {y} L{x2} {y2}" fill="none" stroke="{c}" stroke-width="2"'+(f' marker-end="url(#a{c[1:]})"' if arrow else '')+(' stroke-dasharray="6 4"' if dash else '')+'/>')
 def path(self,d,c=GR,arrow=True,dash=False):
  self.s.append(f'<path d="{d}" fill="none" stroke="{c}" stroke-width="2"'+(f' marker-end="url(#a{c[1:]})"' if arrow else '')+(' stroke-dasharray="6 4"' if dash else '')+'/>')
 def node(self,x,y,label,c=G,sub=None,dash=False,w=64):
  self.rect(x-w/2,y-22,w,44,c,fill='white',dash=dash)
  self.text(x,y+6,label,c,18,True,'middle')
  if sub: self.text(x,y+47,sub,c,16,False,'middle')
 def dot(self,x,y,c=G,r=5): self.s.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{c}"/>')
 def save(self,caption):
  (OUT/(self.n+'.svg')).write_text('\n'.join(self.s+['</g></svg>']))
  manifest.append({'file':self.n+'.svg','title':self.title,'caption':caption})

f=Fig('architecture','Separate messages, separate decision paths',455)
f.rect(20,35,200,90,G);f.text(34,64,'512 committee seats',G,17,True);f.text(34,94,'Every slot: head votes')
f.rect(270,35,210,90,G);f.text(284,64,'Goldfish (Ch. 3–4)',G,18,True);f.text(284,94,'Head + confirmation')
f.line(220,80,270,80,G)
f.rect(530,35,210,110,T);f.text(545,62,'Safe-confirmed',T,17,True);f.text(545,91,'Confirmed prefix');f.text(545,117,'filtered for conflict')
f.line(480,80,530,80,G)
f.rect(20,235,200,105,F);f.text(34,264,'Full validator set',F,17,True);f.text(34,293,'Once per round');f.text(34,319,'Head + finality fields')
f.rect(270,235,210,105,T);f.text(284,264,'Stabilization (Ch. 5–6)',T,18,True);f.text(284,293,'Anchor root (G1 / TSQ)');f.text(284,319,'Conflict veto (G0)')
f.line(220,280,270,280,T)
f.line(375,235,375,125,T);f.text(275,169,'Anchor-root',T,15);f.text(275,191,'floor',T,15)
f.path('M480 310 L510 310 L510 123 L530 123',T)
f.rect(530,200,210,90,F);f.text(545,229,'Finality choice (Ch. 7)',F,17,True);f.text(545,259,'Freeze → sign at duty')
f.line(635,145,635,200,T)
f.rect(530,350,210,90,F);f.text(545,379,'Height outcomes',F,17,True);f.text(545,409,'Justify → finalize')
f.line(635,290,635,350,F);f.text(646,322,'Include',F,15)
f.path('M220 319 L240 319 L240 405 L530 405',F)
f.text(263,390,'Included finality fields',F,16)
f.save('Goldfish live confirmation and the full-set conflict veto determine safe confirmation. That gate constrains frozen finality choices, whose included fields drive chain-state outcomes. Full-set heads also feed stabilization, whose anchor root constrains the Goldfish head walk.')

f=Fig('expiry-merge','One-slot memory and proposer view merge',350)
xs=[25,270,515]
for x,t,c in zip(xs,['Slot s−1','Slot s','Slot s+1'],[GR,G,P]):
 f.rect(x,20,220,48,c);f.text(x+110,50,t,c,18,True,'middle')
f.line(245,44,265,44);f.line(490,44,510,44)
f.text(30,103,'Older votes: s−2',GR,17,True);f.text(30,128,'Ignored on entry to s',GR);f.line(30,137,220,137,R,False)
f.text(278,103,'Score with votes s−1',G,17,True);f.text(278,128,'Fresh committee view')
f.text(523,103,'Score with votes s',P,17,True);f.text(523,128,'Not accumulated history')
f.line(30,186,730,186,GR,False)
for x,l in [(45,'25%: vote'),(310,'75%: cutoff'),(630,'0%: proposal')]:
 f.line(x,178,x,194,GR,False);f.text(x,219,l,GR,15,False,'middle' if x>60 else 'start')
f.text(35,258,'Receivers freeze ordinary wire intake',G,16,True)
f.path('M310 235 L310 285 L610 285 L610 235',P)
f.text(335,277,'Next proposer keeps collecting',P,16)
f.text(35,326,'Next proposal carries votes → receivers merge evidence before voting.',K,16)
f.save('Old votes expire as scoring weight, while proposer view merge helps reconcile recent evidence. The ordinary wire cutoff is 75%; it is separate from the 50% confirmation snapshot. Alignment remains conditional on delivery and proposer assumptions.')

f=Fig('confirmation-tree','Frozen seats support every ancestor',305)
for x,y,x2,y2 in [(80,95,220,95),(280,95,410,95),(470,95,600,95),(280,105,410,220)]:f.line(x,y,x2,y2,G)
f.node(55,95,'F',F,sub='Finalized')
f.node(250,95,'A',G,sub='100 support')
f.node(440,95,'B',G,sub='75 support')
f.node(630,95,'C',G,sub='60 support')
f.node(440,220,'D',GR,sub='25 support')
f.text(552,52,'60 votes name C',G,16)
f.text(357,52,'15 name B',G,16)
f.text(23,190,'Frozen electorate: 100 seats',K,17,True)
f.text(23,218,'Strict majority: > 50',G,17,True)
f.text(23,283,'A, B and C pass; the delayed-confirmation candidate reaches C.',G,16)
f.save('Sixty frozen seats name C, fifteen name B, and twenty-five name D. Subtree support propagates upward: A=100, B=75, C=60, D=25. The strict majority of 100 reaches C; this is a local snapshot calculation.')

f=Fig('confirmation-thresholds','A large observed majority can miss fast confirmation',285)
start=38;scale=680/512
f.text(38,30,'400 timely seats; 380 support the same block',K,18,True)
for y,title,den,thr,c in [(90,'Delayed available confirmation',400,200,G),(185,'Fast confirmation',512,384,F)]:
 f.text(start,y-22,title,c,17,True)
 f.rect(start,y,680,27,GR,fill='#eeeeee')
 f.rect(start,y,380*scale,27,c,fill=c)
 if den==400:f.rect(start+400*scale,y,(512-400)*scale,27,GR,fill='white',dash=True)
 xx=start+thr*scale;f.line(xx,y-7,xx,y+35,R,False)
 f.text(xx,y+58,('> 200 of 400' if den==400 else '≥ 384 of 512'),R,16,False,'middle')
 f.text(716,y+19,('PASS' if den==400 else 'FAIL'),c,16,True,'end')
f.text(38,278,'380 / 400 = 95% observed support; 380 < 384 full-committee seats.',K,16)
f.save('The same 380 supporting seats pass the delayed relative-majority threshold among 400 timely seats, but fail the immediate absolute threshold of 384 out of all 512 seats. The delayed rule first runs in the following slot.')

f=Fig('live-history','Recovery uses a live candidate while preserving a record',315)
f.line(80,142,220,84,G);f.line(80,142,220,220,P)
f.node(50,142,'F',F);f.node(250,84,'A',G);f.node(250,220,'B',P)
f.text(320,48,'Before healing',G,17,True);f.text(320,76,'Live available confirmation: A');f.text(320,103,'Historical confirmation: A')
f.line(470,119,470,172,GR)
f.text(320,203,'After a recovered live view selects B',P,17,True)
f.text(320,232,'Live available confirmation: B');f.text(320,259,'Historical confirmation: A')
f.text(22,306,'Persistent records do not reconcile incompatible confirmations.',R,17,True)
f.save('When recovery changes the live confirmed branch from A to B, the ordinary historical record retains A. Historical persistence is not a safety proof; the code also has a defensive reset for unknown or finalized-conflicting historical roots.')

f=Fig('grades','Positive selection and a conflict veto answer different questions',315)
f.line(100,125,270,75,G);f.line(100,125,270,235,R)
f.node(70,125,'F',F);f.node(300,75,'A',G,sub='40 / 60');f.node(300,235,'B',R,sub='20 / 60')
f.text(420,55,'G1 enters A',G,19,True);f.text(420,85,'3 × 40 ≥ 2 × 60');f.text(420,114,'Exactly two thirds is enough.')
f.text(420,205,'A is NOT G0-clear',R,19,True);f.text(420,235,'Conflicting B: 3 × 20 = 60');f.text(420,264,'One-third opposition vetoes.')
f.text(22,308,'D = 60 is usable live head weight, not automatically all active stake.',GR,16)
f.save('In one live view with D=60, G1 selects A with forty votes, yet twenty conflicting B votes veto G0 clearance. Selection and clearance are different predicates; neither arithmetic result establishes cross-node agreement by itself.')

f=Fig('safe-confirmation','Safe confirmation walks back past substantial opposition',380)
for a,b in [(70,225),(285,425),(485,625)]:f.line(a,90,b,90,G)
f.line(285,101,425,225,R)
f.node(40,90,'F',F);f.node(255,90,'A',T,sub='SAFE');f.node(455,90,'B',G);f.node(655,90,'C',G,sub='60 live heads')
f.node(455,225,'X',R,sub='30 live heads')
f.text(24,193,'Starting floor = F',F,17,True)
f.text(24,226,'D = 90',K,17,True)
f.path('M655 151 L700 151 L700 290 L255 290 L255 151',T)
f.text(470,318,'Walk back: C → B → A',T,16,False,'middle')
f.text(24,359,'X conflicts with B and C, but extends A. With no other veto, safe = A.',K,16)
f.save('The live available-confirmed head is C, but thirty of ninety usable full-set heads support X. X vetoes B and C at the one-third boundary; A is compatible with X. With floor F and no other qualifying opposition, the safe-confirmed head is A.')

f=Fig('tsq-timeline','TSQ separates frozen positive support from later equivocation evidence',430)
# Equal horizontal distances for the two quarter-slot windows.
f.text(165,30,'Last slot of round r−1',T,16,True)
f.text(487,30,'First slot of round r',P,16,True)
for x,l in [(250,'75% · F'),(450,'0% · P'),(650,'25% · A')]:
 f.line(x,66,x,373,GR,False,True);f.text(x,58,l,T if x==250 else P if x==450 else F,17,True,'middle')
for y,l,c in [(124,'Receiver',T),(224,'Proposer',P),(324,'Receiver',F)]:
 f.text(20,y+5,l,c,17,True);f.line(145,y,723,y,GR,False)
f.dot(250,124,T,7);f.text(155,95,'Freeze F',T,16,True)
f.line(259,134,442,214,T);f.text(275,95,'Signed messages',T,15);f.text(275,117,'+ dependencies',T,15)
f.dot(450,224,P,7);f.text(464,208,'Pin tree / weights / floor',P,15)
f.line(458,234,642,314,P);f.text(510,246,'Proposal + relay',P,15)
f.dot(650,324,F,7);f.text(462,355,'Count F ∩ U; recheck live state',F,15)
f.line(250,391,450,391,T,False);f.line(450,391,650,391,P,False)
f.text(350,417,'L / 4',T,16,True,'middle');f.text(550,417,'L / 4',P,16,True,'middle')
f.save('Freeze at 75% of the preceding last slot; pin before the new proposal at 0%; act at 25% of the first slot. Timely dissemination and validation must fit both quarter-slot windows. New relay cannot add a signer missing from F, but equivocation evidence can remove support.')

f=Fig('nested-locks','Different TSQ locks can lead to the same proposal',385)
for a,b in [(65,220),(280,410),(470,620)]:f.line(a,70,b,70,T)
for x,l,c in [(35,'F',F),(250,'A',T),(440,'B',T),(650,'P',P)]:f.node(x,70,l,c)
f.text(250,121,'Y lock',T,16,True,'middle');f.text(440,121,'X lock',T,16,True,'middle');f.text(650,121,'Shared head',P,16,True,'middle')
f.text(22,171,'Ten equal-balance voters; q = 7. Votes 1–8 name B; 9–10 name A.',K,16)
f.text(22,215,'Frozen receiver X',T,17,True);f.text(260,215,'Voters 1–7 → A: 7, B: 7 → lock B')
f.text(22,250,'Frozen receiver Y',T,17,True);f.text(260,250,'Voters 1–6, 9 → A: 7, B: 6 → lock A')
f.text(22,285,'Proposer at pin',P,17,True);f.text(260,285,'Voters 1–10 → A: 10, B: 8 → build P on B')
f.rect(20,312,720,62,P)
f.text(34,336,'Alignment requires timely P, usable locks, a viable admitted proposal,',P,16)
f.text(34,360,'and compatibility with both receivers’ live confirmed prefixes.',P,16)
f.save('X locks B while Y locks A; relaying votes 7–8 does not upgrade Y’s frozen support. A timely eligible P built on B can align their heads despite different locks, provided the live-state and confirmed-prefix proposal guards pass.')

f=Fig('height-outcomes','Target support is a subset of distinct height-progress support',425)
f.rect(20,18,720,94,F)
f.text(35,44,'Current-height progress markers Mₕ',F,18,True)
f.rect(35,59,355,37,G);f.text(46,84,'Target voters Tₕ: also mark progress',G,16,True)
f.text(415,84,'+ other timeout voters',F,16)
f.text(20,151,'At a due outcome: count included distinct validators; q = 43 of 64.',K,16)
f.rect(20,178,218,91,G);f.text(34,206,'43 target voters',G,17,True);f.text(34,234,'Tₕ = 43; Mₕ = 43')
f.rect(271,178,218,91,F);f.text(285,206,'30 target + 15 other',F,17,True);f.text(285,234,'Tₕ = 30; Mₕ = 45')
f.rect(522,178,218,91,GR);f.text(536,206,'25 target + 15 other',GR,17,True);f.text(536,234,'Tₕ = 25; Mₕ = 40')
for x,c in [(129,G),(380,F),(631,GR)]:f.line(x,269,x,308,c)
f.text(129,338,'Justify + advance',G,17,True,'middle');f.text(380,338,'Advance only',F,17,True,'middle');f.text(631,338,'Stay at height h',GR,17,True,'middle')
f.text(20,386,'Check enabled justification first. A voter contributes once to Mₕ.',K,16)
f.text(20,412,'Rounds continue while h stays open; these are not elapsed-time certificates.',GR,16)
f.save('A target vote sets both target and progress markers; a timeout sets progress only. With q=43, the three examples justify and advance, advance without justification, or stay at h. The justification branch assumes an ordinary justifiable height; independently available finality is handled first.')

f=Fig('viability','One-height slack filters eligibility, not vote weight',345)
f.text(22,28,'Frontier height = 12 → viable-leaf threshold = 11',F,18,True)
f.line(85,151,265,81,G);f.line(85,151,265,251,R)
f.line(325,81,505,81,G);f.line(325,251,505,251,R)
f.node(55,151,'F',F);f.node(295,81,'A',G,sub='ancestor retained');f.node(535,81,'A₁',G,sub='state-height 12')
f.node(295,251,'B',R,dash=True);f.node(535,251,'B₁',R,sub='best leaf: height 9',dash=True)
f.text(638,87,'Viable',G,17,True);f.text(638,257,'Excluded',R,17,True)
f.text(370,185,'Height 11 could also qualify.',G,16)
f.text(22,330,'G0 can still inspect finalized-compatible opposition on excluded branches.',T,16)
f.save('With frontier twelve, a leaf needs state-height at least eleven. An ancestor remains eligible when it leads to a qualifying leaf, while a branch ending at nine is excluded from ordinary head selection. This filter does not erase its live conflict evidence from G0.')

f=Fig('partition-healing','Availability can split while full-set progress waits',455)
f.text(20,27,'64 equal-balance validators; fixed full-set quorum q = 43',K,18,True)
f.rect(20,48,343,130,GR);f.text(35,77,'32 / 32 partition',GR,18,True)
for x,l in [(100,'32'),(277,'32')]:f.node(x,114,l,GR)
f.text(36,162,'Neither side alone reaches 43.',GR,16)
f.rect(397,48,343,130,F);f.text(412,77,'48 / 16 partition',F,18,True)
f.node(478,114,'48',F);f.node(654,114,'16',GR)
f.text(412,162,'48 can form a quorum if eligible.',F,16)
f.text(20,213,'Committee-level available suffixes may diverge on both sides.',G,16)
f.line(380,228,380,260,GR)
f.text(380,287,'Communication resumes',K,18,True,'middle')
f.line(80,319,680,319,GR,False)
for x,l,c in [(80,'Evidence',G),(280,'Live views',T),(480,'TSQ round',P),(680,'Finality',F)]:
 f.dot(x,319,c,6);f.text(x,348,l,c,16,True,'middle')
f.text(20,386,'Conditional path: common dependencies, compatible floors / committees,',K,16)
f.text(20,411,'usable confirmation, timely proposer relay, and eligible included votes.',K,16)
f.text(20,442,'Restored delivery alone does not prove convergence or a healing bound.',R,16,True)
f.save('At 32/32, neither isolated side supplies q=43; at 48/16, the larger side can supply a quorum only with eligible compatible votes and inclusion. Healing exposes a conditional recovery path, not a guarantee: the executable profile still leaves composition and recovery proof obligations open.')

(ROOT/'figure-manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n')
print('Generated',len(manifest),'SVG figures in',OUT)
