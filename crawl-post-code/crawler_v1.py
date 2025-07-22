import sys
from queue import Queue
from typing import List, Set, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import requests


def fetch(url: str) -> bytes:
    """
    Executa um GET na url e retorna o conteúdo respondido.
    """
    return requests.get(url).content


def get_links(url: str, content: bytes) -> List[str]:
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


def process_page(depth: int, url: str, content: bytes):
    print(f'{depth} - {url}')


def crawl(seed: str, max_depth: int=3):
    # urls já visitadas
    visited: Set[str] = set()

    # fila de urls a visitar.
    # já adicionamos a url original, que tem profundidade 0
    queue: Queue[Tuple[int, str]] = Queue()
    queue.put((0, seed))

    # se a fila estiver vazia, paramos o processamento
    while not queue.empty():
        depth, url = queue.get()
        if url not in visited:
            visited.add(url)

            content = fetch(url)
            # faz alguma coisa com o conteúdo
            process_page(depth, url, content)

            # se a profundidade atual já for máxima, nem pegamos os links
            # se não, adicionamos cada link na fila,
            # lembrando de incrementar a profundidade
            if depth < max_depth:
                for link in get_links(url, content):
                    if link not in visited and should_visit(seed, link):
                        queue.put((depth + 1, link))


if __name__ == '__main__':
    max_depth, seed = sys.argv[1:]
    crawl(seed, int(max_depth))
