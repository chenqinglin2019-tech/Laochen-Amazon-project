"""r5d3 fixes from the r5d2 real run: public web cards read from their own address before judgment (and closed
when only the user could answer), comparison sessions in small batches, a refused module answer run again inside the
same review pass, the chain summary bound to its modules by the program, not_selected originals and triage prose
left out of the final-review packets, and the chief draft taking the claims table one reviewer gave."""
import json
import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

os.environ.setdefault("LC_IPR_OFFLINE_TESTS", "1")

FOCUS = {'review_focus_revision': 'review-focus-v1'}
NEEDS_USER = {'candidate_id': 'W1', 'decision': 'needs_info', 'reason': '卡片只有标题',
              'missing_information': ['网页的具体内容'], 'reopen_conditions': ['候选公开内容变化时重新分流'],
              'basis_summary': '需补材料', 'comparison': {'candidate_content': 't', 'product_content': 'p',
              'relationship': 'r', 'missing_fact_effect': 'e', 'completion_condition': 'c', 'existing_material_review': 'm'},
              'next_actions': [{'kind': 'user_information', 'purpose': '补充网页', 'question': '请提供网页原文'}]}
WEB_CARD = {'right_type': 'unknown', 'candidate_nature': 'web_result', 'title': 'Guardian SoftShox Chinstrap',
            'url': 'https://guardiansports.com/chinstrap/'}


class CardPageTests(unittest.TestCase):
    def test_excerpt_is_whole_when_short_and_keeps_the_relevant_lines_when_long(self):
        import review_focus as rf
        task = {'query_terms': [{'value': 'lid securing strap'}]}
        text, complete, total = rf.excerpt('Title\n\nA short page.', task)
        self.assertEqual((text, complete, total), ('Title\nA short page.', True, len('Title\nA short page.')))
        lines = ['Intro line %d about football helmets.' % i for i in range(60)]
        lines[50] = 'This strap keeps the lid secure on the pot.'
        lines[55] = 'The plaintiff alleged design infringement in court.'
        lines += ['filler ' * 40] * 40
        body = '\n'.join(lines)
        text, complete, total = rf.excerpt(body, task)
        self.assertFalse(complete)
        self.assertEqual(total, len('\n'.join(' '.join(line.split()) for line in lines)))   # whitespace-normalized
        self.assertLessEqual(len(text), rf.EXCERPT_LIMIT)
        self.assertTrue(text.startswith('Intro line 0'))
        self.assertIn('This strap keeps the lid secure', text)
        self.assertIn('plaintiff alleged design infringement', text)
        self.assertNotIn('filler', text.split('\n…\n', 1)[1])
        self.assertEqual(rf.excerpt(body, task), (text, complete, total))      # deterministic

    def test_html_and_pdf_page_text(self):
        import review_focus as rf
        html = b'<html><head><style>x{}</style><script>var a=1</script></head><body><h1>Chinstrap</h1><p>Helmet</p></body></html>'
        self.assertEqual(rf.page_text(html, 'html'), 'Chinstrap\nHelmet')

    def test_unreadable_page_is_remembered_and_never_fetched_twice(self):
        import review_focus as rf
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            card = {**WEB_CARD, 'candidate_id': 'W1', 'image_url': '', 'thumbnail_url': ''}
            (root / 'normalized-candidates.json').write_text(json.dumps({'enforcement': [card]}), encoding='utf-8')
            (root / 'evidence.json').write_text(json.dumps({'collections': {'sources': []}}), encoding='utf-8')
            calls = []

            def fetch(url):
                calls.append(url)
                raise ValueError('PAGE_HTTP_404')
            entries = [{'candidate_id': 'W1'}]
            summary = rf.prefetch_card_pages(root, entries, fetch=fetch)
            self.assertEqual(summary, {'fetched': 0, 'failed': [{'candidate_id': 'W1', 'reason': 'ValueError:PAGE_HTTP_404'}]})
            self.assertEqual(rf.prefetch_card_pages(root, entries, fetch=fetch), {'fetched': 0, 'failed': []})
            self.assertEqual(calls, [card['url']])
            view = rf.card_page_view(root, {}, {'collections': {'sources': []}}, card)
            self.assertEqual(view, {'unavailable': 'ValueError:PAGE_HTTP_404'})
            # a patent card or a card with an image is not a text-only web lead: never fetched
            (root / 'normalized-candidates.json').write_text(json.dumps({'patents': [
                {'candidate_id': 'P1', 'right_type': 'patent', 'url': 'https://x.example/p'}]}), encoding='utf-8')
            self.assertEqual(rf.prefetch_card_pages(root, [{'candidate_id': 'P1'}], fetch=fetch)['fetched'], 0)
            self.assertEqual(len(calls), 1)

    def test_only_a_user_question_about_a_public_web_card_is_closed(self):
        import review_focus as rf
        closed = rf.close_public_text_card(deepcopy(NEEDS_USER), WEB_CARD)
        self.assertEqual(closed['decision'], 'not_selected')
        self.assertNotIn('next_actions', closed)
        self.assertNotIn('missing_fact_effect', closed['comparison'])
        self.assertIn('用户无法补充', closed['comparison']['difference'])
        self.assertTrue(closed['comparison']['applicability_limit'])
        self.assertIn('补得：网页的具体内容', closed['reopen_conditions'])
        self.assertIn(rf.PUBLIC_TEXT_CARD_REOPEN, closed['reopen_conditions'])
        read = rf.close_public_text_card(deepcopy(NEEDS_USER), {**WEB_CARD, 'page_excerpt': 'helmet'})
        self.assertIn('程序取回的网页正文', read['comparison']['difference'])
        source_action = deepcopy(NEEDS_USER)
        source_action['next_actions'] = [{'kind': 'source_lookup', 'purpose': 'p'}]
        self.assertEqual(rf.close_public_text_card(source_action, WEB_CARD)['decision'], 'needs_info')
        self.assertEqual(rf.close_public_text_card(deepcopy(NEEDS_USER), {**WEB_CARD, 'right_type': 'patent'})['decision'],
                         'needs_info')
        self.assertEqual(rf.close_public_text_card(deepcopy(NEEDS_USER), {**WEB_CARD, 'publication_number': 'US1'})['decision'],
                         'needs_info')

    def test_text_prompt_names_the_page_only_for_review_focus_packets(self):
        import text_triage_host as host
        packet = {'schema': 'IPR-TEXT-TRIAGE/1.0', 'product': {}, 'objects': [], 'directions': [], 'facts': [],
                  'units': [], 'followup_contract': {}, 'core_focus': 'core-focus-v1'}
        self.assertNotIn('page_excerpt', host.prompt(packet))
        self.assertIn('page_excerpt', host.prompt({**packet, 'review_focus': 'review-focus-v1'}))


