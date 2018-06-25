--------
title: Como fazer um crawler em Python - Parte 2
--------

### Introdução

No [último post](/blog/2018-07-30-crawling-in-python-part1.html) vimos como funciona um crawler e implementamos uma versão simples e ingênua: tudo rodava numa thread só e não nos preocupamos em tratar erros.

Nesse post vamos ver como as capacidades assíncronas das últimas versões do Python podem nos ajudar a melhorar a performance do código. Aliás, esse post assume que você leu a parte 1 ou pelo menos sabe como funciona um crawler, então antes de continuar pode ser que você queira dar uma olhada [nela](/blog/2018-07-30-crawling-in-python-part1.html).


### Medindo a performance

Antes de tentarmos melhor a performance é bom medir exatamente a atual, para termos uma base para comparar. Rodando o crawler para esse site usando uma conexão meio ruim, temos:

```
% time python crawler.py 2 https://etandel.xyz/
0 - https://etandel.xyz/
1 - https://etandel.xyz/contact.html
1 - https://etandel.xyz/blog.html
2 - https://etandel.xyz/blog/2018-07-30-crawling-in-python-part1.html
2 - https://etandel.xyz/blog/2018-06-10-protecting_postgresql_from_delete.html
python crawler_v1.py 3 http://etandel.xyz/  0.63s user 0.05s system 12% cpu 5.627 total
```

Rodando mais algumas vezes para diminuir erros aleatórios, cheguei a uma média de ~12 segundos.


Antes de sair otimizando o código, primeiro temos que encontrar os pontos no código que estão gerando o gargalo de performance.  Fazendo mais alguns testes com a `requests`, percebi que cada requisição está demorando em média ~1 segundo. Comparando com o tempo total do crawling, dá pra ver que o código passa quase que o tempo todo só esperando a requisição ser feita. E como a implementação que fizemos é sequencial, isso significa que o tempo total vai ser a soma dos tempos de cada requisição (mais algum diferencial para parsing, imprimir na tela etc. que no nosso caso é desprezível).

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
Isso ocorre justamente em `await response.text()`: nessa linha dizemos que pode ser que a operação demore um pouco e portanto podemos entregar o controle para alguma outra co-rotina que já esteja pronta pra continuar.

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

TODO
```
--- resultado ---
```

Dá pra ver que tivemos um ganho bom já, caindo quase pela metade o tempo de processamento. Vamos validar no G1 também, já que ele tem muito mais URLs e por isso o ganho vai ser maior:

TODO
```
--resultado--
```

Oops, parece que fomos bloqueados. Isso aconteceu porque não limitamos a quantidade de requisições que podem ser feitas simultaneamente, então o crawler vai fazendo tudo o que ele consegue ao mesmo tempo, e isso foi detectado pelos servidores do g1 como um abuso, gerando o bloqueio. É importante sempre tomar cuidado para não fazer muitas requisições para os sites de uma vez. Primeiro, porque muitas vezes os sites não estão preparados para receber muitas requisições de uma vez, e você pode acabar interferindo com o funcionamento deles. Segundo, porque justamente para evitar que isso aconteça muitos sites acabam bloqueando origens com um _throughput_ de requisições alto.

A solução é limitarmos a quantidade de requisições simultâneas usando um semáforo.

### Semáforo

Semáforos são estruturas que permitem coordenar as co-rotinas controlando quantas podem executar por vez, igual a... semáforos.
Uma outra metáfora boa é a forma como vários estabelecimentos passaram a limitar a quantidade de clientes durante a pandemia de COVID-19: apenas uma quantidade fixa de clientes entra na loja e somente quando um sai que outro pode entrar.
O segurança que fica na porta da loja coordenando isso é jutamente o que chamamos de semáfaro em computação.

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

Rodando com concorrência = 10:

TODO

Agora sim =)

Note que o tempo foi bem melhor também. Comparando com a versão sequencial, tive um aumento de ~Yx.  TODO


### Melhorias

#### `gather()` vs `as_completed()`

Uma das coisas que podem ser melhoradas é a forma como as tarefas rodam concorrentemente. Da forma que fizemos, tentamos rodar todas as filhas de uma página ao mesmo tempo, o que tem dois problemas:

1. O crawler fica suscetível a um ataque onde uma página possui muitos e muitos links, o que pode fazer estourar a memóra (já que vamos criar todas as tasks simultaneamente).
1. Se uma página tem menos links que a concorrência máxima configurada, estaremos desperdiçando concorrência. Por exemplo, se colocarmos o limite em 10 e visitarmos uma página com só 2 filhas, teríamos 8 _slots_ vazios que poderiam estar puxando alguma outra página da fila.

Além disso, o `gather()` espera todas as tasks terminarem antes de seguir, o que significa que se uma página demorar mais que as outras, o processamento vai ficar esperando ela sendo que já daria pra ir processando o que já tá pronto.

Uma forma de resolver isso seria reorganizar o código para usar [`as_completed()`](https://docs.python.org/3/library/asyncio-task.html#asyncio.as_completed) em vez do `gather()`. Ainda assim estaríamos limitados a apenas 1 processo, o que nos traz à próxima possível melhoria:


#### Escalabilidade horizontal

Da forma como foi escrito, esse crawler só ganha performance se melhorarmos a máquina e consequentemente aumentarmos o limite de concorrência. E mesmo assim isso pode não melhorar muito, pois como vimos concorrência muito alta pode fazer o crawler ser bloqueado.

Para realmente ganharmos mais performance então precisaríamos permitir escalabilidade horizontal, onde teríamos várias máquinas trabalhando em conjunto. Para isso, teríamos que ter processos dedicados a visitar somente uma página por vez, e algum tipo de orquestração que define quem vai visitar que página.

O código já até dá um bom indício de como fazer isso: se a fila fosse compartilhada entre múltiplos processos, o código já funcionaria distribuído com poquíssima alteração:

- Transformar a fila de URLs em algo compartilhado, usando algum message broker ([RabbitMQ](https://www.rabbitmq.com/), [ZeroMQ](https://zeromq.org/), [Kafka](https://kafka.apache.org/) etc.).
- Transformar o `fetch()` em um processo próprio que lê as URLs da fila.
- Criar uma fila de páginas já visitadas a serem processadas.
- Transformar o processamento da página e extração de links em um processo que lê da fila anterior.

![](/images/dist-crawler-architecture.svg)


Uma vantagem disso é que permite quebrar ainda mais o processamento em unidades menores se necessário, criando uma pipeline que permite escalar cada componente separadamente.


#### Erros e pegadinhas

_Crawling_ é todo um universo de problemas que podem acontecer: problemas de rede (falha de conexão, timeouts etc.), HTMLs quebrados, páginas que dependem agressivamente de JavaScript para funcionar, links quebrados, armadilhas etc.

Como são muitos, e dependem muito dos sites em questão, não faz sentido explorar todos aqui, então fica como exercício para o leitor. ;-)


### Conclusão


### Código completo

```
```
