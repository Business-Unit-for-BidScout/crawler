from bidscout_crawler.crawler import candidate_links

def test_candidate_links_same_host_and_keywords():
    html = '<a href="/a">采购公告</a><a href="https://other.test/b">中标公告</a><a href="/c">医院新闻</a>'.encode()
    assert candidate_links("https://example.test/list", html, 10) == [("https://example.test/a", "采购公告")]
