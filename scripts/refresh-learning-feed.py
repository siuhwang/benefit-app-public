"""Refresh reviewed factual metadata from the official public lifelong-learning portal."""
from html.parser import HTMLParser
from pathlib import Path
import datetime,json,re,sys,urllib.request,hashlib
ROOT=Path(__file__).resolve().parents[1]
SOURCE='https://www.lllcard.kr/main'
LIST='https://www.lllcard.kr/main/vcReq/vcList.do'
KST=datetime.timezone(datetime.timedelta(hours=9));UTC=datetime.timezone.utc
LABELS=('신청기간','지원금액','발표일','자격요건','소득요건')
class Cards(HTMLParser):
 def __init__(self):super().__init__();self.current=None;self.rows=[]
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if tag=='a' and (a.get('href')or'').startswith('javascript:fn_vc_Move('):
   if self.current is not None:raise ValueError('Unexpected nested card')
   self.current={'href':a['href'],'tokens':[]}
 def handle_data(self,data):
  if self.current is not None and data.strip():self.current['tokens'].append(re.sub(r'\s+',' ',data.strip()))
 def handle_endtag(self,tag):
  if tag=='a' and self.current is not None:self.rows.append(self.current);self.current=None
def parse_cards(source):
 parser=Cards();parser.feed(source);out=[]
 for r in parser.rows:
  t=r['tokens'];m=re.fullmatch(r"javascript:fn_vc_Move\('([A-Za-z0-9+/=]+)'\);",r['href'])
  if not m or len(t)<12:raise ValueError('Malformed official card')
  fields={}
  for i,v in enumerate(t):
   if v in LABELS and i+1<len(t):
    if v in fields:raise ValueError('Duplicate field label')
    fields[v]=t[i+1]
  if set(fields)!=set(LABELS):raise ValueError('Missing public metadata field')
  out.append({'id':m.group(1),'status':t[0],'region':t[1],'title':t[2],**fields})
 if len(out)<40 or len({x['id']for x in out})!=len(out):raise ValueError('Unexpected incomplete source; preserve last success')
 return out
def parse_period(text,year):
 parts=re.findall(r'(\d{2})\.(\d{2})\([^)]*\)\s*(\d{1,2})시(?:\s*(\d{1,2})분)?',text)
 if len(parts)!=2:raise ValueError('Unrecognized official time')
 result=[]
 for month,day,hour,minute in parts:
  hour=int(hour);minute=int(minute or 0)
  if hour==24 and minute==0:dt=datetime.datetime(year,int(month),int(day),tzinfo=KST)+datetime.timedelta(days=1)
  else:dt=datetime.datetime(year,int(month),int(day),hour,minute,tzinfo=KST)
  result.append(dt.isoformat())
 if result[0]>=result[1]:raise ValueError('Reversed application period')
 return result
def build_feed(source,approved,observed):
 rows=parse_cards(source);notices=[];seen=set()
 for x in rows:
  a=approved.get(x['id'])
  if not a:continue
  seen.add(x['id'])
  for k,f in [('title','title'),('region','region'),('eligibility','자격요건'),('income','소득요건')]:
   if x[f]!=a[k]:raise ValueError('Reviewed criterion changed; preserve last success')
  amount=int(re.sub(r'[^0-9]','',x['지원금액']))
  if amount!=a['amount']:raise ValueError('Reviewed amount changed')
  year=int(re.match(r'^(20\d{2}) ',x['title']).group(1))
  if year!=2026:raise ValueError('Unreviewed policy year')
  start,end=parse_period(x['신청기간'],year)
  excellent='(우수이용자)'in x['title'];kind='excellent'if excellent else'new';typ='digital'if'AI·디지털'in x['title']else'senior'if'노인'in x['title']else'general'
  age=None;useDate=None;used=None
  if excellent:
   m=re.fullmatch(r'\((\d{4}\.\d{2}\.\d{2}) 기준\) 당해년도 선정자로 이용권 지급금액 중 기준금액\(([0-9,]+) 원\) 이상 사용자',x['자격요건'])
   if not m or x['소득요건']!='일반이용자 신청 당시 판정된 소득요건':raise ValueError('Unrecognized excellent eligibility')
   useDate=m.group(1).replace('.','-');datetime.date.fromisoformat(useDate);used=int(m.group(2).replace(',',''))
  else:
   m=re.fullmatch(r'(\d{4})\.12\.31 까지 출생한 자',x['자격요건'])
   if not m or x['소득요건']!='소득무관':raise ValueError('Unreviewed new-applicant criteria')
   age=int(m.group(1))
  notices.append({'id':x['id'],'region':x['region'],'title':x['title'],'kind':kind,'type':typ,'amount':amount,'startAt':start,'endAt':end,'birthYearMax':age,'usageCutoff':useDate,'minimumUsed':used,'income':x['소득요건'],'officialListUrl':LIST})
 if seen!=set(approved):raise ValueError('Reviewed official notices missing; preserve last success')
 return {'version':1,'source':SOURCE,'generatedAt':observed,'sourceSha256':hashlib.sha256(source.encode()).hexdigest(),'scannedCount':len(rows),'reviewedCount':len(notices),'notices':notices}
def main():
 approved=json.loads((ROOT/'data/approved-learning.json').read_text())
 if '--from-file'in sys.argv:
  source=Path(sys.argv[sys.argv.index('--from-file')+1]).read_text();feed=build_feed(source,approved,'fixture-only');print(json.dumps({'scanned':feed['scannedCount'],'reviewed':feed['reviewedCount'],'written':False}));return
 req=urllib.request.Request(SOURCE,headers={'User-Agent':'LearningAid/1.0 public factual metadata reader','Accept':'text/html'})
 with urllib.request.urlopen(req,timeout=30)as response:
  b=response.read(1200000)
  if response.status!=200 or len(b)>=1200000:raise ValueError('Official source unavailable or too large')
 observed=datetime.datetime.now(UTC).isoformat();feed=build_feed(b.decode('utf-8'),approved,observed)
 path=ROOT/'data/learning-feed.json';temp=path.with_suffix('.json.tmp');temp.write_text(json.dumps(feed,ensure_ascii=False,indent=2)+'\n');temp.replace(path)
 print(json.dumps({'scanned':feed['scannedCount'],'reviewed':feed['reviewedCount'],'generatedAt':observed}))
if __name__=='__main__':main()
