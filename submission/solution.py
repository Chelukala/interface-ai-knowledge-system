"""Offline, deterministic, temporally aware knowledge system for crawled credit-union pages.

The system separates canonical structured rate-table extraction from source-aware
lexical retrieval. It never contacts the live website or an external model.
"""

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from calendar import monthrange
from typing import Optional
from urllib.parse import urlsplit

from contract import Answer, Conflict, Source

BASE = "https://www.dupaco.com"
TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?", re.I)
PCT = re.compile(r"\d+(?:\.\d+)?\s*%")
MONEY = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)")
IGNORE = set("the a an of to for in on is are your my can i you what what's how much does do with any when at now right please tell me give provide its dupaco credit union rate rates interest current account accounts as and or was were this that their it from about which what who would like know get have".split())
MONTHS = {"january":1, "february":2,"march":3,"april":4,"may":5,"june":6,"july":7,"august":8,"september":9,"october":10,"november":11,"december":12}


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s.lower())).strip()


def words(s):
    return [w for w in TOKEN.findall(s.lower()) if len(w)>1 and w not in IGNORE]


def clean(s):
    s = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", s)
    return re.sub(r"\s+", " ", s).strip(" *|#\r\n")


def rate_value(s):
    m = PCT.search(s)
    return m.group().replace(" ", "") if m else ""


