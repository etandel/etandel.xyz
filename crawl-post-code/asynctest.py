import asyncio

from aiohttp import ClientSession



URLS = [
    'http://etandel.xyz/',
    'http://etandel.xyz/contact.html',
    'http://etandel.xyz/blog.html',
    'http://etandel.xyz/blog/2018-07-30-crawling-in-python-part1.html',
    'http://etandel.xyz/blog/2018-06-10-protecting_postgresql_from_delete.html',
    'http://etandel.xyz/blog/2018-07-30-crawling-in-python-part1.html#start',
]



async def async_wait_and_print(dt, val):
    await asyncio.sleep(dt)
    print(val)


async def fetch(session, url):
    async with session.get(url) as response:
        t = await response.text()
        print(f'Done - {url}')
        return t
 

async def main1():
#    print('init')
    tasks = []
    async with ClientSession() as session:
        for url in URLS:
            tasks.append(asyncio.create_task(fetch(session, url)))

        for f in asyncio.as_completed(tasks):
            await f

#        for url in URLS:
#            await asyncio.create_task(fetch(session, url))


async def main2():
        async with ClientSession() as session:
            for url in URLS:
                await fetch(session, url)


if __name__ == '__main__':
    asyncio.run(main1())
#    loop = asyncio.get_event_loop()
#    loop.run_until_complete(main())


