"""Focused V3 layout regressions. Browser suite is opt-in with LC_LAYOUT_BROWSER_TEST=1."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from PIL import Image, ImageDraw
import lc_layout as layout

class GeometryTests(unittest.TestCase):
    def job(self,name='scene',canvas=None):
        job={'id':'test','kind':'listing','canvas':canvas or [2000,2000], 'layout_input':'base.png',
             'layout':{'template':name,'headline':'Made for everyday','body':'Simple details. Thoughtfully made.','items':[]}}
        if name in {'benefits','detail','dimensions','components'}:
            job['layout']['items']=[{'text':'24 cm','axis':'horizontal','image':'crop.png','target':[.5,.5],'evidence_refs':['ref']}]
        return job
    def test_all_geometry_within_canvas_and_stable_for_copy(self):
        for template in layout.TEMPLATES:
            for canvas in [[2000,2000],[2000,2600]]:
                a=self.job(template,canvas);b=copy.deepcopy(a);b['layout']['headline']='A much longer headline';b['layout']['text_color']='#ffffff'
                ga=layout.layout_geometry(a);gb=layout.layout_geometry(b)
                self.assertEqual(ga,gb)
                for box in ga['text_zones']+[ga['product_zone']]:layout._box(box,'geometry')
    def test_geometry_has_distinct_portrait_layouts(self):
        for name in layout.TEMPLATES:
            self.assertNotEqual(layout.layout_geometry(self.job(name,[2000,2000])),layout.layout_geometry(self.job(name,[2000,2600])))
    def test_no_dimension_duplicates(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);Image.new('RGB',(2000,2000),'white').save(base/'base.png');Image.new('RGB',(100,100),'white').save(base/'crop.png')
            job=self.job('dimensions');job['layout']['items']*=3
            with self.assertRaises(layout.LayoutError):layout._prepare_job({},base,job)
    def test_font_covers_cjk_arabic_latin_but_not_emoji(self):
        fonts,missing=layout._font_payload(['English Größe 清晰設計 日本語 한국어 تصميم واضح 😀'])
        self.assertEqual(len(fonts),6)
        self.assertEqual(missing,['U+1F600'])
    def test_project_path_and_input_safety(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);Image.new('RGB',(2000,2000),'white').save(base/'base.png')
            for value in ['https://example.com/x.png','../x.png','/tmp/x.png']:
                with self.assertRaises(layout.LayoutError):layout._project_file(base,value)
            for field,value in [('text_color','red;background:url(https://a)'),('direction','auto')]:
                job=self.job();job['layout'][field]=value
                with self.assertRaises(layout.LayoutError):layout._prepare_job({},base,job)
    def test_main_text_forbidden(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);Image.new('RGB',(2000,2000),'white').save(base/'base.png')
            job=self.job();job['kind']='main'
            with self.assertRaises(layout.LayoutError):layout._prepare_job({},base,job)
    def test_fingerprint_separates_metadata_and_copy(self):
        a=self.job();b=copy.deepcopy(a);b['ai_disclosure']={'synthetic_performer':True}
        self.assertEqual(layout.layout_fingerprint({},a),layout.layout_fingerprint({},b))
        b['layout']['headline']='Revised';self.assertNotEqual(layout.layout_fingerprint({},a),layout.layout_fingerprint({},b))

@unittest.skipUnless(os.environ.get('LC_LAYOUT_BROWSER_TEST')=='1','set LC_LAYOUT_BROWSER_TEST=1 for pinned Chromium suite')
class BrowserTests(unittest.TestCase):
    job = GeometryTests.job
    def test_templates_languages_and_failure_gates(self):
        out=os.environ.get('LC_LAYOUT_TEST_OUTPUT')
        temp=tempfile.TemporaryDirectory() if not out else None
        base=Path(out or temp.name);base.mkdir(parents=True,exist_ok=True)
        crop=Image.new('RGB',(450,450),'#e9e5dc');draw=ImageDraw.Draw(crop);draw.rounded_rectangle((100,40,350,410),radius=65,fill='#7f948b');crop.save(base/'crop.png')
        jobs=[]
        for name in sorted(layout.TEMPLATES):
            for width,height in [(2000,2000),(2000,2600)]:
                job=self.job(name,[width,height]);job['id']=name+('-portrait' if height>width else '-square')
                job['layout']['headline']='Everyday, elevated';job['layout']['body']='Thoughtful details. Simple living.'
                if name=='detail':job['layout']['items'][0]['text']='Fine finish'
                if name=='components':job['layout']['items'][0]['text']='Included part'
                if name=='benefits':job['layout']['items']=[{'text':'Easy to carry','icon':'leaf'},{'text':'Simple care','icon':'care'},{'text':'Everyday use','icon':'check'}]
                g=layout.layout_geometry(job);x,y,w,h=g['product_zone'];job['output_product_bbox_norm']=[x+.04,y+.025,w-.08,h-.05]
                image=Image.new('RGB',(width,height),'#fafbf9');draw=ImageDraw.Draw(image)
                px,py,pw,ph=job['output_product_bbox_norm'];draw.rounded_rectangle((int(px*width),int(py*height),int((px+pw)*width),int((py+ph)*height)),radius=90,fill='#9aaea4')
                job['layout_input']=job['id']+'.png';image.save(base/job['layout_input']);jobs.append(job)
        for language,headline,body in [('de','Für jeden Tag','Klare Details, einfach gestaltet.'),('zh-CN','让日常更轻松','清晰细节，自然质感'),('ja','毎日を心地よく','細部まで丁寧なデザイン'),('ko','매일 더 편안하게','섬세하고 간결한 디자인'),('ar','تفاصيل لحياة أسهل','تصميم بسيط للاستخدام اليومي')]:
            job=copy.deepcopy(jobs[8]);job['id']='language-'+language;job['language']=language;job['layout']={'template':'scene','headline':headline,'body':body};job.pop('output_product_bbox_norm');jobs.append(job)
        steps=copy.deepcopy(jobs[2]);steps['id']='components-steps';steps['layout']['items']=[{'text':'Open the case'},{'text':'Place the item'},{'text':'Close gently'}];jobs.append(steps)
        vertical=copy.deepcopy(jobs[6]);vertical['id']='dimensions-both';vertical['layout']['items']=[{'text':'24 cm','axis':'horizontal','evidence_refs':['ref']},{'text':'12 cm','axis':'vertical','evidence_refs':['ref']}];jobs.append(vertical)
        solid=copy.deepcopy(jobs[8]);solid['id']='scene-solid';solid['layout']['text_surface']='solid';solid['layout']['theme']='warm';jobs.append(solid)
        gradient=copy.deepcopy(jobs[8]);gradient['id']='scene-gradient';gradient['layout']['text_surface']='gradient';gradient['layout']['theme']='technical';jobs.append(gradient)
        escaped=copy.deepcopy(jobs[8]);escaped['id']='escaped-html';escaped['layout']['headline']='Literal <b> text';jobs.append(escaped)
        main=copy.deepcopy(jobs[8]);main['id']='main-no-copy';main['kind']='main';main['layout']={};jobs.append(main)
        compound=copy.deepcopy(jobs[8]);compound['id']='fail-long-word';compound['language']='de';compound['layout']['headline']='Donaudampfschifffahrtsgesellschaftskapitän';jobs.append(compound)
        overflow=copy.deepcopy(jobs[8]);overflow['id']='fail-overflow';overflow['layout']['headline']='long headline ' * 10;overflow['language']='en';jobs.append(overflow)
        protected=copy.deepcopy(jobs[8]);protected['id']='fail-protected';protected['layout']['protected_regions']=[{'bbox':[.05,.05,.9,.2],'kind':'face'}];jobs.append(protected)
        contrast=copy.deepcopy(jobs[8]);contrast['id']='fail-contrast';contrast['layout']['text_color']='#fafbf9';jobs.append(contrast)
        glyph=copy.deepcopy(jobs[8]);glyph['id']='fail-glyph';glyph['layout']['headline']='😀';jobs.append(glyph)
        result=layout.render_batch({},base,jobs)
        (base/'layout-test-report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        for job in jobs:
            answer=result[job['id']]
            if job['id'].startswith('fail-'):self.assertFalse(answer['passed'],job['id'])
            else:self.assertTrue(answer['passed'],(job['id'],[c for c in answer['checks'] if not c['passed']]))
        if temp:temp.cleanup()

if __name__=='__main__':unittest.main()
