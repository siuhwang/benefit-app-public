from pathlib import Path
import datetime,json,re
root=Path(__file__).resolve().parents[1]
feed=json.loads((root/'data/feed.json').read_text());approved=json.loads((root/'data/approved-programs.json').read_text())
assert set(feed)=={'version','source','generatedAt','scannedCount','totalRssCount','notices'}
assert feed['version']==1 and feed['source']=='https://www.k-startup.go.kr/web/contents/rss/bizpbanc-ongoing.do'
age=(datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(feed['generatedAt'])).total_seconds();assert -300<=age<=86400
keys={'id','title','url','field','region','stages','target','organization','organizationType','startDate','endDate','endTime','publishedAt','sourceLicense','categories','supportKind','summary'}
seen=set()
for n in feed['notices']:
    assert set(n)==keys and n['id'] in approved and n['id'] not in seen
    assert n['url']=='https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&id='+n['id']
    assert n['sourceLicense']=='KOGL1' and n['categories']==approved[n['id']]['categories']
    assert n['summary']==approved[n['id']]['summary'] and n['supportKind']==approved[n['id']]['supportKind']
    assert all(isinstance(v,str)and len(v)<=400 for k,v in n.items()if k not in ['categories','endTime'])
    assert all(n[k] for k in ['title','field','region','stages','organization','supportKind','summary'])
    assert datetime.date.fromisoformat(n['startDate'])<=datetime.date.fromisoformat(n['endDate'])
    assert n['endTime'] is None or re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d',n['endTime'])
    seen.add(n['id'])
assert len(seen)<=len(approved) and feed['totalRssCount']>=feed['scannedCount']>=len(seen)
print(json.dumps({'validatedPrograms':len(seen),'freshAgeSeconds':round(age),'privateFields':0}))
