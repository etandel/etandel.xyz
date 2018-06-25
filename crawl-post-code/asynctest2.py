import asyncio
import logging
import aiohttp
from urllib.parse import urljoin, urlparse
from lxml import html as lh


class AsyncCrawler:

    def __init__(self, start_url, crawl_depth, max_concurrency=200):
        self.start_url = start_url
        self.base_url = '{}://{}'.format(urlparse(self.start_url).scheme, urlparse(self.start_url).netloc)
        self.crawl_depth = crawl_depth
        self.seen_urls = set()
        self.session = aiohttp.ClientSession()
        self.bounded_sempahore = asyncio.BoundedSemaphore(max_concurrency)

    async def _http_request(self, url):
        print('Fetching: {}'.format(url))
        async with self.bounded_sempahore:
            try:
                async with self.session.get(url, timeout=30) as response:
                    html = await response.read()
                    return html
            except Exception as e:
                logging.warning('Exception: {}'.format(e))

    def find_urls(self, html):
        found_urls = []
        dom = lh.fromstring(html)
        for href in dom.xpath('//a/@href'):
            url = urljoin(self.base_url, href)
            if url not in self.seen_urls and url.startswith(self.base_url):
                found_urls.append(url)
        return found_urls

    async def extract_async(self, url):
        data = await self._http_request(url)
        found_urls = set()
        if data:
            for url in self.find_urls(data):
                found_urls.add(url)
        return url, data, sorted(found_urls)

    async def extract_multi_async(self, to_fetch):
        futures, results = [], []
        for url in to_fetch:
            if url in self.seen_urls: continue
            self.seen_urls.add(url)
            futures.append(self.extract_async(url))

        for future in asyncio.as_completed(futures):
            try:
                results.append((await future))
            except Exception as e:
                logging.warning('Encountered exception: {}'.format(e))
        return results

    def parser(self, data):
        raise NotImplementedError

    async def crawl_async(self):
        to_fetch = [self.start_url]
        results = []
        for depth in range(self.crawl_depth + 1):
            batch = await self.extract_multi_async(to_fetch)
            to_fetch = []
            for url, data, found_urls in batch:
                data = self.parser(data)
                results.append((depth, url, data))
                to_fetch.extend(found_urls)
        await self.session.close()
        return results


class GuardianCrawler(AsyncCrawler):

    def parser(self, data):
        dom = lh.fromstring(data)
        title = dom.cssselect('title')
        if title:
            title = title[0].text
        return {'title': title}


if __name__ == '__main__':
    url = 'http://etandel.xyz'
    crawler = GuardianCrawler(url, 3)
    future = asyncio.Task(crawler.crawl_async())
    loop = asyncio.get_event_loop()
    loop.run_until_complete(future)
    loop.close()
    result = future.result()
    print(len(result))
