"""Optional browser check: pip install playwright; python scripts/browser_e2e.py.
Uses an isolated temp SQLite DB and in-process ASGI requests; no live data touched.
"""
import asyncio
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.main import create_app
from httpx import AsyncClient, ASGITransport
from playwright.async_api import async_playwright

async def main():
    with tempfile.TemporaryDirectory() as directory:
        app = create_app(f'sqlite:///{directory}/browser.db')
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url='http://education.test') as client:
                async with async_playwright() as p:
                    browser = await p.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
                    for width in [1366, 360]:
                        page = await browser.new_page(viewport={'width': width, 'height': 900})
                        errors = []
                        page.on('pageerror', lambda e: errors.append(str(e)))
                        async def serve(route):
                            req = route.request
                            u = urlsplit(req.url)
                            response = await client.request(req.method, u.path + ('?' + u.query if u.query else ''), content=req.post_data_buffer)
                            await route.fulfill(status=response.status_code, headers=dict(response.headers), body=response.content)
                        await page.route('http://education.test/**', serve)
                        await page.goto('http://education.test/#students')
                        await page.get_by_role('button', name='＋ O‘quvchi qo‘shish').click()
                        form = page.locator('#student-form')
                        name = f'Test {width} <img src=x onerror=alert(1)>'
                        for key, value in {'name': name, 'phone': '+998901234567', 'group_name': 'Python', 'monthly_fee': '100.30'}.items():
                            await form.locator(f'[name={key}]').fill(value)
                        await form.get_by_role('button', name='Saqlash', exact=True).click()
                        await page.locator('#student-dialog').wait_for(state='hidden')
                        await page.locator('nav a[href="#debtors"]').click()
                        row = page.locator('tr').filter(has_text=name)
                        await row.get_by_role('button', name='＋ To‘lov qo‘shish').click()
                        await page.locator('[name=amount]').fill('0')
                        await page.get_by_role('button', name='To‘lovni saqlash').click()
                        await page.locator('[data-error=amount]').get_by_text('Musbat summa', exact=False).wait_for()
                        await page.locator('[name=amount]').fill('40.10')
                        await page.get_by_role('button', name='To‘lovni saqlash').click()
                        await page.get_by_role('heading', name=name+' — to‘lovlar tarixi').wait_for()
                        await page.locator('nav a[href="#debtors"]').click()
                        row = page.locator('tr').filter(has_text=name)
                        await row.get_by_text('60.20 so‘m', exact=True).wait_for()
                        await row.get_by_role('button', name='＋ To‘lov qo‘shish').click()
                        await page.locator('[name=amount]').fill('60.20')
                        await page.get_by_role('button', name='To‘lovni saqlash').click()
                        await page.get_by_role('heading', name=name+' — to‘lovlar tarixi').wait_for()
                        await page.locator('nav a[href="#debtors"]').click()
                        await page.get_by_text('Qarzdorlar topilmadi', exact=True).wait_for()
                        for dest in ['home','students','payment']:
                            await page.locator(f'nav a[href="#{dest}"]').click()
                            await page.wait_for_timeout(150)
                            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width,dest)
                        assert not errors, errors
                        await page.screenshot(path=f'/tmp/education-{width}.png', full_page=True)
                        print(f'{width}px: create → partial → full → no debt; no overflow; safe user text OK')
                        await page.close()
                    await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
