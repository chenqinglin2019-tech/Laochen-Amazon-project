"""Behavioral design-reference precedence and cache regressions."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lc_reference_design import prepare_design_briefs, validate_units, _finished_design_tags


class DesignReferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        source = self.base/'截图.png'
        source.write_bytes(b'reviewed external design source')
        self.unit = {'id':'example','external_path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                     'unit_region_norm':[.5,0,.5,1],'recipe':'photo_sidebar','reviewed':True,'product_evidence':False,
                     'generation':{'visual_composition':'macro on left'},'layout':{'headline_tone':'sans'}}
        self.atlas = self.base/'atlas.json'
        self.atlas.write_text(json.dumps({'schema_version':1,'asset_policy':'external_regions_only','units':[self.unit]}))
        self.manifest = {'design_reference_units_path':str(self.atlas), 'jobs':[
            {'id':'hero','kind':'secondary','text_mode':'model_native','design_reference_id':'example'},
            {'id':'other','kind':'secondary','layout':{'version':2}}]}

    def tearDown(self): self.tmp.cleanup()

    def test_explicit_reference_compiles_and_caches(self):
        first = prepare_design_briefs(self.manifest,self.base,{'hero'})
        self.assertEqual(first['changed'],['hero'])
        self.assertEqual(self.manifest['jobs'][0]['design_brief']['generation']['visual_composition'],'macro on left')
        snapshot = copy.deepcopy(self.manifest)
        self.assertEqual(prepare_design_briefs(self.manifest,self.base,{'hero'})['cached'],['hero'])
        self.assertEqual(snapshot,self.manifest)
        self.assertNotIn('design_brief',self.manifest['jobs'][1])

    def test_changed_reference_does_not_claim_valid_design(self):
        prepare_design_briefs(self.manifest,self.base,{'hero'})
        Path(self.unit['external_path']).write_bytes(b'different screenshot')
        self.assertEqual(prepare_design_briefs(self.manifest,self.base,{'hero'})['needs_input'],['hero'])
        self.assertEqual(self.manifest['jobs'][0]['design_resolution']['status'],'needs_input')
        self.assertTrue(self.manifest['jobs'][0]['design_resolution']['required'])

    def test_comparison_board_tags_never_become_poster_structure(self):
        tags = ['catalog_left_lifestyle_right', 'product_kit_left_action_right',
                'product_kit_left_lifestyle_right', 'before_after_board',
                'action_closeup', 'detail_callout', 'photo_sidebar']
        self.assertEqual(_finished_design_tags(tags), ['action_closeup','detail_callout','photo_sidebar'])

    def test_optional_generic_reference_does_not_require_missing_input(self):
        del self.manifest['jobs'][0]['design_reference_id']
        with patch('lc_reference_design._generic_unit',return_value=None):
            prepare_design_briefs(self.manifest,self.base,{'hero'})
        self.assertFalse(self.manifest['jobs'][0]['design_resolution']['required'])

    def test_override_only_changes_chosen_job(self):
        prepare_design_briefs(self.manifest,self.base,{'hero'})
        untouched=copy.deepcopy(self.manifest['jobs'][1])
        self.manifest['jobs'][0]['design_overrides']={'layout':{'headline_tone':'serif'}}
        prepare_design_briefs(self.manifest,self.base,{'hero'})
        self.assertEqual(self.manifest['jobs'][0]['design_brief']['layout']['headline_tone'],'serif')
        self.assertEqual(self.manifest['jobs'][1],untouched)

    def test_confirmed_brief_precedes_generic(self):
        job=self.manifest['jobs'][0]
        del job['design_reference_id']
        job['design_brief']={'version':1,'generation':{'setting':'tool workbench'},'layout':{}}
        before=copy.deepcopy(job)
        with patch('lc_reference_design._generic_unit',side_effect=AssertionError('must not reselect')):
            prepare_design_briefs(self.manifest,self.base,{'hero'})
        self.assertEqual(job,before)

    def test_unrelated_category_does_not_use_rabbit_atlas(self):
        job=self.manifest['jobs'][0]
        del job['design_reference_id']
        unit={**self.unit,'id':'tool-unit','generation':{'setting':'workbench'}}
        with patch('lc_reference_design._generic_unit',return_value=unit) as generic:
            prepare_design_briefs(self.manifest,self.base,{'hero'})
        generic.assert_called_once()
        self.assertEqual(job['design_brief']['reference_ids'],['tool-unit'])

    def test_rejects_invalid_region_and_product_evidence(self):
        bad=copy.deepcopy(self.unit); bad['unit_region_norm']=[.8,0,.5,1];bad['product_evidence']=True
        self.assertGreaterEqual(len(validate_units({'schema_version':1,'asset_policy':'external_regions_only','units':[bad]})),2)


if __name__=='__main__': unittest.main()
