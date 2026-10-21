# -*- coding: utf-8 -*-
"""Inject REAL PowerPoint slide transitions and entrance (fade) animations
into a pptxgenjs-generated .pptx by editing the slide XML directly (no tree
round-trip, so namespaces are preserved). Targets = shapes whose cNvPr name
starts with 'anim'; they build on one click, staggered 'after previous'.
"""
import sys, re, zipfile, shutil, os

SRC, DST = sys.argv[1], sys.argv[2]
SLOW = {1, 6, 12, 19}          # title, dividers, closing -> slower fade

CNVPR = re.compile(r'<p:cNvPr\b([^>]*?)/?>')
IDRE = re.compile(r'\bid="(\d+)"')
NMRE = re.compile(r'\bname="(anim\d+)"')

def transition(n):
    spd = "slow" if n in SLOW else "med"
    return f'<p:transition spd="{spd}"><p:fade/></p:transition>'

def timing(spids):
    # one click gate, first item on click, the rest after previous (300ms stagger)
    items = []
    nid = 5
    for k, spid in enumerate(spids):
        e = nid; nid += 3
        node = "clickEffect" if k == 0 else "afterEffect"
        delay = "0" if k == 0 else "300"
        items.append(
            f'<p:par><p:cTn id="{e}" presetID="10" presetClass="entr" presetSubtype="0" '
            f'fill="hold" grpId="0" nodeType="{node}">'
            f'<p:stCondLst><p:cond delay="{delay}"/></p:stCondLst><p:childTnLst>'
            f'<p:set><p:cBhvr><p:cTn id="{e+1}" dur="1" fill="hold">'
            f'<p:stCondLst><p:cond delay="0"/></p:stCondLst></p:cTn>'
            f'<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl>'
            f'<p:attrNameLst><p:attrName>style.visibility</p:attrName></p:attrNameLst></p:cBhvr>'
            f'<p:to><p:strVal val="visible"/></p:to></p:set>'
            f'<p:animEffect transition="in" filter="fade"><p:cBhvr>'
            f'<p:cTn id="{e+2}" dur="500"/><p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl>'
            f'</p:cBhvr></p:animEffect>'
            f'</p:childTnLst></p:cTn></p:par>')
    inner = "".join(items)
    return (
        '<p:timing><p:tnLst><p:par>'
        '<p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst>'
        '<p:seq concurrent="1" nextAc="seek">'
        '<p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>'
        '<p:par><p:cTn id="3" fill="hold"><p:stCondLst><p:cond delay="indefinite"/></p:stCondLst>'
        '<p:childTnLst><p:par><p:cTn id="4" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst>'
        f'<p:childTnLst>{inner}</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par>'
        '</p:childTnLst></p:cTn>'
        '<p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst>'
        '<p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst>'
        '</p:seq></p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>')

def anim_targets(xml):
    found = []
    for m in CNVPR.finditer(xml):
        attrs = m.group(1)
        idm, nm = IDRE.search(attrs), NMRE.search(attrs)
        if idm and nm:
            found.append((int(nm.group(1)[4:]), int(idm.group(1))))
    found.sort(key=lambda t: t[0])
    return [sp for _, sp in found]

def process(xml, n):
    block = transition(n)
    spids = anim_targets(xml)
    if spids:
        block += timing(spids)
    # insert after </p:clrMapOvr> (schema: cSld, clrMapOvr, transition, timing)
    if "</p:clrMapOvr>" in xml:
        xml = xml.replace("</p:clrMapOvr>", "</p:clrMapOvr>" + block, 1)
    else:
        xml = xml.replace("</p:cSld>", "</p:cSld>" + block, 1)
    return xml, len(spids)

zin = zipfile.ZipFile(SRC, "r")
items = zin.infolist()
data = {i.filename: zin.read(i.filename) for i in items}
zin.close()

slide_re = re.compile(r"ppt/slides/slide(\d+)\.xml$")
total_anim = 0; nslides = 0
for name in list(data):
    m = slide_re.match(name)
    if not m:
        continue
    nslides += 1
    n = int(m.group(1))
    xml = data[name].decode("utf-8")
    xml, na = process(xml, n)
    data[name] = xml.encode("utf-8")
    total_anim += na

zout = zipfile.ZipFile(DST, "w", zipfile.ZIP_DEFLATED)
for i in items:
    zout.writestr(i, data[i.filename])
zout.close()
print(f"slides={nslides} transitions={nslides} animated_shapes={total_anim} -> {DST}")
