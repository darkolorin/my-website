#!/usr/bin/env python3
"""Offline import/resume checks; translation and network access are always mocked."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location('history_importer_under_test', SCRIPT_DIR / 'import_telegram_history.py')
history = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = history
SPEC.loader.exec_module(history)
MODEL = 'offline-fixture-model'
KEY = f'openai:{MODEL}:{history.OPENAI_PROMPT_VERSION}'


def source_post(pid, text='Исходный текст.'):
    return {'id': pid, 'url': f'https://t.me/chillhousetech/{pid}',
            'date_utc': '2025-04-02T12:30:00+00:00', 'text_ru': text, 'images': []}


def cached_post(pid, text='Сохранённый оригинал.'):
    return {**source_post(pid, text), 'hash': 'existing-hash', 'translation_key': 'existing-model',
            'title_en': '', 'text_en': 'The existing cached translation.'}


class ImportHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.snapshot = self.root / 'snapshot.json'
        self.archive = self.root / 'archive.json'
        self.checkpoint = self.root / 'checkpoint.json'
        environment = patch.dict(os.environ, {'OPENAI_API_KEY': 'offline-fixture-not-a-real-key'}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        network = patch('requests.sessions.Session.request', side_effect=AssertionError('Network forbidden in offline tests'))
        network.start()
        self.addCleanup(network.stop)

    def write(self, path, posts):
        document = {'channel': 'chillhousetech', 'source': 'https://t.me/chillhousetech', 'posts': posts}
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def inputs(self, source, existing=()):
        self.write(self.snapshot, source)
        self.write(self.archive, list(existing))

    def run_import(self, **kwargs):
        return history.run_import(self.snapshot, self.archive, self.checkpoint,
                                  workers=kwargs.pop('workers', 1), model=kwargs.pop('model', MODEL),
                                  timeout_s=20, max_attempts=kwargs.pop('max_attempts', 1), **kwargs)

    def fake_translation(self, *, text_ru, model, timeout_s):
        self.assertEqual(model, MODEL)
        self.assertEqual(timeout_s, 20)
        return '', 'Translated: ' + text_ru

    def checkpoint_data(self, pid, text, *, key=KEY, translated='Cached pending translation.'):
        return {'version': 1, 'channel': 'chillhousetech', 'translations': {
            str(pid): {'source_text_sha256': hashlib.sha256(text.encode()).hexdigest(),
                       'translation_key': key, 'title_en': '', 'text_en': translated}}}

    def save_checkpoint(self, data):
        self.checkpoint.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')

    def test_dry_run_without_credentials_never_calls_api_or_mutates_inputs(self):
        self.inputs([source_post(1)], [cached_post(1205)])
        self.save_checkpoint(self.checkpoint_data(999, 'Other checkpoint source'))
        before = {path: path.read_bytes() for path in [self.snapshot, self.archive, self.checkpoint]}
        with patch.dict(os.environ, {}, clear=True), patch.object(history, 'translate_and_format_ru_to_en_openai') as translate:
            report = self.run_import(dry_run=True)
        self.assertEqual(report['status'], 'dry_run')
        self.assertEqual(report['pending_translations'], 1)
        translate.assert_not_called()
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_missing_key_fails_before_api_or_archive_checkpoint_writes(self):
        self.inputs([source_post(1)])
        self.save_checkpoint(self.checkpoint_data(999, 'Other checkpoint source'))
        before_archive, before_checkpoint = self.archive.read_bytes(), self.checkpoint.read_bytes()
        with patch.dict(os.environ, {}, clear=True), patch.object(history, 'translate_and_format_ru_to_en_openai') as translate:
            with self.assertRaisesRegex(ValueError, 'OPENAI_API_KEY'):
                self.run_import()
        translate.assert_not_called()
        self.assertEqual(self.archive.read_bytes(), before_archive)
        self.assertEqual(self.checkpoint.read_bytes(), before_checkpoint)

    def test_existing_cache_values_and_snapshot_absent_posts_survive_exactly(self):
        original = cached_post(10)
        original['date_utc'] = None
        retained = cached_post(1205, 'Старая запись, которой нет в снимке.')
        changed = {**source_post(10, 'Изменённый публичный текст.'), 'date_utc': '2026-01-01T10:00:00Z',
                   'images': ['https://example.com/new.jpg'],
                   'forwarded_from': {'name': 'Original channel', 'url': 'https://t.me/sourcechannel/2'}}
        self.inputs([changed, source_post(11, 'Новая запись.')], [original, retained])
        with patch.object(history, 'translate_and_format_ru_to_en_openai', side_effect=self.fake_translation) as translate:
            report = self.run_import()
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(translate.call_count, 1)
        self.assertEqual(translate.call_args.kwargs['text_ru'], 'Новая запись.')
        saved = {p['id']: p for p in json.loads(self.archive.read_text())['posts']}
        for key, value in original.items():
            self.assertEqual(saved[10][key], value)
        self.assertEqual(saved[1205], retained)
        self.assertEqual(saved[10]['forwarded_from'], changed['forwarded_from'])
        self.assertEqual(saved[11]['text_en'], 'Translated: Новая запись.')
        self.assertFalse(self.checkpoint.exists())

    def test_partial_failure_leaves_archive_untouched_and_resume_only_translates_missing(self):
        self.inputs([source_post(2, 'Успешная запись.'), source_post(1, 'Временная ошибка.')], [cached_post(1205)])
        original_bytes = self.archive.read_bytes()
        def partial(**kwargs):
            if kwargs['text_ru'] == 'Временная ошибка.':
                raise RuntimeError('A controlled permanent fixture failure')
            return self.fake_translation(**kwargs)
        with patch.object(history, 'translate_and_format_ru_to_en_openai', side_effect=partial):
            report = self.run_import()
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(self.archive.read_bytes(), original_bytes)
        self.assertTrue(self.checkpoint.exists())
        checkpoint = json.loads(self.checkpoint.read_text())
        self.assertEqual(set(checkpoint['translations']), {'2'})
        self.assertEqual(checkpoint['translations']['2']['source_text_sha256'], hashlib.sha256('Успешная запись.'.encode()).hexdigest())
        self.assertEqual(checkpoint['translations']['2']['translation_key'], KEY)
        with patch.object(history, 'translate_and_format_ru_to_en_openai', side_effect=self.fake_translation) as translate:
            resumed = self.run_import()
        self.assertEqual(resumed['status'], 'complete')
        self.assertEqual(resumed['checkpoint_reused'], 1)
        self.assertEqual(translate.call_count, 1)
        self.assertEqual(translate.call_args.kwargs['text_ru'], 'Временная ошибка.')
        self.assertFalse(self.checkpoint.exists())
        self.assertEqual({p['id'] for p in json.loads(self.archive.read_text())['posts']}, {1, 2, 1205})

    def test_checkpoint_requires_matching_source_hash_and_translation_key(self):
        for stale_source, stale_key in [('Другой оригинал.', KEY), ('Текущий оригинал.', 'openai:other-model:older-prompt')]:
            with self.subTest(source=stale_source, key=stale_key):
                self.inputs([source_post(1, 'Текущий оригинал.')])
                self.save_checkpoint(self.checkpoint_data(1, stale_source, key=stale_key))
                with patch.object(history, 'translate_and_format_ru_to_en_openai', side_effect=self.fake_translation) as translate:
                    result = self.run_import()
                self.assertEqual(result['status'], 'complete')
                self.assertEqual(translate.call_count, 1)
                saved = json.loads(self.archive.read_text())['posts'][0]
                self.assertEqual(saved['text_en'], 'Translated: Текущий оригинал.')

    def test_poll_translation_contains_question_and_options_without_votes(self):
        poll = {**source_post(3, ''), 'poll': {'question': 'Ваш выбор?', 'options': [
            {'text': 'Один', 'votes': 999, 'percentage': 99.7}, {'text': 'Два', 'voters': 88}],
            'total_voter_count': 12345}}
        self.inputs([poll])
        with patch.object(history, 'translate_and_format_ru_to_en_openai', side_effect=self.fake_translation) as translate:
            report = self.run_import()
        expected = 'Ваш выбор?\n\n- Один\n- Два'
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(translate.call_args.kwargs['text_ru'], expected)
        saved = json.loads(self.archive.read_text())['posts'][0]
        self.assertEqual(saved['text_ru'], expected)
        self.assertEqual(saved['content_kind'], 'poll')
        self.assertEqual(saved['text_en'], 'Translated: ' + expected)

    def test_empty_caption_media_and_known_service_actions_need_no_api_or_invented_body(self):
        source = [
            {**source_post(10, ''), 'images': ['https://example.com/photo.jpg']},
            {**source_post(11, ''), 'media_types': ['video']},
            {**source_post(12, ''), 'media_types': ['document']},
            {**source_post(13, ''), 'media_not_supported_in_widget': True},
            {**source_post(1, ''), 'service_action': 'channel_created'},
            {**source_post(5, ''), 'service_action': 'pinned_message'},
        ]
        self.inputs(source)
        with patch.dict(os.environ, {}, clear=True), patch.object(history, 'translate_and_format_ru_to_en_openai') as translate:
            result = self.run_import()
        self.assertEqual(result['status'], 'complete')
        translate.assert_not_called()
        saved = {p['id']: p for p in json.loads(self.archive.read_text())['posts']}
        self.assertEqual([saved[i]['content_kind'] for i in [10, 11, 12, 13, 1, 5]],
                         ['photo', 'video', 'document', 'unsupported', 'service', 'service'])
        self.assertTrue(all(p['text_en'] == '' and p['text_ru'] == '' for p in saved.values()))
        self.assertIn('created', saved[1]['media_notice_en'].lower())
        self.assertIn('pinned', saved[5]['media_notice_en'].lower())

    def test_empty_translation_result_is_partial_and_does_not_replace_archive(self):
        self.inputs([source_post(1)], [cached_post(1205)])
        before = self.archive.read_bytes()
        with patch.object(history, 'translate_and_format_ru_to_en_openai', return_value=('', '')):
            result = self.run_import()
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(self.archive.read_bytes(), before)
        self.assertEqual(result['untranslated_ids'], [1])

    def test_failed_final_atomic_save_retains_checkpoint_and_previous_archive(self):
        self.inputs([source_post(1)], [cached_post(1205)])
        before = self.archive.read_bytes()
        replace = os.replace
        def fail_archive(source, destination):
            if Path(destination) == self.archive:
                raise OSError('Controlled final archive replace failure')
            return replace(source, destination)
        with patch.object(history, 'translate_and_format_ru_to_en_openai', side_effect=self.fake_translation), patch.object(history.os, 'replace', side_effect=fail_archive):
            with self.assertRaises(OSError):
                self.run_import()
        self.assertEqual(self.archive.read_bytes(), before)
        self.assertTrue(self.checkpoint.exists())
        self.assertEqual(set(json.loads(self.checkpoint.read_text())['translations']), {'1'})
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    def test_workers_are_bounded_and_cli_accepts_both_snapshot_flag_names(self):
        self.inputs([source_post(1)])
        with self.assertRaises(ValueError):
            self.run_import(workers=5, dry_run=True)
        for flag in ['--input', '--snapshot']:
            with self.subTest(flag=flag):
                run = subprocess.run([sys.executable, str(SCRIPT_DIR / 'import_telegram_history.py'), flag,
                                      str(self.snapshot), '--archive', str(self.archive), '--checkpoint',
                                      str(self.checkpoint), '--model', MODEL, '--dry-run'],
                                     text=True, capture_output=True, env={})
                self.assertEqual(run.returncode, 0, run.stderr)
                report = json.loads(run.stdout)
                self.assertEqual(report['status'], 'dry_run')
                self.assertEqual(report['pending_translations'], 1)
        self.assertFalse(self.checkpoint.exists())

    def test_gpt5_network_failure_is_not_retried_outside_existing_responses_retries(self):
        with patch.object(history, 'translate_and_format_ru_to_en_openai', side_effect=history.requests.ReadTimeout('Controlled network timeout')) as translate, patch.object(history.time, 'sleep') as sleep:
            with self.assertRaises(history.requests.ReadTimeout):
                history.translate_with_retry('Исходный текст.', 'gpt-5.2', 20, 3)
        self.assertEqual(translate.call_count, 1)
        sleep.assert_not_called()

    def test_legacy_chat_network_failures_still_retry_up_to_bound(self):
        with patch.object(history, 'translate_and_format_ru_to_en_openai', side_effect=history.requests.ReadTimeout('Controlled network timeout')) as translate, patch.object(history.time, 'sleep') as sleep:
            with self.assertRaises(history.requests.ReadTimeout):
                history.translate_with_retry('Исходный текст.', 'gpt-4o-mini', 20, 3)
        self.assertEqual(translate.call_count, 3)
        self.assertEqual([call.args for call in sleep.call_args_list], [(1,), (2,)])

    def test_rate_limit_and_server_errors_retry_for_both_model_paths(self):
        for model in ['gpt-5.2', 'gpt-4o-mini']:
            for status in [429, 503]:
                with self.subTest(model=model, status=status):
                    error = RuntimeError(f'HTTP {status}: controlled fixture error')
                    with patch.object(history, 'translate_and_format_ru_to_en_openai', side_effect=error) as translate, patch.object(history.time, 'sleep') as sleep:
                        with self.assertRaises(RuntimeError):
                            history.translate_with_retry('Исходный текст.', model, 20, 3)
                    self.assertEqual(translate.call_count, 3)
                    self.assertEqual(sleep.call_count, 2)


if __name__ == '__main__':
    unittest.main()
