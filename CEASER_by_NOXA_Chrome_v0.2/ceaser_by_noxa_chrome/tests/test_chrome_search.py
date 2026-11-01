"""Pure browser-driver and research-logic tests; no internet access required."""
import asyncio
from datetime import datetime, timezone

import pytest

from backend.chrome_research import (EXTRACT_ARTICLE, EXTRACT_SEARCH_RESULTS,
                                     normalize_search_link, public_https, search_url)
from backend import main


def test_public_url_restrictions():
    good = ['https://example.com/a', 'https://store.example.org:443/a']
    bad = ['http://example.com', 'https://localhost/', 'https://127.0.0.1/',
           'https://10.0.0.1/', 'https://192.168.0.1/', 'https://169.254.169.254/',
           'https://[::1]/', 'https://evil.internal/', 'file:///etc/hosts',
           'https://foo.example:8080', 'https://admin:secret@example.com']
    assert all(public_https(s) for s in good)
    assert not any(public_https(s) for s in bad)


def test_search_url_and_redirect_links():
    assert 'www.google.com/search?' in search_url('Jordan perfume', 'google')
    assert 'Jordan+perfume' in search_url('Jordan perfume', 'google')
    assert 'www.bing.com/search?' in search_url('Jordan perfume', 'bing')
    assert normalize_search_link('https://www.google.com/url?q=https%3A%2F%2Fexample.com%2Fblog') == 'https://example.com/blog'
    assert normalize_search_link('https://www.google.com/search?q=local') is None
    assert normalize_search_link('https://127.0.0.1/private') is None
    with pytest.raises(ValueError):
        search_url('test', 'duckduckgo')


def insert_record(record_id, objective='Investigate perfume preferences in Jordan'):
    now = datetime.now(timezone.utc).isoformat()
    with main.LOCK, main.connection() as c:
        c.execute('INSERT INTO investigations (id,objective,region,depth,status,stage,progress,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)',
                  (record_id, objective, 'Jordan', 'quick', 'running', 'queued', 0, now, now))


def test_research_browser_mocked(monkeypatch, tmp_path):
    monkeypatch.setattr(main, 'DB', tmp_path / 'mocked.sqlite')
    main.initialize()
    insert_record('demo')

    class FakeBrowser:
        channel = 'chrome'
        engine = 'google'

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def search(self, query, count=6):
            return [{'title': 'Perfume buying survey', 'url': 'https://example.com/study',
                     'snippet': 'Example survey summary', 'retrieved_at': '2026-01-01',
                     'query': query, 'content_status': 'not_fetched'}]

        async def read_source(self, item, char_limit=4500):
            return {**item, 'content': 'Example survey reported 200 sampled customers. ' * 15,
                    'content_status': 'page_excerpt'}

    async def fake_model(messages, max_tokens):
        if max_tokens == 800:
            return {'queries': ['consumer perfume Jordan preferences', 'Jordan fragrance competitors']}
        return {'summary': 'Preliminary survey data', 'findings': [
            {'claim': 'The example survey has a sample of 200.', 'assessment': 'FACT',
             'confidence': 'medium', 'source_ids': ['S1'], 'limitations': 'Sample biased'},
            {'claim': 'Unsupported allegation', 'assessment': 'FACT', 'confidence': 'high',
             'source_ids': ['S999'], 'limitations': ''}],
            'opportunities': ['Survey further'], 'gaps': ['Representativeness'], 'recommended_actions': ['Verify sample']}

    monkeypatch.setattr(main, 'ChromeResearchBrowser', FakeBrowser)
    monkeypatch.setattr(main, 'model_json', fake_model)
    asyncio.run(main.run_research('demo'))
    d = main.get_record('demo')
    assert d['status'] == 'completed'
    assert len(d['sources']) == 1
    assert d['sources'][0]['content_status'] == 'page_excerpt'
    assert len(d['findings']) == 2
    assert d['findings'][0]['assessment'] == 'FACT'
    assert d['findings'][1]['assessment'] == 'UNDETERMINED'
    assert '[S1]' in d['report']


def test_missing_evidence_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(main, 'DB', tmp_path / 'empty.sqlite')
    main.initialize()
    insert_record('missing')

    class EmptyBrowser:
        channel = 'chrome'
        engine = 'google'

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def search(self, query, count=6):
            raise RuntimeError('Google blocked the automated browser')

    async def fake_model(messages, max_tokens):
        return {'queries': ['market study Jordan', 'consumer survey Jordan']}

    monkeypatch.setattr(main, 'ChromeResearchBrowser', EmptyBrowser)
    monkeypatch.setattr(main, 'model_json', fake_model)
    asyncio.run(main.run_research('missing'))
    d = main.get_record('missing')
    assert d['status'] == 'failed'
    assert d['report'] is None
    assert len(d['findings']) == 0


def test_dom_extractors_with_local_chromium():
    """Smoke-test DOM parsing without a network; skip if no local Chromium."""
    import shutil
    from playwright.async_api import async_playwright

    executable = shutil.which('chromium') or shutil.which('google-chrome')
    if not executable:
        pytest.skip('No local Chromium executable')

    async def check():
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=executable, headless=True,
                                               args=['--no-sandbox'])
            page = await browser.new_page()
            await page.set_content('''<html><body><div id="search"><div class="MjjYud">
               <a href="https://example.com/article"><h3>Perfume study Jordan</h3></a>
               <div class="VwiC3b">Public sample findings and limitations.</div></div></div></body></html>''')
            google = await page.evaluate(EXTRACT_SEARCH_RESULTS, 'google')
            assert google and google[0]['url'] == 'https://example.com/article'
            assert 'sample findings' in google[0]['snippet']
            await page.set_content('''<html><body><ol><li class="b_algo">
               <h2><a href="https://example.com/another">Competitor overview</a></h2>
               <div class="b_caption"><p>Market research limitations</p></div></li></ol></body></html>''')
            bing = await page.evaluate(EXTRACT_SEARCH_RESULTS, 'bing')
            assert bing and bing[0]['url'] == 'https://example.com/another'
            await page.set_content('<html><head><title>Example</title></head><body><main><p>Credible source text</p><nav>Ignore</nav></main></body></html>')
            article = await page.evaluate(EXTRACT_ARTICLE)
            assert 'Credible source text' in article['content']
            assert 'Ignore' not in article['content']
            await browser.close()

    asyncio.run(check())
