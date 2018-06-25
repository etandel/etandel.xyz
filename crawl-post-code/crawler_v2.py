import sys
from queue import Queue
from typing import List
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import requests

import asyncio
import re
import unicodedata
from abc import ABC, abstractmethod
from collections import Counter
from pprint import pprint
from typing import Callable, Mapping, Sequence, Set, Tuple

from aiohttp import ClientSession
from bs4 import BeautifulSoup


async def fetch(semaphore: asyncio.Semaphore,
                session: ClientSession, url: str) -> str:
    """
    Executa um GET na url e retorna o conteúdo respondido.
    """
    async with semaphore:
        async with session.get(url) as response:
            print(f'Trying {url}')
            return await response.text()


def get_links(url: str, content: str) -> List[str]:
    """
    Busca todas as tags <a> em content que possuam a propriedade href,
    normaliza os hrefs para serem URLs absolutas baseadas na url dada
    e então retorna os links em uma lista.
    """
    parser = BeautifulSoup(content, 'html.parser')
    return [urljoin(url, a['href'])
            for a in parser.find_all('a', href=True)]


def should_visit(seed: str, link: str) -> bool:
    return urlparse(seed).hostname == urlparse(link).hostname


def process_page(depth: int, url: str, content: str):
    print(f'{depth} - {url}')


async def crawl(semaphore: asyncio.Semaphore,
                session: ClientSession,
                seed: str,
                max_depth: int=3):
    # urls já visitadas
    visited: Set[str] = set()

    # fila de urls a visitar.
    # já adicionamos a url original, que tem profundidade 0
#    queue: asyncio.LifoQueue[Tuple[int, List[str]]] = asyncio.LifoQueue()
    queue: Queue[Tuple[int, List[str]]] = Queue()
    queue.put((0, [seed]))

    # se a fila estiver vazia, paramos o processamento
    while not queue.empty():
        depth, urls = queue.get()

        visited_in_this_run = []
        results = []
        tasks = []
        for url in urls:
            if url not in visited:
                visited.add(url)
                visited_in_this_run.append(url)
                tasks.append(fetch(semaphore, session, url))

        results = await asyncio.gather(*tasks)

        for url, content in zip(visited_in_this_run, results):

            # faz alguma coisa com o conteúdo
            process_page(depth, url, content)

            # se a profundidade atual já for máxima, nem pegamos os links
            # se não, adicionamos cada link na fila,
            # lembrando de incrementar a profundidade
            if depth < max_depth:
                next_urls = []
                for link in get_links(url, content):
                    if link not in visited and should_visit(seed, link):
                        next_urls.append(link)

                queue.put((depth + 1, next_urls))


async def main():
    max_concurrency, max_depth, seed = sys.argv[1:]
    semaphore = asyncio.BoundedSemaphore(int(max_concurrency))
    async with ClientSession() as session:
        await crawl(semaphore, session, seed, int(max_depth))


if __name__ == '__main__':
    asyncio.run(main())

