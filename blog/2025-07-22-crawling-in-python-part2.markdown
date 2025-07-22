--------
title: Como fazer um crawler em Python - Parte 2

header-includes: |
    <meta name="twitter:card" content="summary" />
    <meta name="twitter:site" content="@etandel" />
    <meta name="twitter:title" content="Como fazer um crawler em Python - Parte 2" />
    <meta name="twitter:description" content="Usando asyncio para ganhar performance" />
--------

### Introdução

No [último post](/blog/2018-07-30-crawling-in-python-part1.html) vimos como funciona um crawler e implementamos uma versão simples e ingênua: tudo rodava numa thread só e não nos preocupamos em tratar erros.

Nesse post vamos ver como as capacidades assíncronas das últimas versões do Python podem nos ajudar a melhorar a performance do código. Aliás, esse post assume que você leu a parte 1 ou pelo menos sabe como funciona um crawler, então antes de continuar pode ser que você queira dar uma olhada [nela](/blog/2018-07-30-crawling-in-python-part1.html).


### Medindo a performance

Antes de tentarmos melhor a performance é bom medir exatamente a atual, para termos uma base para comparar. Rodando o crawler para esse site usando uma conexão mais ou menos, temos:

```
$ time python crawler_v1.py 2  https://etandel.xyz
0 - https://etandel.xyz
1 - https://etandel.xyz/
1 - https://etandel.xyz/contact.html
1 - https://etandel.xyz/blog.html
2 - https://etandel.xyz/blog/2018-07-30-crawling-in-python-part1.html
2 - https://etandel.xyz/blog/2018-06-10-protecting_postgresql_from_delete.html
python crawler_v1.py 2 https://etandel.xyz  1.06s user 0.05s system 52% cpu 2.104 total
```


Antes de sair otimizando o código, primeiro temos que encontrar os pontos no código que estão gerando o gargalo de performance.  Fazendo mais alguns testes com a `requests`, percebi que cada requisição está demorando entre 200 e 500 milissegundos. Comparando com o tempo total do crawling, dá pra ver que o código passa quase que o tempo todo só esperando a requisição ser feita. E como a implementação que fizemos é sequencial, isso significa que o tempo total vai ser a soma dos tempos de cada requisição (mais algum diferencial para parsing, imprimir na tela etc. que no nosso caso é desprezível).

Isso significa que o sistema é *IO-bound*. Ou seja, o gargalo está em esperar por eventos de entrada e saída, que no caso é a comunicação pela rede. Uma forma óbvia de resolver isso é simplesmente arranjar uma conexão de internet mais rápida, o que diminuiria o tempo de cada requisição e portanto o tempo total.