class SchedulingTests(unittest.TestCase):
    def test_comparison_sessions_hold_two_candidates(self):
        import comparison_host
        from visual_triage_host import batches
        self.assertEqual(comparison_host.BATCH_CANDIDATES, 2)
        self.assertGreater(comparison_host.SESSION_SECONDS, 240)
        entries = [{'candidate_id': 'C%d' % i} for i in range(6)]
        self.assertEqual([len(batch) for batch in batches(entries, comparison_host.BATCH_CANDIDATES)], [2, 2, 2])

    def test_in_run_retry_needs_allowance_time_and_a_retry_left(self):
        from module_review import in_run_retry_allowed
        now = 1000.0
        self.assertTrue(in_run_retry_allowed(now + 700, now, 1, [455.0], [1]))
        self.assertFalse(in_run_retry_allowed(now + 500, now, 1, [455.0], [1]))     # no room for the summaries
        self.assertFalse(in_run_retry_allowed(now + 700, now, 1, [455.0], [2]))     # slot already retried
        self.assertFalse(in_run_retry_allowed(now + 700, now, None, [455.0], [1]))  # task without a retry allowance
        self.assertFalse(in_run_retry_allowed(None, now, 1, [455.0], [1]))
        self.assertFalse(in_run_retry_allowed(now + 900, now, 1, [455.0, 800.0], [1, 1]))


class SummaryBindingTests(unittest.TestCase):
    RAW = {'reviewer': 'ipr-module-chain-1', 'assessments': [], 'future_applications': [], 'enforcement_signals': [],
           'coverage_confidence_cap': '高', 'coverage_confidence_reasoning': '依据完整',
           'final_review_statement': {'overall': '极高', 'scope': '美国', 'limitations': '有界检索'}}

    def test_review_focus_summary_is_bound_by_the_program(self):
        import module_review as mr
        modules = [{'module_id': 'technical', 'judgment': {'assessments': []}}]
        good = [__import__('common').sha256_json(row) for row in modules]
        miscopied = dict(self.RAW, module_review_digests=[good[0][:40] + good[0][42:]])
        mr._validate_summary_judgment(dict(self.RAW), modules, FOCUS)
        mr._validate_summary_judgment(miscopied, modules, FOCUS)
        with self.assertRaises(mr.ModuleJudgmentError):
            mr._validate_summary_judgment(miscopied, modules, {})            # older tasks keep the echo contract
        mr._validate_summary_judgment(dict(self.RAW, module_review_digests=good), modules, {})
        with self.assertRaises(mr.ModuleJudgmentError):
            mr._validate_summary_judgment(dict(self.RAW, assessments=[{'x': 1}]), modules, FOCUS)

    def test_summary_prompt_asks_for_digests_only_on_older_tasks(self):
        import module_review as mr
        packet = {'task': {'task_id': 'T'}, 'chain_id': '1', 'modules': [{'module_id': 'technical'}]}
        self.assertIn('module_review_digests严格照抄', mr.summary_prompt(packet))
        focused = mr.summary_prompt({**packet, 'task': {'task_id': 'T', **FOCUS}})
        self.assertNotIn('module_review_digests', focused)


