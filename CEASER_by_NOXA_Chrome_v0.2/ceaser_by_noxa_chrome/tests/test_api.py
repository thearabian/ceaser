from backend.main import safe_url, ResearchRequest

def test_safe_urls():
    assert safe_url('https://example.com/article')
    assert not safe_url('file:///etc/passwd')
    assert not safe_url('http://localhost/private')
    assert not safe_url('https://user:password@example.com/')

def test_research_validation():
    r = ResearchRequest(objective='Investigate customer preferences', region='Jordan', depth='standard')
    assert r.depth == 'standard'