No entanto, isso não resolve completamente, porque ainda assim o tempo total será a soma dos tempos de cada requisição. Chutando um valor otimista de 0.2 segundo por requisição, um crawler que visitasse todas as [6.4 milhões de páginas de produto](https://static.b2wdigital.com/upload/releasesderesultados/00003071.pdf) da Americanas.com demoraria quase 14 dias para completar!

Logo, precisamos ser mais espertos: se o problema é ter que esperar a resposta na rede, será que não dá pra ir fazendo outra coisa enquanto isso?


### Assincronia

[Desde a versão 3.3](https://asyncio-notes.readthedocs.io/en/latest/asyncio-history.html) Python tem algum tipo de suporte a assincronia, de forma que é possível pausar a execução de um trecho de código até que ele já esteja pronto para continuar. Isso permite com que na prática a gente consiga puxar outra tarefa pra fazer enquanto está esperando a anterior ficar pronta, e aí transformar uma lógio IO-bound em CPU-bound.

Para uma boa introdução a assincronia em Python, recomendo [esse post](https://diogommartins.wordpress.com/2017/04/07/concorrencia-e-paralelismo-threads-multiplos-processos-e-asyncio-parte-1/).


### Fazendo o crawler ser assíncrono


Para melhorar nossa performance, vamos ter que transformar o processamento do nosso IO em assíncrono, e para isso temos que usar uma biblioteca HTTP que seja async, como a [aiohttp](https://docs.aiohttp.org/en/stable/). Para isso, precisamos alterar a definição da nossa função que visita as páginas::

``` python
from aiohttp import ClientSession


async def fetch(session: ClientSession, url: str) -> str:
    """
    Executa um GET na url e retorna o conteúdo respondido.
    """
    async with session.get(url) as response:
        return await response.text()
```

Primeiro, vale notar que estamos definindo a função agora com `async def`.
Isso diz para o interpretador que a função é na verdade uma co-rotina e portanto pode ser "pausada".
Isso ocorre justamente em `await response.text()`: nessa linha dizemos que pode ser que a operação tenha que esperar e portanto podemos entregar o controle para alguma outra co-rotina que já esteja pronta pra continuar.

Além disso, agora a função está recebendo um outro parâmetro, uma `ClientSession`.
As requisições feitas pela `aiohttp` ocorrem sempre dento de uma sessão, o que permite à biblioteca certas otimizações que aceleram ainda mais o IO.
A [documentação recomenda](https://aiohttp.readthedocs.io/en/stable/client_quickstart.html#make-a-request) manter uma sessão por site, então como estamos _crawleando_ apenas um domínio, podemos instanciá-la uma vez só e reutilizá-la na função `crawl()`.

Quer dizer, **co-rotina** `crawl()`, porque agora ela tem que ser async também:

``` python
async def crawl(session: ClientSession, seed: str, max_depth: int=3):
    ...
```

Para tirarmos vantagem da assincronia, precisamos dar um jeito de chamar `fetch()` para várias páginas concorrentemente.
Uma forma natural de fazer isso é juntar todas as urls encontradas em uma página e visitá-las de uma vez só.
Para isso vamos ter que salvar na fila uma lista de urls, em vez de uma só. Além disso, vamos ter que coletar as visitas numa lista de tarefas a serem executadas concorrentemente.

``` python
    ...

    # fila de urls a visitar.
    # já adicionamos a url original, que tem profundidade 0
    queue: Queue[Tuple[int, List[str]]] = Queue()
    queue.put((0, [seed]))

    # se a fila estiver vazia, paramos o processamento
    while not queue.empty():
        depth, urls = queue.get()

        # urls visitadas nesse grupo.
        # necessário para depois podermos saber qual resposta pertence a qual url
        visited_in_this_run = []
        # tarefas a serem executadas concorrentemente
        tasks = []

        for url in urls:
            if url not in visited:
                visited.add(url)
                visited_in_this_run.append(url)
                tasks.append(fetch(session, url))
```

Agora que temos várias tarefas acumuladas, podemos pedir para o _loop_ de eventos processar tudo concorremente, e a forma mais direta de fazer isso é com o [`gather()`](https://docs.python.org/3/library/asyncio-task.html#asyncio.gather):

``` python
        results = await asyncio.gather(*tasks)
```

Depois iteramos sobre os resultados processando e coletando as próximas urls a serem visitadas:

``` python
        for url, content in zip(visited_in_this_run, results):

            # faz alguma coisa com o conteúdo
            process_page(depth, url, content)

            # se a profundidade atual já for máxima, nem pegamos os links
            # se não, adicionamos cada link na fila,
            # lembrando de incrementar a profundidade
            if depth < max_depth:
                # temos que agregar as urls para adicionar na fila
                # para podermos vistar todas elas de uma vez
                next_urls = []
                for link in get_links(url, content):
                    if link not in visited and should_visit(seed, link):
                        next_urls.append(link)

                queue.put((depth + 1, next_urls))
```

E então criamos a co-rotina principal que vai ler os parâmetros da linha de comando, inicializar a sessão e iniciar o crawler:


``` python
async def main():
    max_depth, seed = sys.argv[1:]
    async with ClientSession() as session:
        await crawl(session, seed, int(max_depth))


if __name__ == '__main__':
    asyncio.run(main())
```

### Testando

Testando nesse site:

```
time python crawler_v2.py 10 2  https://etandel.xyz
0 - https://etandel.xyz
1 - https://etandel.xyz/
1 - https://etandel.xyz/contact.html
1 - https://etandel.xyz/blog.html
2 - https://etandel.xyz/blog/2018-07-30-crawling-in-python-part1.html
2 - https://etandel.xyz/blog/2018-06-10-protecting_postgresql_from_delete.html
python crawler_v2.py 10 2 https://etandel.xyz  1.11s user 0.06s system 75% cpu 1.552 total
```

Dá pra ver que tivemos algum ganho, mas que não foi tâo significativo porque são poucas páginas. Vamos validar no G1 também para comparar melhor, já que ele tem muito mais URLs, mas antes um detalhe sobre boa vizinhança.


Do jeito que o código foi estruturado, estamos tentando buscar o máximo de páginas que conseguimos ao mesmo tempo. Isso pode acabar sobrecarregando alguns sites, o que não é muito legal de se fazer. Além disso, pode ser contraproducente porque esse tipo de comportamento pode ser detectado por alguns sites como um abuso, e podem acabar bloqueando seu crawler ou fazendo algum tipo de _throttling_ nas respotas. 

Então é importante sempre tomar cuidado para não sobrecarregar os sites fazendo muitas requisições ao mesmo tempo, e uma boa forma de fazer isso é com um semáforo.

### Semáforo

Semáforos são estruturas que permitem coordenar as co-rotinas controlando quantas podem executar por vez, igual a... semáforos.
Uma metáfora que me ajuda a visualizar é que o semáforo é como um _maître_ de um restaurante: ele vai levando os clientes às suas mesas até encher, e então passa a formar uma fila de espera, de forma que só permite entrar mais um grupo quando vaga uma mesa.

O próprio Python já vem com uma [implementação de semáforos assíncronos](https://docs.python.org/3/library/asyncio-sync.html#asyncio.BoundedSemaphore), que vamos usar.
Pra facilitar os testes, vamos adicionar um parâmetro que define a concorrência máxima, criar o `BoundedSemaphore` usando esse valor, e passá-lo pelo código para ser usado na corotina `fetch()`, que é quem realmente precisa ser limitada:


``` python
async def fetch(semaphore: asyncio.Semaphore
                session: ClientSession, url: str) -> str:
    """
    Executa um GET na url e retorna o conteúdo respondido.
    """
    async with semaphore:
        async with session.get(url) as response:
            print(f'Trying {url}')
            return await response.text()


async def crawl(semaphore: asyncio.Semaphore,
                session: ClientSession,
                seed: str,
                max_depth: int=3):
    ...


async def main():
    max_concurrency, max_depth, seed = sys.argv[1:]
    semaphore = asyncio.BoundedSemaphore(int(max_concurrency))
    async with ClientSession() as session:
        await crawl(semaphore, session, seed, int(max_depth))

```

### Testando com G1

Rodando a versão sequencial, com profundidade máxima de 1 (porque mais que isso demora muito):
```
$ time python crawler_v1.py 1  https://g1.globo.com
0 - https://g1.globo.com
1 - https://g1.globo.com/
1 - https://g1.globo.com/fantastico/noticia/2025/07/22/nao-me-resta-muito-tempo-disse-ozzy-osbourne-em-entrevista-ao-fantastico.ghtml
1 - https://g1.globo.com/saude/noticia/2025/07/22/ozzy-osbourne-parkinson-problemas-saude.ghtml
1 - https://g1.globo.com/pop-arte/musica/noticia/2025/07/22/ozzy-osbourne-relembre-a-carreira-do-musico-em-fotos.ghtml
1 - https://g1.globo.com/pop-arte/musica/noticia/2025/07/22/ozzy-osbourne-fez-seu-ultimo-show-com-o-black-sabbath-no-comeco-de-julho.ghtml
...
1 - https://g1.globo.com/institucional/sobre-o-g1.ghtml
1 - https://g1.globo.com/institucional/equipe-do-g1.ghtml
1 - https://g1.globo.com/institucional/vc-no-g1-como-entrar-em-contato-enviar-videos-fotos-e-mensagens.ghtml
1 - https://g1.globo.com/institucional/termos-de-uso-do-g1.ghtml
python crawler_v1.py 1 https://g1.globo.com  33.54s user 0.74s system 5% cpu 10:06.23 total
```

Rodando agora com concorrência = 10:
```
$ time python crawler_v2.py 10 1  https://g1.globo.com
0 - https://g1.globo.com
1 - https://g1.globo.com/
1 - https://g1.globo.com/fantastico/noticia/2025/07/22/nao-me-resta-muito-tempo-disse-ozzy-osbourne-em-entrevista-ao-fantastico.ghtml
1 - https://g1.globo.com/saude/noticia/2025/07/22/ozzy-osbourne-parkinson-problemas-saude.ghtml
1 - https://g1.globo.com/pop-arte/musica/noticia/2025/07/22/ozzy-osbourne-relembre-a-carreira-do-musico-em-fotos.ghtml
...
1 - https://g1.globo.com/institucional/sobre-o-g1.ghtml
1 - https://g1.globo.com/institucional/equipe-do-g1.ghtml
1 - https://g1.globo.com/institucional/vc-no-g1-como-entrar-em-contato-enviar-videos-fotos-e-mensagens.ghtml
1 - https://g1.globo.com/institucional/termos-de-uso-do-g1.ghtml
python crawler_v2.py 10 1 https://g1.globo.com  5.75s user 0.41s system 32% cpu 19.171 total
```

Apenas 30x mais rápido =)


### Melhorias

#### `gather()` vs `as_completed()`

Uma das coisas que podem ser melhoradas é a forma como as tarefas rodam concorrentemente. Da forma que fizemos, tentamos rodar todas as filhas de uma página ao mesmo tempo, o que tem pelo menos dois problemas:

1. Se uma página possui muitos links, vamos enfileirar uma task para cada um, o que pode gerar um problem de memória.
1. Se uma página tem menos links que a concorrência máxima configurada, estaremos desperdiçando concorrência. Por exemplo, se colocamos o limite em 10 e visitamos uma página com só 2 filhas, teríamos 8 _slots_ vazios que poderiam estar puxando alguma outro link da fila.

Além disso, o `gather()` espera todas as tasks terminarem antes de seguir, o que significa que se uma página demorar mais que as outras, o processamento vai ficar esperando ela sendo que já daria pra ir processando o que já tá pronto.

Uma forma de resolver isso seria reorganizar o código para usar [`as_completed()`](https://docs.python.org/3/library/asyncio-task.html#asyncio.as_completed) em vez do `gather()`. Ainda assim estaríamos limitados a apenas 1 processo, o que nos traz à próxima possível melhoria:


#### Escalabilidade horizontal

Da forma como foi escrito, esse crawler só ganha performance se melhorarmos a máquina e consequentemente aumentarmos o limite de concorrência. E mesmo assim isso pode não melhorar muito, pois como vimos concorrência muito alta pode fazer o crawler ser bloqueado.

Para realmente ganharmos mais performance então precisaríamos permitir escalabilidade horizontal, onde teríamos várias máquinas trabalhando em conjunto. Para isso, teríamos que ter processos dedicados a visitar somente uma página por vez, e algum tipo de orquestração que define quem vai visitar que página.

O código já até dá um bom indício de como fazer isso: se a fila fosse compartilhada entre múltiplos processos, o código já funcionaria distribuído com poquíssima alteração:

- Transformar a fila de URLs em algo que possa ser compartilhado por múltiplos processos em máquinas diferentes usando algum _message broker_ como [RabbitMQ](https://www.rabbitmq.com/), [ZeroMQ](https://zeromq.org/), [Kafka](https://kafka.apache.org/) etc..
- Transformar a lógica do `fetch()` em um processo que lê as URLs da fila compartilahada, acessa a página, e manda o resultado para outra fila.

Por exemplo:

![diagrama mostrando uma fila sendo lida por um processo fetcher, que coloca o resultado em outra fila, que é lida por um processador, que retorna novas urls para a fila inicial.](/images/dist-crawler-architecture.svg)


Uma vantagem disso é que permite quebrar ainda mais o processamento em unidades menores se necessário, criando uma pipeline que permite escalar cada componente separadamente.


#### Erros e pegadinhas

_Crawling_ é todo um universo de problemas que podem acontecer: problemas de rede (falha de conexão, timeouts etc.), HTMLs quebrados, páginas que dependem de JavaScript para funcionar, links quebrados, armadilhas etc.

Como são muitos, e são comumente particulares a cada site, não faz sentido explorar todos aqui, então fica de exercício para quem lê.


### Conclusão

Desde a introdução do `asyncio` ao Python, ficou relativamente fácil ganhar performance em aplicações IO-bound, e crawling é só uma das muitas aplicações desse conceito. Além disso, são relativamente poucas as alterações necessárias para transformar um código sync em async, mas ainda assim é necessário prestar atenção aos detalhes: concorrência, sincronização etc.

De qualquer forma, espero ter ajudado você a entender um pouco mais como utilizar o `asyncio`.


### Código completo

```python
import sys
from typing import List
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

import asyncio
from typing import Set, Tuple

from aiohttp import ClientSession
from bs4 import BeautifulSoup


async def fetch(semaphore: asyncio.Semaphore,
                session: ClientSession, url: str) -> str:
    """
    Executa um GET na url e retorna o conteúdo respondido.
    """
    async with semaphore:
        async with session.get(url) as response:
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
    queue: asyncio.LifoQueue[Tuple[int, List[str]]] = asyncio.LifoQueue()
    await queue.put((0, [seed]))

    # se a fila estiver vazia, paramos o processamento
    while not queue.empty():
        depth, urls = await queue.get()

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

                await queue.put((depth + 1, next_urls))


async def main():
    max_concurrency, max_depth, seed = sys.argv[1:]
    semaphore = asyncio.BoundedSemaphore(int(max_concurrency))
    async with ClientSession() as session:
        await crawl(semaphore, session, seed, int(max_depth))


if __name__ == '__main__':
    asyncio.run(main())
```
