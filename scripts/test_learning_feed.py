import unittest,importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location('learning',Path(__file__).with_name('refresh-learning-feed.py'));E=importlib.util.module_from_spec(spec);spec.loader.exec_module(E)
def card(i,eligibility='1996.12.31 까지 출생한 자',income='소득무관'):
 return f'''<a href="javascript:fn_vc_Move('Notice{i}==');" class="slide_card"><div>모집중</div><div>전북특별자치도</div><div>2026 AI·디지털 평생교육이용권 4차</div><div>신청기간</div><div>10.14(수) 10시 ~ 10.23(금) 18시</div><div>지원금액</div><div>350,000 원</div><div>발표일</div><div>10.30(금)</div><div>자격요건</div><div>{eligibility}</div><div>소득요건</div><div>{income}</div></a>'''
class FeedTests(unittest.TestCase):
 def test_fields_keep_labelword_inside_value(self):
  source=''.join(card(i,income='일반이용자 신청 당시 판정된 소득요건')for i in range(40));rows=E.parse_cards(source);self.assertEqual(rows[0]['소득요건'],'일반이용자 신청 당시 판정된 소득요건')
 def test_24_hour_rolls_to_next_day_without_changing_17_or18_closing(self):
  self.assertEqual(E.parse_period('09.15(화) 10시 ~ 09.30(수) 24시',2026)[1],'2026-10-01T00:00:00+09:00');self.assertEqual(E.parse_period('10.14(수) 10시 ~ 10.23(금) 18시',2026)[1],'2026-10-23T18:00:00+09:00')
 def test_missing_partial_duplicate_source_rejected(self):
  for source in [card(1),card(1)*40,'<html>Request Blocked</html>']:self.assertRaises(ValueError,E.parse_cards,source)
 def test_unreviewed_change_rejected_and_personal_data_fields_not_created(self):
  source=''.join(card(i)for i in range(40));a={'Notice0==':{'title':'2026 AI·디지털 평생교육이용권 4차','region':'전북특별자치도','eligibility':'1996.12.31 까지 출생한 자','income':'소득무관','amount':350000}};f=E.build_feed(source,a,'2026-10-18T00:00:00Z');self.assertEqual(len(f['notices']),1);self.assertEqual(f['notices'][0]['birthYearMax'],1996);self.assertNotIn('applicant',str(f));self.assertRaises(ValueError,E.build_feed,source.replace('1996.12.31','1997.12.31'),a,'test');self.assertRaises(ValueError,E.build_feed,source.replace('350,000 원','700,000 원'),a,'test')
 def test_new_notice_not_blindly_added(self):
  source=''.join(card(i)for i in range(40));self.assertEqual(E.build_feed(source,{},'test')['notices'],[])
if __name__=='__main__':unittest.main()
