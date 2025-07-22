--------
title: Como fazer um crawler em Python - Parte 1

header-includes: |
    <meta name="twitter:card" content="summary" />
    <meta name="twitter:site" content="@etandel" />
    <meta name="twitter:title" content="Como fazer um crawler em Python - Parte 1" />
    <meta name="twitter:description" content="Um tempo atrás um colega de faculdade veio me pedir ajuda com ..." />
--------

### Introdução

Um tempo atrás um colega de faculdade veio me pedir ajuda com o TCC dele. Ele queria analisar a divulgação de astronomia nos principais portais de notícias do Brasil e para isso eu sugeri que ele fizesse um crawler. Explicando para ele o que é e como funciona um crawler e lembrando dos meus tempos quando trabalhei com isso na [Sieve](https://sieve.com.br/), achei que valeria a pena falar sobre esse assunto aqui. Na verdade, esse é o primeiro de uma série de posts sobre crawlers que farei aqui.


#### Mas afinal, o que é um crawler?

Um _crawler_ é um programa que é capaz de navegar páginas web recursivamente.
Ou seja, dadas uma ou mais URLs iniciais, ele visita a página, extrai os links na página, visita esses links e assim por diante até não ter mais o que visitar ou atingir alguma condição definida pelo usuário.
Crawlers são usados principalmente para [replicar sites](https://en.wikipedia.org/wiki/Mirror_website), indexar a web (e.g. Google) ou extrair informações relevantes de sites, também chamado de [web scraping](https://pt.wikipedia.org/wiki/Coleta_de_dados_web).

A lógica de um crawler pode ser resumida no diagrama abaixo:

![fluxograma da lógica de um crawler](/images/crawler-flowchart.svg)

Note que essencialmente um crawler é simples: possui apenas um _loop_ e algumas condições de parada. No entanto, são tantos os problemas que podem ocorrer em qualquer uma dessas etapas que criar e manter um crawler robusto e rápido não é nem um pouco trivial. Por isso, apesar de existirem diversas ferramentas no mercado que abstraem essa tarefa - e para produção você provavelmente deveria usar uma delas em vez de criar outra do zero -, essa série visa explicar o passo-a-passo de criar um crawler em Python, iniciando com uma implementação mais ingênua e evoluindo ela para ganhar performance e lidar melhor com dificuldades comuns.

### Web 101

Pra implementar um crawler é preciso primeiro saber como funciona a web. Se você já sabe, pode [pular essa seção](#start); se não, essa introdução vai ser importante para entender as próximas.

#### HTTP - Hypertext Transfer Protocol

HTTP é um dos protocolos usados na web, e ele define basicamente como que um _user agent_ (geralmente um browser tipo o Chrome ou o Firefox) e um servidor se comunicam. Nele, o _user agent_ inicia a comunicação fazendo ao servidor uma requisição que contém até 4 partes:

- Um **caminho** (ou _path_), que define qual o recurso deve ser acessado. Geralmente se parece com `/blog/2018-07-30-crawling-in-python-part1.html`.
- Um **método**, que define o que deve ser feito com o recurso. Os mais comuns são `GET`, que apenas requisita o recurso e `POST`, que é uma das formas de enviar informações para o servidor, muito usado em formulários de cadastro, login etc. No nosso caso, como queremos apenas coletar as páginas, vamos usar somente o `GET`.
- Possivelmente um **corpo**, que contém as informações que estão sendo enviadas ao servidor (e.g. dados de cadastro, cartão de crédito, login etc. a depender da aplicação), se houver.
- Vários **cabeçalhos** (ou _headers_), que são uma série de metadados que definem como o servidor deve processar a requisição: quais os formatos aceitos, que tipo de compressão deve ser usada, qual o "nome" do _user agent_ entre outras.

Recebendo a requisição, o servidor gera uma resposta que contém:

- Um **_status code_**, que é um código numérico que define se deu tudo certo com a requição. São [vários](https://pt.wikipedia.org/wiki/Lista_de_c%C3%B3digos_de_estado_HTTP), sendo os mais comuns:
    - **200**: ok;
    - **301**: o recurso mudou de endereço permanentemente;
    - **403**: o usuário não tem permissão para acessar esse recurso;
    - **500**: deu ruim no servidor.
- Mais **cabeçalhos**, dessa vez definindo metadados sobre a resposta;
- O **corpo** da resposta. No nosso caso, esse corpo será em geral um conteúdo HTML.


#### HTML

[HTML](https://developer.mozilla.org/pt-BR/docs/Web/HTML) é a linguagem usada para se estruturar o conteúdo de uma página para um _browser_ poder carregá-la.
Nela, a informação é organizada em _tags_, que não só indicam qual a função daquele conteúdo mas também guardam propriedades que definem o comportamento e até o estilo (cor, tamanho etc.) dele. Um exemplo de um HTML simples:

``` html
<html>
<head>
    <title>Título da página</title>
</head>

<body>
    <h1>Está é a página</h1>
    <a href="https://etandel.xyz">Clique aqui para visitar o site etandel.xyz.</a>
</body>
</html>
```

Existem **várias** tags diferentes, mas por enquanto fica só o destaque para a que define links: `<a>`.


### Versão 1: Um processo, uma thread, síncrono e ingênuo.  {#start}

Para uma primeira versão, vamos implementar o mínimo necessário para um crawler funcionar e não nos preocupar muito com qualquer problema que possa surgir.

Antes de começar, precisamos resolver como é que o crawler vai visitar uma página e extrair seus links.
O ecossistema do Python possui muitas bibliotecas que podem ajudar nisso, sendo que algumas já até vem embutidas na própria biblioteca padrão da linguagem, como os módulos [`urllib`](https://docs.python.org/3/library/urllib.html) e [`html.parser`](https://docs.python.org/3/library/html.parser.html#module-html.parser).
A escolha do que usar é subjetiva, mas eu acho que, mesmo não sendo embutidas na linguagem e portanto precisarem ser [instaladas](http://blog.dunderlabs.com/criando-seu-ambiente-para-desenvolvimento-web-com-django.html), as mais simples são a [Requests](http://docs.python-requests.org/en/master/) para lidar com a camada HTTP e a [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/bs4/doc/) para trabalhar com o conteúdo HTML da página.

Primeiro, vamos criar uma função que visita uma URL e retorna seu conteúdo, sem nenhum tratamento de erro:

``` python
import requests


def fetch(url: str) -> str:
    """
    Executa um GET na URL e retorna o conteúdo respondido.
    """
    return requests.get(url).content
```

Precisamos também de uma função que leia o HTML da página e extraia os links:

``` python
from typing import List

from bs4 import BeautifulSoup


def get_links(content: str) -> List[str]:
    """
    Busca todas as tags <a> em content que possuam a propriedade
    href, e então retorna os hrefs em uma lista.
    """
    parser = BeautifulSoup(content, 'html.parser')
    return [a['href'] for a in parser.find_all('a', href=True)]
```

Agora a função que de fato faz a lógica toda. Ela deve receber uma URL inicial e executar o fluxograma acima.
Para isso vamos precisar de uma fila de URLs a visitar, um conjunto para armazenar as URLs já visitadas, e um _loop_ para manter a coisa toda rodando.
Além disso, como todo algoritmo recursivo, é sempre bom ter uma condição de parada que evite que nosso crawler fique rodando para sempre; para isso, vamos definir uma profundidade máxima para a recursão.
A nossa fila então vai guardar as próximas URLs a serem visitadas e suas respectivas profundidades, para podermos saber se devemos entrar mais um nível no site ou não.

``` python
from queue import Queue  # já vem pronto na linguagem


def crawl(seed: str, max_depth: int=3):
    # URLs já visitadas
    visited = set()

    # fila de URLs a visitar.
    # já adicionamos a URL original, que tem profundidade 0
    queue = Queue()
    queue.put((0, seed))

    # se a fila estiver vazia, paramos o processamento
    while not queue.empty():
        depth, url = queue.get()
        visited.add(url)

        content = fetch(url)
        # faz alguma coisa com o conteúdo
        process_page(depth, url, content)

        # se a profundidade atual já for máxima,
        # nem pegamos os próximos links
        # se não, adicionamos cada link na fila,
        # lembrando de incrementar a profundidade
        if depth < max_depth:
            for link in get_links(content):
                if link not in visited:
                    queue.put((depth + 1, link))

```

Note a chamada da função `process_page()`. Como só visitar recursivamente um site não traz nenhum valor, precisamos passar os dados recebidos para alguém fazer algo interessante com isso. Por enquanto, vamos só imprimir na tela a profundidade e a URL:

``` python
def process_page(depth: int, url: str, content: str):
    print(f'{depth} - {url}')
```

Falta só adicionar um _boilerplate_ para iniciarmos o crawler pela linha de comando:

``` python
import sys

if __name__ == '__main__':
    max_depth, seed = sys.argv[1:]
    crawl(seed, int(max_depth))
```

### Testando

Vamos testar no G1:

```
% python crawler.py 2 https://g1.globo.com/
0 - https://g1.globo.com/
1 - http://g1.globo.com/economia/agronegocios/
1 - http://g1.globo.com/blogs-e-colunas/
1 - http://g1.globo.com/carros/
1 - http://g1.globo.com/carros/a-z/
1 - http://g1.globo.com/carros/caminhoes/
1 - http://g1.globo.com/carros/motos/
1 - http://g1.globo.com/carros/tabela-fipe/
1 - http://g1.globo.com/ciencia-e-saude/
1 - http://g1.globo.com/economia/concursos-e-emprego/
1 - https://g1.globo.com/e-ou-nao-e/
1 - http://g1.globo.com/economia/
1 - http://g1.globo.com/economia/agronegocios/
1 - http://g1.globo.com/economia/seu-dinheiro/calculadoras/
1 - http://g1.globo.com/economia/concursos-e-emprego/
1 - http://g1.globo.com/economia/seu-dinheiro/
1 - http://g1.globo.com/economia/midia-e-marketing/
1 - http://g1.globo.com/economia/pme/
1 - http://g1.globo.com/educacao/
1 - http://especiais.g1.globo.com/educacao/app-g1-enem/
...
```

Eu parei o processamento logo no começo, porque o site do G1 é bem grande, mas parece que está funcionando direitinho: extraindo os links, calculando a profundidade etc.
Aliás, note como alguns links usam HTTP, enquanto outros HTTPS. Isso é um comportamento bem ruim do G1, pois hoje em dia [não tem mais desculpa](https://letsencrypt.org/) [para não usar HTTPS](https://stormpath.com/blog/why-http-is-sometimes-better-than-https).
Mas como muitos sites não se comportam direito, você como usuário pode se proteger disso usando a extensão [HTTPS Everywhere](https://www.eff.org/https-everywhere), da Electronic Frontier Foundation, que quando possível força seu browser a usar HTTPS mesmo que o link do site esteja errado.

Só para ter certeza, vamos testar nesse site aqui:

```
% python crawler.py 2 https://etandel.xyz/
0 - https://etandel.xyz/
Traceback (most recent call last):
  [stack trace enorme]
requests.exceptions.MissingSchema: Invalid URL './': No schema supplied. Perhaps you meant http://./?
```

Ooops. Parece que o crawler tentou acessar a URL `./`, o que fez dar um erro na Requests. Isso aconteceu porque os links nesse site são caminhos relativos entre as páginas. Isto é, em vez de URLs completas como `https://etandel.xyz/blog/`, os links são na forma `./blog/`, que significa "acesse o caminho `blog/` a partir da página atual". Esse tipo de link é muito comum em sites estáticos como esse aqui, onde em geral uma URL corresponde diretamente a um arquivo no servidor.

Para resolver isso, vamos ter que alterar nossa função `get_links()` para normalizar a URL extraída com base na atual. Por sorte o Python já vem com uma função que resolve isso pra gente:

``` python
In [1]: from urllib.parse import urljoin

In [2]: urljoin('https://site.com/p1', '/p2')
Out[2]: 'https://site.com/p2'

In [3]: urljoin('https://site.com/p1', './p2')
Out[3]: 'https://site.com/p2'

In [4]: urljoin('https://site.com/p1/', './p2')
Out[4]: 'https://site.com/p1/p2'

In [5]: urljoin('https://site.com/p1/', '/p2')
Out[5]: 'https://site.com/p2'

In [6]: urljoin('https://site.com/p1/', 'http://outrosite.com/p2')
Out[6]: 'http://outrosite.com/p2'
```

Melhorando então nossa extração de links:

``` python
def get_links(url: str, content: str) -> List[str]:
    """
    Busca todas as tags <a> em content que possuam a propriedade
    href, normaliza os hrefs para serem URLs absolutas baseadas
    na URL dada e então retorna os links em uma lista.
    """
    parser = BeautifulSoup(content, 'html.parser')
    return [urljoin(url, a['href']) for a in parser.find_all('a', href=True)]
```

Não podemos esquecer de trocar a chamada em `crawl()` para passar a URL atual:

``` python
...
for link in get_links(url, content):
    if link not in visited:
        queue.put((depth + 1, link))
```

Testando de novo:

```
% python crawler.py 2 https://etandel.xyz/
0 - https://etandel.xyz/
1 - https://etandel.xyz/contact.html
1 - https://etandel.xyz/blog.html
1 - http://jaspervdj.be/hakyll
2 - https://etandel.xyz/blog.html
2 - https://twitter.com/etandel
2 - https://www.linkedin.com/in/etandel
2 - https://github.com/etandel
2 - https://keybase.io/etandel
2 - https://garimpofm.wordpress.com/
2 - http://jaspervdj.be/hakyll
2 - https://etandel.xyz/blog/2018-06-10-protecting_postgresql_from_delete.html
2 - http://jaspervdj.be/hakyll
2 - https://github.com/jaspervdj/hakyll
2 - http://jaspervdj.be/
2 - http://jaspervdj.be/index.html
2 - http://jaspervdj.be/tutorials.html
...
```

Quando testamos com o G1, todas as URLs que apareceram eram do mesmo domínio, porque o G1 é um site bem conectado: muitos links dele para ele mesmo.
Já esse site, por não ser tão conectado, fez o crawler começar logo a acessar links externos.
Se você é um Google da vida, percorrer a web inteira é exatamente o que você quer, mas em geral quando criamos crawlers estamos apenas interessados em um site ou só um subconjunto dele.
Para resolver, vamos criar uma função que decide se um link deve ser seguido ou não, e nesse caso vamos considerar que devemos seguir um link apenas quando este for do mesmo domínio da URL inicial:

``` python
from urllib.parse import urlparse


def should_visit(seed: str, link: str) -> bool:
    return urlparse(seed).hostname == urlparse(link).hostname
```

E fazemos a checagem antes de colocar o link na fila:

``` python
for link in get_links(url, content):
    if link not in visited and should_visit(seed, link):
        queue.put((depth + 1, link))
```

Ainda assim falta resolver mais um problema. Mesmo com a checagem, estamos visitando algumas páginas mais de uma vez.
Isso ocorre porque uma página já pode ter sido enfileirada várias vezes antes de ser visitada.
Uma solução possível seria verificar se a URL já não foi enfileirada, mas estruturas de fila em geral não são muito eficientes para testes de pertinência (checar se um elemento já está presente). Pra resolver então fazemos a checagem logo antes de visitar a URL e, para não encher a fila desnecessariamente, antes de enfileirar a URL:

``` python
while not queue.empty():
    depth, url = queue.get()
    if url not in visited:
        visited.add(url)
```

Testando de novo agora, parece que está tudo ok!

```
% python crawler.py 2 https://etandel.xyz/
0 - https://etandel.xyz/
1 - https://etandel.xyz/contact.html
1 - https://etandel.xyz/blog.html
2 - https://etandel.xyz/blog/2018-06-10-protecting_postgresql_from_delete.html
```

### Conclusão

Crawlers são sistemas conceitualmente simples, mas na prática bem complicados devido à quantidade de coisas que podem dar errado em cada etapa do processo. Nesse post vimos não só o básico de como implementar um sistema desse tipo, mas também como lidar com alguns problemas típicos como HTMLs quebrados, URLs relativas e erros comuns de lógica que podem adicionar comportamentos ruins ao sistema.

No próximo post veremos como melhorar a performance e lidar com os erros de rede e protocolo que podem surgir.

### Arquivo completo:

``` python
import sys
from queue import Queue
from typing import List
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


def fetch(url: str) -> str:
    """
    Executa um GET na URL e retorna o conteúdo respondido.
    """
    return requests.get(url).content


def get_links(url: str, content: str) -> List[str]:
    """
    Busca todas as tags <a> em content que possuam a propriedade
    href, normaliza os hrefs para serem URLs absolutas baseadas
    na URL dada e então retorna os links em uma lista.
    """
    parser = BeautifulSoup(content, 'html.parser')
    return [urljoin(url, a['href']) for a in parser.find_all('a', href=True)]


def should_visit(seed: str, link: str) -> bool:
    return urlparse(seed).hostname == urlparse(link).hostname


def process_page(depth: int, url: str, content: str):
    print(f'{depth} - {url}')


def crawl(seed: str, max_depth: int=3):
    # URLs já visitadas
    visited = set()

    # fila de URLs a visitar.
    # já adicionamos a URL original, que tem profundidade 0
    queue = Queue()
    queue.put((0, seed))

    # se a fila estiver vazia, paramos o processamento
    while not queue.empty():
        depth, url = queue.get()
        if url not in visited:
            visited.add(url)

            content = fetch(url)
            # faz alguma coisa com o conteúdo
            process_page(depth, url, content)

            # se a profundidade atual já for máxima,
            # nem pegamos os links
            # se não, adicionamos cada link na fila,
            # lembrando de incrementar a profundidade
            if depth < max_depth:
                for link in get_links(url, content):
                    if link not in visited and should_visit(seed, link):
                        queue.put((depth + 1, link))


if __name__ == '__main__':
    max_depth, seed = sys.argv[1:]
    crawl(seed, int(max_depth))
```