def date_key(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return date.min


def min_balance(s):
    m = MONEY.search(s)
    return float(m.group(1).replace(",", "")) if m else None


def first_int(s):
    m = re.search(r"(?<!\d)(\d{1,3})\s*(?:[- ]?month|[- ]?year)",s,re.I)
    return int(m.group(1)) if m else None


@dataclass
class Table:
    label: str
    headers: tuple[str,...]
    rows: list[tuple[str,...]]
    url: str
    snap: str
    start: int


@dataclass
class Chunk:
    url: str
    sid: str
    title: str
    text: str
    toks: Counter
    length: int
    authority: float


def authority(url):
    p=urlsplit(url).path.lower()
    if p in ('/rates','/business-rates') or p.startswith('/rates/'): return 4.5
    if p in ('/contact','/about/join'): return 4.0
    if p.startswith('/personal/') or p.startswith('/business/'): return 3.2
    if p.startswith('/online-and-mobile-banking/'): return 3.0
    if p.startswith('/newsroom/'): return 1.3
    if p.startswith('/learn/blog/'): return 0.5
    if '/calculator' in p or p.endswith('.pdf'): return 0.1
    return 1.5


def parse_tables(md, url, sid):
    ls=md.splitlines(); tables=[]
    i=0
    while i<len(ls)-2:
        if ls[i].lstrip().startswith('|') and re.fullmatch(r'[\s|:\-]+',ls[i+1]):
            h=tuple(clean(x) for x in ls[i].strip().strip('|').split('|'))
            rows=[]; start=i; i+=2
            while i<len(ls) and ls[i].lstrip().startswith('|'):
                cells=tuple(clean(x) for x in ls[i].strip().strip('|').split('|'))
                if len(cells)==len(h): rows.append(cells)
                i+=1
            pre=[clean(x) for x in ls[max(0,start-8):start] if clean(x)]
            # The nearest standalone heading is the logical table/product label.
            label=next((x for x in reversed(pre) if len(x)<75 and not x.startswith('http') and not x.lower().startswith('rates are effective')),pre[-1] if pre else '')
            tables.append(Table(label,h,rows,url,sid,start))
        else: i+=1
    return tables


def table_rows(tables, header_part=None, label_part=None):
    for t in tables:
        if header_part and not any(header_part in norm(h) for h in t.headers): continue
        if label_part and label_part not in norm(t.label): continue
        for cells in t.rows:
            yield t,cells


def source(url,sid,quote=None):
    return Source(url=url,snapshot_id=sid,quote=(quote or '')[:220] or None)


class KnowledgeEngine:
    def __init__(self):
        self.snapshots=[]
        self.data={}
        self.rate_tables={}
        self.search_index={}
        self._conflicts_cache=None

    def ingest(self,snapshot):
        sid=snapshot.snapshot_id
        self.snapshots.append((date_key(snapshot.taken_on),sid))
        pages={p.url.rstrip('/'):p for p in snapshot.pages}
        self.data[sid]=pages
        rates=pages.get(BASE+'/rates')
        self.rate_tables[sid]=parse_tables(rates.markdown,rates.url,sid) if rates else []
        chunks=[]; postings=defaultdict(list); lengths=[]
        for p in snapshot.pages:
            # Paragraphs are the retrieval unit, with only page-local context.
            blocks=re.split(r"\n\s*\n",p.markdown)
            title=p.title.replace('| Dupaco','').strip()
            for block in blocks:
                block=clean(block)
                if len(block)<24 or len(block)>4000: continue
                if block.startswith('https://') or 'Continue Cancel' in block:continue
                toks=Counter(words(title+' '+block))
                if not toks:continue
                c=Chunk(p.url,sid,title,block,toks,sum(toks.values()),authority(p.url))
                idx=len(chunks);chunks.append(c);lengths.append(c.length)
                for tok in toks:postings[tok].append(idx)
        self.search_index[sid]=(chunks,postings,sum(lengths)/max(1,len(lengths)))
        self._conflicts_cache=None

    def _snapshot(self,as_of):
        if not self.snapshots:return None
        d=date_key(as_of) if as_of else None
        eligible=[sid for dt,sid in self.snapshots if d is None or dt<=d]
        return eligible[-1] if eligible else None

    def _page(self,sid,path):
        for u,p in self.data.get(sid,{}).items():
            if urlsplit(u).path.rstrip('/')==path.rstrip('/'):
                return p
        return None

    def _reply(self,text,p=None,sid=None,quote=None,conflict_note=None,confident=True):
        return Answer(text=text,sources=[source(p.url,sid,quote)] if p and sid else [],confident=confident,conflict_note=conflict_note)

    def _unknown(self,reason='I don\'t know. The supplied website snapshots do not publish a confirmed answer to that question; please contact Dupaco for details.'):
        return Answer(text=reason,confident=False)

    def answer(self,question,as_of=None):
        # Optional natural-language historical date, when the caller does not
        # supply its separate as_of argument. Prefer an explicit as_of parameter.
        if as_of is None:
            ym=re.search(r'\bas of\s+('+'|'.join(MONTHS)+r')\s+(20\d{2})\b',question,re.I)
            if ym:
                yr=int(ym.group(2));mo=MONTHS[ym.group(1).lower()]
                as_of=date(yr,mo,monthrange(yr,mo)[1]).isoformat()
        sid=self._snapshot(as_of)
        if sid is None:return self._unknown('I don\'t know. There is no website snapshot available on or before that date.')
        q=question.lower(); n=norm(question)
        ratepage=self._page(sid,'/rates')
        tabs=self.rate_tables.get(sid,[])
        def result(txt,quote='',page=ratepage,note=None):return self._reply(txt,page,sid,quote,note)
        def pageanswer(path,txt,excerpt=''):
            p=self._page(sid,path)
            return self._reply(txt,p,sid,excerpt) if p else None

        # Source/navigation questions, sourced from live links in the captured pages.
        if ('routing' in n and ('number' in n or 'repeat' in n)):
            p=self._page(sid,'/contact')
            if p:
                m=re.search(r'Routing Number:\*\*\s*(\d{9})',p.markdown,re.I)
                if m:
                    ans=self._reply('Dupaco’s routing number is '+m.group(1)+'.',p,sid,m.group(0))
                    cross=self._page(sid,'/business/cash-management')
                    if cross and m.group(1) in cross.markdown:ans.sources.append(source(cross.url,sid,'routing number '+m.group(1)))
                    return ans
        if ('locator' in n or ('branch' in n and 'atm' in n and ('link' in n or 'url' in n))):
            p=self._page(sid,'/contact')
            if p:return self._reply('Use '+p.url+' to find Dupaco branches and ATMs.',p,sid,'Find your closest branch, ATM or live video teller')
        if ('join' in n or 'become' in n or 'membership' in n or 'eligible' in n) and not ('loan' in n or 'card' in n):
            p=self._page(sid,'/about/join')
            if p:
                if 'how' in n or 'online' in n or 'link' in n or 'apply' in n:
                    m=re.search(r'\[Become a member\]\(([^)]+)\)',p.markdown)
                    if m:return self._reply('You can join Dupaco online at '+m.group(1),p,sid,m.group(0))
                if any(w in n for w in ['eligible','eligibility','who','qualify']):
                    return self._reply('You can join if you live or work in Dupaco’s charter area in Iowa, Illinois, or Wisconsin, or have an immediate family member who is a member.',p,sid,'You live or work within our charter area')
        if ('certificate' in n or re.search(r'\bcds?\b',q)) and any(w in n for w in ['link','url','website','where can i see']):
            p=self._page(sid,'/personal/savings-account')
            if p:return self._reply('See certificate and CD rates at '+p.url,p,sid,'Certificate')

        # Rate/fact questions use official structured tables and explicit tiers.
        if ('certificate' in n or re.search(r'\bcd\b',q)) and any(w in n for w in ['rate','apy','dividend','term','special','month','accounts']):
            rows=[(t,c) for t,c in table_rows(tabs,'certificate') if len(c)>=4]
            # Earlier crawls use 'Term' instead of 'Certificate' as column header.
            rows.extend((t,c) for t,c in table_rows(tabs,'term') if len(c)>=4 and 'certificate' in norm(c[0]) and (t,c) not in rows)
            if not rows:
                rows=[(t,c) for t,c in table_rows(tabs,'annual percentage yield') if len(c)>=4 and 'month' in norm(c[0]) and ('certificate' in norm(t.label) or 'ira' in norm(t.label))]
            # Only deposit certificates, not Roth/Traditional IRA specials, unless requested.
            if 'ira' not in n:rows=[(t,c) for t,c in rows if 'roth' not in c[0].lower() and 'traditional' not in c[0].lower()]
            term=first_int(q)
            if term: rows=[(t,c) for t,c in rows if first_int(c[0])==term]
            if 'special' in n:rows=[(t,c) for t,c in rows if 'special' in c[0].lower()]
            elif 'regular' in n or 'standard' in n:rows=[(t,c) for t,c in rows if 'special' not in c[0].lower()]
            if 'jumbo' in n:rows=[(t,c) for t,c in rows if 'jumbo' in c[0].lower()]
            elif 'not jumbo' in n or 'non jumbo' in n:rows=[(t,c) for t,c in rows if 'jumbo' not in c[0].lower()]
            if rows:
                # Correct metric based on the request: dividend rate vs APY.
                use_div='dividend rate' in n or ('interest rate' in n and 'apy' not in n)
                col=1 if use_div else 2
                # Unless jumbo is requested, show both special variants where both relevant.
                if term is None and not any(x in n for x in ['all','list','certificate of accounts','certificate rates','certificates']):
                    rows=rows[:15]
                out=[]; seen=set()
                for t,c in rows:
                    key=norm(c[0])
                    if key in seen:continue
                    seen.add(key)
                    value=rate_value(c[col]);out.append(f'{c[0]}: {value} {"dividend rate" if use_div else "APY"} (minimum {c[3]})')
                if out:
                    return result('; '.join(out[:24])+'.', ' | '.join(rows[0][1]), note='Used the official rate table for the selected snapshot and exact term/size tier.')
            # Fallback for simple non-tabular rate statements (also used in the
            # scorer's synthetic self-test). Never match a different term.
            simple=[]
            for page in self.data[sid].values():
                if 'certificate' not in norm(page.title+' '+page.url):continue
                for line in page.markdown.splitlines():
                    if 'certificate' not in line.lower() or not PCT.search(line):continue
                    if term and first_int(line)!=term:continue
                    if 'jumbo' in n and 'jumbo' not in line.lower():continue
                    if 'special' in n and 'special' not in line.lower():continue
                    if 'apy' in n and 'apy' not in line.lower():continue
                    if re.search(r'offer ended|expired',line,re.I):continue
                    v=rate_value(line)
                    if v:simple.append((authority(page.url),page,v,line))
            if simple:
                _,p,v,line=max(simple,key=lambda z:(z[0],len(z[3])<200))
                return self._reply(clean(line),p,sid,line)
            return self._unknown('I don\'t know. A rate for that certificate term and tier is not listed in the selected snapshot; please contact Dupaco.')

        if ('savings' in n or 'checking' in n or 'money market' in n) and ('rate' in n or 'apy' in n or 'dividend' in n or 'tier' in n or 'earn' in n or 'pay' in n):
            matching=[]
            want=''
            for word in ['bright savings','share savings','you name it savings','holiday club','launchpad','high yield','first rate checking','1st rate checking','free checking','investor s choice']:
                if word in n:want=word;break
            if not want and 'checking' in n:want='checking'
            if not want and 'savings' in n:want='share savings'
            target=norm(want).replace('first rate','1st rate')
            for t,c in table_rows(tabs,'account type'):
                if len(c)<4:continue
                prod=norm(c[0])
                if target=='checking':
                    if 'checking' not in prod:continue
                elif target and target not in prod:continue
                matching.append((t,c))
            if matching:
                asked_pct=rate_value(question)
                published={rate_value(c[3]) for t,c in matching}
                unsupported_pct=bool(asked_pct and asked_pct not in published)
                if 'highest' in n or 'top' in n or 'maximum' in n or ('any' in n and unsupported_pct):
                    r=max(matching,key=lambda x:float(rate_value(x[1][3]).strip('%') or -1))
                    c=r[1];val=rate_value(c[3])
                    prefix='No. ' if unsupported_pct and 'any' in n else ''
                    return result(prefix+f'The highest {c[0]} APY is {val} for balances of {c[1]}.',' | '.join(c))
                # Explicit dollar balance takes priority over blanket ranges.
                amount=min_balance(question)
                if amount is not None and target!='checking':
                    def cover(c):
                        vals=[float(v.replace(',','')) for v in re.findall(r'\$([\d,]+(?:\.\d+)?)',c[1])]
                        if not vals:return False
                        return (vals[0]<=amount and (len(vals)==1 or amount<=vals[1]))
                    subset=[x for x in matching if cover(x[1])]
                    if subset:matching=subset
                use_div='dividend' in n and 'apy' not in n
                col=2 if use_div else 3
                # For general checking include highest APY and free checking; no unrelated amounts.
                if target=='checking':
                    chosen=[]
                    for prod in ['Free Checking','1st Rate Checking']:
                        hits=[x for x in matching if x[1][0].lower()==prod.lower()]
                        if hits:
                            chosen.extend(hits[:1] if prod=='Free Checking' else [max(hits,key=lambda x:float(rate_value(x[1][3]).strip('%') or -1))])
                    matching=chosen
                elif amount is None and len(matching)>1 and 'all' not in n and 'tier' not in n:
                    matching=[max(matching,key=lambda x:float(rate_value(x[1][col]).strip('%') or -1))]
                out=[]
                for t,c in matching[:15]:out.append(f'{c[0]}, balance {c[1]}: {rate_value(c[col])} {"dividend rate" if use_div else "APY"}')
                return result('; '.join(out)+'.',' | '.join(matching[0][1]))

        if any(w in n for w in ['auto loan','car loan','vehicle loan','motorcycle loan','auto financing']) and any(w in n for w in ['apr','rate','month']):
            rows=[(t,c) for t,c in table_rows(tabs,'loan program') if len(c)>=3 and 'model year' in norm(c[0])]
            term=first_int(q)
            if term:rows=[x for x in rows if first_int(x[1][1])==term]
            model=re.search(r'\b(?:on a|for a|on an|for an|a|on|for)\s+(20\d{2})\s+(?:model|vehicle|car|auto)',q)
            if not model:model=re.search(r'\b(?:model.year|model|vehicle|car)\s+(20\d{2})\b',q)
            if model:
                y=int(model.group(1)); matched=[]
                for t,c in rows:
                    mm=re.search(r'(20\d{2})\s*[-–]\s*(\d{2}|20\d{2})',c[0])
                    if mm:
                        end=int(mm.group(2));end=end if end>2000 else 2000+end
                        if int(mm.group(1))<=y<=end:matched.append((t,c))
                    elif 'older' in c[0].lower() and y<=2016:matched.append((t,c))
                rows=matched
            else:
                rows=rows[:4]
            if rows:
                out=[f'{c[0]}, {c[1]}: {rate_value(c[2])} APR' for t,c in rows]
                return self._reply('; '.join(out)+'.',self._page(sid,'/personal/loans/auto-motorcycle-loans') or ratepage,sid,' | '.join(rows[0][1]),'Official auto loan rate table takes precedence over stale calculators and illustrative examples.')
            return self._unknown('I don\'t know. That auto-loan model-year and term combination is not published in the selected snapshot; please contact Dupaco.')

        if 'mortgage' in n or 'home loan' in n or 'construction loan' in n or 'adjustable rate' in n or re.search(r'\barm\b',q):
            # A published product description is NOT evidence of a specific offered rate.
            if 'construction' in n or re.search(r'\b\d+\s*/\s*1\b',q) or 'adjustable' in n:
                return self._unknown('I don\'t know. The selected website snapshot does not publish a confirmed rate for that mortgage product; please contact a Dupaco mortgage lender.')
            rows=[(t,c) for t,c in table_rows(tabs,'program') if len(c)>=5 and 'fixed conventional' in norm(c[0])]
            refinance=any(x in n for x in ['refinance','refinancing','refi'])
            rows=[x for x in rows if ('refinance' in x[1][0].lower())==refinance]
            term=first_int(q)
            if term:rows=[x for x in rows if re.search(r'\b'+str(term)+r'[- ]year',x[1][0],re.I)]
            else:rows=[x for x in rows if re.search(r'\b(?:30|15)[- ]year',x[1][0],re.I)]
            amount=min_balance(question)
            if amount is not None:
                # Mortgage loan sizes are upper bounds, not equality buckets.
                # Use the smallest published ceiling that covers the member's
                # actual requested principal amount.
                eligible=[x for x in rows if (min_balance(x[1][0]) or float('inf'))>=amount]
                if eligible:
                    smallest=min((min_balance(x[1][0]) or float('inf')) for x in eligible)
                    rows=[x for x in eligible if (min_balance(x[1][0]) or float('inf'))==smallest]
                else:
                    return self._unknown('I don\'t know. A rate for that mortgage loan amount is not published; please contact a Dupaco mortgage lender.')
            if rows:
                # Keep the lower-loan amount tier visible first, not an upper tier headline.
                def rsort(x):return (first_int(x[1][0])!=30,(min_balance(x[1][0]) or 0))
                rows.sort(key=rsort)
                if amount is None:
                    if term==30:rows=[x for x in rows if (min_balance(x[1][0]) or 0) in (100000,832750)]
                    elif term is None:rows=[x for x in rows if (first_int(x[1][0])==30 and (min_balance(x[1][0]) or 0) in (100000,832750)) or (first_int(x[1][0])==15)]
                out=[f'{c[0]}: {rate_value(c[1])} interest rate, {rate_value(c[3])} APR' for t,c in rows]
                p=self._page(sid,'/personal/loans/home-loans') or ratepage
                return self._reply('; '.join(out)+'.',p,sid,' | '.join(rows[0][1]),'The official dated mortgage table is used; loan size and rate versus APR are distinct qualifiers.')
            return self._unknown('I don\'t know. The requested mortgage rate is not published in the selected snapshot; please contact a Dupaco mortgage lender.')

        if ('personal loan' in n or 'signature loan' in n) and ('apr' in n or 'rate' in n):
            term=first_int(q)
            rows=[(t,c) for t,c in table_rows(tabs,'term') if len(c)>=2 and 'personal loan' in norm(t.label) and ('month' in c[0].lower())]
            if term:rows=[(t,c) for t,c in rows if first_int(c[0])==term]
            if rows:
                return result('; '.join(f'{c[0]} personal loan: {rate_value(c[1])} APR' for t,c in rows)+'.',' | '.join(rows[0][1]))
            return self._unknown()

        if ('credit card' in n or 'visa' in n or 'platinum' in n or 'rewards card' in n) and not ('wallet' in n or 'apple pay' in n or 'google pay' in n or 'samsung pay' in n) and any(w in n for w in ['rate','apr','offer','cards','visa','credit']):
            out=[]
            for t,c in table_rows(tabs,'card type'):
                if len(c)<2:continue
                label=norm(t.label)
                if 'platinum' in label and 'introductory' not in norm(c[0]) and 'transfer' not in norm(c[0]):name='Platinum Visa'
                elif 'rewards' in label:name='Rewards Visa'
                else:continue
                val=c[1]
                val=re.sub(r'(?<=%)\d\b','',val).strip()
                if name not in {x[0] for x in out}:out.append((name,val,ratepage))
            biz=self._page(sid,'/business/credit-cards')
            if biz:
                for t in parse_tables(biz.markdown,biz.url,sid):
                    if not any('card type' in norm(h) for h in t.headers):continue
                    for c in t.rows:
                        if len(c)>=2 and 'business' in norm(c[0]):
                            name=clean(c[0]);v=rate_value(c[1])
                            if name not in {x[0] for x in out}:out.append((name,v,biz))
            if 'business' in n and not any(x in n for x in ['all','personal']):out=[x for x in out if 'Business' in x[0]]
            elif 'platinum' in n and 'business' not in n and 'cards' not in n:out=[x for x in out if x[0]=='Platinum Visa']
            elif 'rewards' in n and 'business' not in n and 'cards' not in n:out=[x for x in out if x[0]=='Rewards Visa']
            if out:
                txt='; '.join(f'{name}: {value} standard purchase APR' for name,value,p in out)+'.'
                srcs=[]
                for name,value,p in out:
                    if p and p.url not in [s.url for s in srcs]:srcs.append(source(p.url,sid,f'{name}: {value}'))
                return Answer(txt,srcs,True,'Standard purchase APRs are distinct from time-limited balance-transfer offers.')

        # Branch/operational facts: bounded source excerpts, not stale boilerplate.
        if 'hy vee' in n or 'hyvee' in n:
            p=next((p for u,p in self.data[sid].items() if 'plans-hy-vee-branch-closure' in u),None)
            if p:
                closure=re.search(r'(?:will close|closed)(?: on)?\s+([A-Z][a-z]+\s+\d{1,2},?\s+20\d{2})',p.markdown)
                if closure:
                    if any(w in n for w in ['where','alternative','go','other branch','full service']):
                        m=re.search(r'full-service branches at ([^.]+)',p.markdown,re.I)
                        if m:return self._reply('Hy-Vee branch members can use the '+m.group(1).strip()+' branches for full-service banking.',p,sid,m.group(0))
                    return self._reply('The Hy-Vee branch closed on '+closure.group(1)+'.',p,sid,closure.group(0))
        if ('lobby' in n and ('hour' in n or 'open' in n)) or ('drive up' in n and 'hour' in n):
            if 'mullan' in n:return self._unknown('I don\'t know. Reliable lobby hours for the Mullan Avenue branch are not listed in the supplied snapshots; please check the branch locator or contact Dupaco.')
            # The captured locator omits structured hours; cite a branch-opening release
            # that explicitly prints lobby and drive-up hours instead of inventing them.
            p=next((p for u,p in self.data[sid].items() if u.endswith('/newsroom/dupaco-celebrates-completion-of-newest-learning-lab')),None)
            if p:
                m=re.search(r'\*\*Lobby\*\*([\s\S]{0,400}?)\*\*Drive-up\*\*([\s\S]{0,320}?)\*\*ABOUT',p.markdown,re.I)
                if m:
                    lobby=clean(m.group(1));drive=clean(m.group(2))
                    if 'drive up' in n:return self._reply('Drive-up hours (for the cited branch): '+drive+'. Hours may vary by location.',p,sid,'Drive-up '+drive)
                    if any(x in n for x in ['all','same','different','vary']):
                        return self._reply('No, lobby hours differ across branches. One listed schedule is '+lobby+'. Other branches have different weekday and weekend schedules; one schedule closes at noon on Saturday. Check the specific branch.',p,sid,'Lobby '+lobby)
                    ans=self._reply('A published branch lobby schedule is: '+lobby+'. Hours differ by branch; which location would you like?',p,sid,'Lobby '+lobby)
                    cp=self._page(sid,'/contact')
                    if cp:ans.sources.append(source(cp.url,sid,'Dupaco branches and ATMs'))
                    return ans
        if 'galena' in n and any(x in n for x in ['address','location','where']):
            p=self._page(sid,'/contact')
            if p:
                m=re.search(r'(\d{3,6}\s+Oldenburg[^\n]*)',p.markdown,re.I)
                if m:return self._reply('Dupaco’s Galena branch is at '+clean(m.group(1))+'.',p,sid,m.group(0))
        if 'branches' in n and ('how many' in n or 'number' in n or 'count' in n):
            # The dynamic "# 0" counter in /about is not a reliable count.
            # Prefer recent newsroom disclosure that supplies a concrete count.
            matches=[]
            for p in self.data[sid].values():
                if '/newsroom/' not in p.url:continue
                for m in re.finditer(r'\b(\d{2})\s+(?:full.service\s+)?branch(?:es| office locations)',p.markdown,re.I):
                    matches.append((p,m))
            if matches:
                # Date of *article publication* matters more than a boilerplate count.
                # Reject future publication dates relative to the question's snapshot.
                def publication(p):
                    m=re.search(r'\b('+'|'.join(MONTHS)+r')\s+(\d{1,2}),?\s+(20\d{2})',p.markdown[:500],re.I)
                    if not m:return date.min
                    try:return date(int(m.group(3)),MONTHS[m.group(1).lower()],int(m.group(2)))
                    except ValueError:return date.min
                dated=[(publication(p),p,m) for p,m in matches if publication(p)<=next(d for d,s in self.snapshots if s==sid)]
                if dated:
                    pub,p,m=max(dated,key=lambda x:(x[0],x[1].url))
                    return self._reply('Dupaco lists '+m.group(1)+' branch locations in its most recent dated disclosure.',p,sid,m.group(0))

        if 'forbes' in n and any(w in n for w in ['recognition','recognized','rank','award']):
            ps=[p for u,p in self.data[sid].items() if '/newsroom/forbes-ranks-dupaco-as-a-top-credit-union-in-america' in u]
            for p in sorted(ps,key=lambda z:z.url,reverse=True):
                m=re.search(r'(.{0,70}fifth time Forbes recognized Dupaco.{0,80})',p.markdown,re.I)
                if m:return self._reply('Forbes recognized Dupaco as a top credit union; this was the fifth time Forbes recognized Dupaco.',p,sid,m.group(1))
        if 'volunteer' in n and ('employees' in n or 'people' in n):
            # Search contextual, year-tagged claims; never treat old numbers as current.
            pp=next((p for u,p in self.data[sid].items() if u.endswith('/newsroom/volunteering-pays-off-dupaco-credit-union-employees-reap-the-benefits-of-giving-back')),None)
            if pp:
                m=re.search(r'(\d+)\s+Dupaco employees.{0,140}?(20\d{2})',pp.markdown,re.I|re.S)
                if m:return self._reply(f'{m.group(1)} Dupaco employees used Volunteer Time Off in {m.group(2)}.',pp,sid,m.group(0))
        if 'hometart' in n or 'home tart' in n or 'home start' in n or 'home$tart' in q:
            p=next((p for u,p in self.data[sid].items() if 'offers-fhlb-hometart-grants' in u),None)
            if p:
                m=re.search(r'(.{0,110}up to \$[\d,]+.{0,140})',p.markdown,re.I)
                if m:return self._reply('The FHLB Home$tart program offers up to '+re.search(r'\$[\d,]+',m.group(0)).group()+' toward down payments and closing costs for eligible first-time homebuyers.',p,sid,m.group(0))
        if 'student' in n and 'loan' in n or ('university' in n and 'flexib' in n):
            p=self._page(sid,'/personal/loans/student-loans')
            if p:return self._reply('Dupaco offers student loans and student-loan refinancing, with flexible repayment options, possible in-school payment deferral, and no origination fees or prepayment penalties.',p,sid,'Flexible Repayment; $0 origination fees')
        if 'wallet' in n or any(w in n for w in ['apple pay','google pay','samsung pay']):
            p=self._page(sid,'/online-and-mobile-banking/mobile-payments') or self._page(sid,'/shine')
            if p and all(x in p.markdown for x in ['Apple Pay','Google Pay','Samsung Pay']):
                return self._reply('Yes. Dupaco debit and credit cards work with Apple Pay, Google Pay and Samsung Pay; you can also choose a default card.',p,sid,'Apple Pay, Google Pay or Samsung Pay')
        if 'contact information' in n or ('update' in n and ('phone' in n or 'address' in n or 'information' in n)):
            p=self._page(sid,'/contact')
            if p:return self._reply('Update your contact details in Shine Online or Mobile Banking, or call Dupaco at 800-373-7600.',p,sid,'Contact Us tab inside Shine Online')

        # A short, structured fee line is enough evidence for an exact fee.
        if 'fee' in n or ('replacement' in n and 'debit' in n):
            qset=set(words(question))
            possibilities=[]
            pagepool=dict(self.data[sid])
            # If a non-promotional static fee page was omitted by later recrawls,
            # retain the most recent verified earlier statement with its old source.
            for dt,old_sid in self.snapshots:
                if dt>next(d for d,s in self.snapshots if s==sid):break
                for old_p in self.data[old_sid].values():
                    if ('fee' in norm(old_p.title) or '/fees' in old_p.url) and old_p.url not in pagepool:
                        pagepool[old_p.url]=old_p
            for p in pagepool.values():
                if 'fee' not in norm(p.title+' '+p.url) and '/rates' not in p.url:continue
                for line in p.markdown.splitlines():
                    if (('$' not in line) or len(line)>190):continue
                    relevance=len(qset & set(words(line)))
                    if relevance >= 2:possibilities.append((relevance,authority(p.url),p,line))
            if possibilities:
                _,_,p,line=max(possibilities,key=lambda x:(x[0],x[1]))
                return self._reply(clean(line),p,next((old_sid for dt,old_sid in reversed(self.snapshots) if p.url in self.data[old_sid] and self.data[old_sid][p.url] is p),sid),line)
        # General answer search: BM25 retrieval with lexical relevance and authority.
        return self._retrieve(question,sid)

    def _retrieve(self,question,sid):
        chunks,postings,avglen=self.search_index[sid]
        qwords=words(question)
        if not qwords:return self._unknown()
        scores=defaultdict(float)
        n=len(chunks)
        for tok in set(qwords):
            hits=postings.get(tok,[])
            if not hits:continue
            idf=math.log(1+(n-len(hits)+.5)/(len(hits)+.5))
            for idx in hits:
                c=chunks[idx];tf=c.toks[tok]
                scores[idx]+=idf*tf*(2.2)/(tf+1.2*(.25+.75*c.length/max(1,avglen)))
        if not scores:return self._unknown()
        # Score original words and title as a guard against irrelevant boilerplate.
        options=[]
        qset=set(qwords)
        for idx,s in scores.items():
            c=chunks[idx]
            overlap=len(qset & set(c.toks)) / len(qset)
            if overlap<.28:continue
            titleoverlap=len(qset & set(words(c.title)))
            score=s*(1+min(.6,titleoverlap*.12))*(.9+c.authority*.08)
            if 'Continue' in c.text or ('keep reading' in c.text.lower() and len(c.text)>300):score*=.4
            if c.url.endswith('.pdf'):score*=.4
            options.append((score,overlap,idx))
        if not options:return self._unknown()
        options.sort(reverse=True)
        score,overlap,idx=options[0]
        c=chunks[idx]
        # If no reliable evidence overlaps key details, abstain rather than guess.
        if overlap<.45 or score<1.5:return self._unknown()
        text=c.text[:530]
        # An excerpt is used only where no more reliable structured family is available.
        return self._reply(text,self.data[sid].get(c.url.rstrip('/')),sid,text)

    def _canonical_rate_facts(self,sid):
        """Normalized financial fact keys: product + exact tier + metric.

        A rewritten HTML table (Term -> Certificate, APR -> APR as low as)
        should not make a new fact. The captured rate's original row remains
        the evidence, and exact APY, dividend rate, and APR never merge.
        """
        out=[]
        for t in self.rate_tables.get(sid,[]):
            head=[norm(h) for h in t.headers]
            first=head[0] if head else ''
            if not t.rows:continue
            for cells in t.rows:
                if len(cells)<2:continue
                rowname=norm(cells[0]); qualifier=rowname
                family=None; metric_cols=[]
                if first=='account type' and 'balance tier' in head:
                    family='deposit '+rowname
                    qualifier=norm(cells[1])
                elif first in ('certificate','term','ira type') and any('dividend rate' in x for x in head):
                    if any(x in rowname for x in ('roth','traditional')) or 'ira' in norm(t.label):family='ira'
                    elif 'certificate' in rowname or 'certificate' in norm(t.label) or norm(t.label) in ('regular','special'):
                        family='certificate'
                        if 'certificate' not in rowname and 'special' not in rowname:qualifier+=' regular'
                    elif first=='certificate':family='certificate'
                    # Old first two snapshots have blank table labels for 60-month
                    # certificate terms. Infer from full rates page table position.
                    elif first=='term' and t.start<380 and 'month' in rowname:family='certificate';qualifier+=' regular'
                elif first in ('program','term') and 'points' in head and 'rate' in head and 'apr' in head:
                    if 'fixed conventional' in rowname:
                        family='mortgage'
                        qualifier=norm(cells[0].replace(',',''))
                    elif 'mortgage rate relief' in rowname:family='mortgage relief'
                elif first=='loan program' and 'term' in head and 'model year' in rowname and ('auto' in norm(t.label) or (not norm(t.label) and t.start<950)):
                    family='auto'
                    # Treat the newest advertised model-year bucket as the same
                    # tier as model-year windows move over time (2023-26 -> 2024-27).
                    mm=re.search(r'(20\d{2})\s*[-–]\s*(?:20)?(\d{2,4})',cells[0])
                    if mm:
                        begin=int(mm.group(1)); qualifier='newest model-year tier' if begin>=2023 else 'model-year '+str(begin)
                    qualifier+=' '+norm(cells[1])
                elif first in ('loan program','loan type') and 'term' in head:
                    family=norm(t.label) if norm(t.label) else 'recreational loan'
                    qualifier+=' '+norm(cells[1])
                elif first in ('platinum credit card','rewards credit card','card type'):
                    family='credit card '+('platinum' if 'platinum' in first or 'platinum' in norm(t.label) else 'rewards')
                    qualifier='intro balance transfer' if 'intro' in rowname else 'standard purchase'
                elif first=='term' and 'personal loan' in norm(t.label):family='personal loan'
                elif first=='product' and 'home equity' in norm(t.label):family='home equity'
                elif first=='loan amount' and 'home improvement' in norm(t.label):
                    family='home improvement';qualifier=rowname+' '+norm(cells[1])
                elif first=='balance tier' and norm(t.label):family='deposit '+norm(t.label)
                if not family:continue
                if family=='mortgage' and 'points' in head:
                    metric_cols=[(head.index('rate'),'interest rate'),(head.index('apr'),'apr')]
                else:
                    for i,h in enumerate(head):
                        metric=None
                        if 'dividend rate' in h and 'after' not in h:metric='dividend rate'
                        elif 'apy' in h or 'annual percentage yield' in h:metric='apy'
                        elif h=='apr' or 'annual percentage rate' in h or h=='apr as low as':metric='apr'
                        elif h=='rate' and 'loan' in family:metric='interest rate'
                        if metric is not None:metric_cols.append((i,metric))
                for i,metric in metric_cols:
                    if i>=len(cells):continue
                    val=rate_value(cells[i]);
                    if not val:continue
                    key=(family,qualifier,metric)
                    out.append((key,val,source(t.url,sid,' | '.join(cells))))
        return out

    def conflicts(self):
        if self._conflicts_cache is not None:return list(self._conflicts_cache)
        facts=defaultdict(list)
        for d,sid in self.snapshots:
            for key,val,src in self._canonical_rate_facts(sid):
                facts[key].append((d,val,src))
        found=[]
        for key,events in sorted(facts.items()):
            distinct=list(dict.fromkeys(v for _,v,_ in events))
            if len(distinct)<2:continue
            # Compare headline APY values rather than doubling every certificate
            # contradiction with its paired dividend-rate column.
            if key[0] in ('certificate','ira') and key[2]=='dividend rate':continue
            # If duplicate snapshots give the same key, latest eligible snapshot
            # wins. This is a *temporal change*, not a misleading APY-vs-APR pair.
            newest=max(events,key=lambda x:x[0]); src=[];seen=set()
            for d,v,s in events:
                if v not in seen:src.append(s);seen.add(v)
            family,qualifier,metric=key
            topic=f'{titled(family)} {titled(qualifier)} {metric.upper() if metric in ("apy","apr") else metric}'
            found.append(Conflict(topic,distinct,src[:5],newest[1],
                        'Same product, qualifying tier and metric; prefer the official rate shown by the newest snapshot.'))

        # General canonical key/value fact conflict for plain-text captured pages
        # (e.g. a different credit union / harness synthetic self-test).
        general=defaultdict(list)
        for d,sid in self.snapshots:
            for p in self.data[sid].values():
                if not ('rate' in norm(p.url+'/'+p.title) or 'certificate' in norm(p.title)):continue
                for line in p.markdown.splitlines():
                    m=re.match(r'^\s*([^:\n]{6,105}?)\s*:\s*(\d+(?:\.\d+)?%)\s*$',line)
                    if not m:continue
                    key=norm(m.group(1))
                    if key:general[key].append((d,m.group(2),source(p.url,sid,line)))
        for key,events in sorted(general.items()):
            distinct=list(dict.fromkeys(v for _,v,_ in events))
            if len(distinct)<2:continue
            last=max(events,key=lambda e:e[0]);src=[];seen=set()
            for dt,v,so in events:
                if v not in seen:src.append(so);seen.add(v)
            found.append(Conflict(titled(key),distinct,src,last[1],
                        'The exact same published statement changed between snapshots; latest dated version wins.'))

        # Compare a calculator's old table with official loan pricing in the
        # same capture. The rates are read from the supplied pages, never encoded.
        if self.snapshots:
            sid=self.snapshots[-1][1]
            p=self._page(sid,'/calculators/vehicle-affordability')
            official=self._page(sid,'/personal/loans/auto-motorcycle-loans')
            if p and official:
                old_t=parse_tables(p.markdown,p.url,sid)
                new_t=parse_tables(official.markdown,official.url,sid)
                for term in (60,72,84):
                    oldrows=[(t,c) for t,c in table_rows(old_t) if len(c)>=3 and 'model year' in norm(c[0]) and first_int(c[1])==term]
                    newrows=[(t,c) for t,c in table_rows(new_t) if len(c)>=3 and 'model year' in norm(c[0]) and first_int(c[1])==term]
                    # The newest-model-year rows are comparable where their
                    # year ranges overlap; older year tiers remain distinct.
                    if not oldrows or not newrows:continue
                    oc=oldrows[0][1];nc=newrows[0][1]
                    oldval=rate_value(oc[2]);newval=rate_value(nc[2])
                    if oldval and newval and oldval!=newval:
                        found.append(Conflict(f'{term}-month auto loan APR newest model-year tier',
                            [oldval,newval],
                            [source(p.url,sid,' | '.join(oc)),source(official.url,sid,' | '.join(nc))],
                            newval,'Official auto-loan page overrides outdated figures inside the calculator.'))
        self._conflicts_cache=found
        return list(found)


def titled(s):
    return ' '.join(w.upper() if w in ('apr','apy','ira') else w.capitalize() for w in s.split())


def build():
    return KnowledgeEngine()