class PacketDietTests(unittest.TestCase):
    def source(self):
        early = {'annotation_id': 'A0', 'candidate_id': 'W1', 'scenario_id': 's', 'jurisdiction': 'UNLOCATED',
                 'right_type': 'unknown', 'decision': 'needs_info', 'annotated_at': '2026-10-12T08:58:11Z', 'reason': '仅标题'}
        late = {'annotation_id': 'A1', 'candidate_id': 'W1', 'scenario_id': 's', 'jurisdiction': 'UNLOCATED',
                'right_type': 'unknown', 'decision': 'not_selected', 'annotated_at': '2026-10-12T09:22:47Z',
                'reason': '网页是头盔下颏带', 'reviewer': 'Codex 主审', 'evidence_refs': ['EV-C', 'EV-P'],
                'comparison': {'candidate_content': '卡片' * 200, 'product_content': '产品描述' * 200,
                               'relationship': '无关', 'difference': '用途不同', 'applicability_limit': '仅此网页'}}
        page = {'evidence_id': 'EV-P', 'provider': 'public_source', 'operation': 'retained_document',
                'kind': 'published_document', 'path': '/run/raw/W1.html', 'sha256': 'a' * 64, 'bytes': 10,
                'source_url': 'https://guardiansports.com/chinstrap/', 'right_type': 'unknown',
                'payload': {'candidate_id': 'W1', 'path': '/run/raw/W1.html', 'sha256': 'a' * 64}}
        return {'task': {'task_id': 'T', **FOCUS},
                'candidates': {'enforcement': [{'candidate_id': 'W1', 'right_type': 'unknown', 'triage_by_scenario': {
                    's': [{'current': True, 'decision': 'needs_info', 'annotation': early}]}}]},
                'materiality_ledger': {'annotations': [early, late]},
                'evidence': {'collections': {'sources': [page]}}}

    def packet(self, source):
        packet = deepcopy(source)
        packet['evidence']['collections']['sources'][0]['payload'] = None   # dropped by the module projection
        return packet

    def test_lagging_projection_and_dropped_payload_still_stub_the_original(self):
        import module_review as mr
        source = self.source()
        packet = mr.packet_diet(self.packet(source), source)
        record = packet['evidence']['collections']['sources'][0]
        self.assertNotIn('path', record)
        self.assertEqual(record['review_packet_stub']['triage_decision'], 'not_selected')
        self.assertEqual(packet['review_packet_diet']['stubbed_evidence_ids'], ['EV-P'])
        late = packet['materiality_ledger']['annotations'][1]
        self.assertNotIn('product_content', json.dumps(late, ensure_ascii=False))
        self.assertEqual(late['comparison'], {'difference': '用途不同', 'applicability_limit': '仅此网页'})
        self.assertEqual((late['decision'], late['reason'], late['evidence_refs']), ('not_selected', '网页是头盔下颏带',
                                                                                    ['EV-C', 'EV-P']))
        self.assertEqual(packet['review_packet_diet']['stubbed_annotations'], 2)

    def test_older_tasks_and_newer_open_decisions_keep_the_material(self):
        import module_review as mr
        source = self.source()
        source['task'] = {'task_id': 'T'}
        packet = mr.packet_diet(self.packet(source), source)
        self.assertIn('path', packet['evidence']['collections']['sources'][0])
        source = self.source()
        reopened = dict(source['materiality_ledger']['annotations'][0], annotation_id='A2', decision='needs_info',
                        annotated_at='2026-10-12T10:00:00Z')
        source['materiality_ledger']['annotations'].append(reopened)
        packet = mr.packet_diet(self.packet(source), source)
        self.assertIn('path', packet['evidence']['collections']['sources'][0])


class ChiefDraftTests(unittest.TestCase):
    def test_draft_takes_the_claims_table_the_other_review_gave(self):
        import prepare_adjudication as pa
        table = {'implementations': [{'implementation_id': 'knob'}],
                 'claims': [{'implementation_id': 'knob', 'claim_id': '1', 'claim_type': 'independent', 'elements': []}]}
        first = {'candidate_id': 'C1', 'right_type': 'patent', 'risk': '极低', 'evidence_refs': ['EV-1'], 'comparison': {}}
        second = {'candidate_id': 'C1', 'right_type': 'patent', 'risk': '极低', 'evidence_refs': ['EV-2'], 'comparison': table}
        draft = deepcopy(first)
        self.assertTrue(pa._adopt_claims_table(draft, second))
        self.assertEqual(draft['comparison']['claims'], table['claims'])
        self.assertEqual(draft['evidence_refs'], ['EV-1', 'EV-2'])
        self.assertEqual(draft['risk'], '极低')
        kept = deepcopy(second)
        self.assertFalse(pa._adopt_claims_table(kept, first))                 # a table of its own is never replaced
        design = dict(first, right_type='design')
        self.assertFalse(pa._adopt_claims_table(design, second))


class MarkerTests(unittest.TestCase):
    def test_new_tasks_carry_the_marker(self):
        import review_focus
        text = (Path(__file__).parent / 'create_task.py').read_text(encoding='utf-8')
        self.assertIn("task['review_focus_revision'] = REVIEW_FOCUS_REVISION", text)
        self.assertTrue(review_focus.enabled(FOCUS))
        self.assertFalse(review_focus.enabled({'review_focus_revision': 'other'}))


if __name__ == '__main__':
    unittest.main()
