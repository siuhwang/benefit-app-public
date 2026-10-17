"""Collect only public factual grant metadata, not people, prose or attachments."""
from pathlib import Path
import datetime,email.utils,html,json,re,time,urllib.request,xml.etree.ElementTree as E,sys
ROOT=Path(__file__).resolve().parents[1]
RSS='https://www.k-startup.go.kr/web/contents/rss/bizpbanc-ongoing.do'
UTC=datetime.timezone.utc
def clean(s):
    return re.sub(r'\s+',' ',html.unescape(html.unescape(re.sub(r'<[^>]*>',' ',s)))).strip()
def get(url):
    req=urllib.request.Request(url,headers={'User-Agent':'GrantInbox/1.0 public RSS reader','Accept':'application/rss+xml,text/html'})
    with urllib.request.urlopen(req,timeout=25) as response:
        data=response.read(1200000)
        if len(data)>=1200000:raise ValueError('Source too large')
        return data.decode('utf-8')
def parse_detail(source,item):
    if '공공누리제1유형' not in re.sub(r'\s+','',source):raise ValueError('No confirmed KOGL1 license')
    begin=source.index('<div class="bg_box">');finish=source.index('<div class="box">',begin);header=source[begin:finish]
    pairs={clean(k):clean(v) for k,v in re.findall(r'<p\s+class="tit"[^>]*>(.*?)</p>\s*<p\s+class="txt"[^>]*>(.*?)</p>',header,re.S)}
    title=re.search(r'id="scrTitle"[^>]*>.*?<h3>(.*?)</h3>',source,re.S)
    if not title:raise ValueError('No official title')
    region=pairs.get('지역','');stages=pairs.get('창업업력','');field=pairs.get('지원분야','')
    period=pairs.get('접수기간','');dates=re.findall(r'\d{4}-\d{2}-\d{2}',period)
    if len(dates)!=2 or not region or not stages or not field:raise ValueError('Incomplete structured metadata')
    start,end=dates
    for date in dates:datetime.date.fromisoformat(date)
    if end<start:raise ValueError('Reversed period')
    tm=re.search(r'\d{4}-\d{2}-\d{2}\s*~\s*\d{4}-\d{2}-\d{2}\s+(\d{2}:\d{2})',period)
    if tm:datetime.time.fromisoformat(tm.group(1))
    return {'id':item['id'],'title':clean(title.group(1)),'url':item['url'],'field':field,'region':region,'stages':stages,'target':pairs.get('대상',''),'organization':pairs.get('주관기관명',''),'organizationType':pairs.get('기관구분',''),'startDate':start,'endDate':end,'endTime':tm.group(1) if tm else None,'publishedAt':item['publishedAt'],'sourceLicense':'KOGL1'}
def main():
    rss=E.fromstring(get(RSS).strip());items=[]
    approved=json.loads((ROOT/'data/approved-programs.json').read_text())
    if len(rss.findall('./channel/item'))<1:raise ValueError('Unexpected empty RSS; preserve successful data')
    for n in rss.findall('./channel/item'):
        title=clean(n.findtext('title') or '');link=n.findtext('link') or ''
        match=re.fullmatch(r'https?://www\.k-startup\.go\.kr/web/contents/bizpbanc-ongoing\.do\?schM=view&id=(\d+)',link)
        if not match:continue
        if not re.search('지원사업|자금|사업화|사업비|R&D|연구개발|지원금|개발지원|바우처|보조금|고도화|기술지원|창업패키지',title):continue
        if re.search('융자|대출|투자|교육|특강|캠프|네트워킹|경진|입주|대관|스튜디오',title):continue
        published=email.utils.parsedate_to_datetime(n.findtext('pubDate')).astimezone(UTC).isoformat()
        items.append({'id':match.group(1),'url':link.replace('http:','https:',1),'publishedAt':published})
    items.sort(key=lambda x:x['publishedAt'],reverse=True)
    unreviewed=[i for i in items if i['id'] not in approved]
    (ROOT/'review-assets/unreviewed-rss.json').write_text(json.dumps(unreviewed,ensure_ascii=False,indent=2)+'\n')
    items=[i for i in items if i['id'] in approved]
    notices=[];failures=[];today=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date().isoformat()
    for item in items:
        try:
            cache=ROOT/'review-assets'/'source-cache';cache.mkdir(parents=True,exist_ok=True)
            old=cache/(item['id']+'.html')
            text=old.read_text() if '--from-cache' in sys.argv else get(item['url']);old.write_text(text)
            p=parse_detail(text,item)
            p.update(approved[item['id']])
            if p['endDate']>=today and not re.search('융자|대출|투자',p['field']):notices.append(p)
        except Exception as e:failures.append({'id':item['id'],'error':str(e)[:150]})
        time.sleep(.35)
    # Never replace a successful feed with a partial response.
    if failures:raise RuntimeError('Source collection incomplete: '+json.dumps(failures,ensure_ascii=False))
    checkedAt=datetime.datetime.now(UTC).isoformat()
    if '--from-cache' in sys.argv:checkedAt=json.loads((ROOT/'data/feed.json').read_text())['generatedAt']
    feed={'version':1,'source':RSS,'generatedAt':checkedAt,'scannedCount':len(items),'totalRssCount':len(rss.findall('./channel/item')),'notices':notices}
    path=ROOT/'data/feed.json';path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.json.tmp');temp.write_text(json.dumps(feed,ensure_ascii=False,indent=2)+'\n');temp.replace(path)
    print(json.dumps({'count':len(notices),'scanned':len(items),'failed':len(failures),'generatedAt':feed['generatedAt']},ensure_ascii=False))
if __name__=='__main__':main()
