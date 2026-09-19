import asyncio
import unittest
from playwright.async_api import async_playwright
from taskweave_playwright import snapshot, locate


class ImageLocators(unittest.TestCase):
    def test_unnamed_images_in_separate_parents_have_unique_capture_locators(self):
        async def scenario():
            async with async_playwright() as runtime:
                browser = await runtime.chromium.launch(headless=True)
                try:
                    page = await browser.new_page()
                    await page.set_content('''<html><body>
                    <header><img style="width:100px;height:28px"></header>
                    <form><div><input id="verifyCode"><span><img style="width:97px;height:42px"></span></div></form>
                    <footer><img style="width:24px;height:24px"></footer>
                    <canvas width="97" height="42"></canvas>
                    <iframe id="child" srcdoc='<div><img style="width:97px;height:42px"></div>'></iframe>
                    </body></html>''')
                    data = await snapshot(page)
                    images = [e for e in data['elements'] if e['tag'] in ('img', 'canvas')]
                    self.assertEqual(len(images), 4)
                    self.assertEqual(len({e['selector']['value'] for e in images}), 4)
                    for element in images:
                        self.assertEqual(element['match_count'], 1)
                        locator = locate(page, element['selector'])
                        self.assertEqual(await locator.count(), 1)
                        png = await locator.screenshot(type='png')
                        self.assertTrue(png.startswith(b'\x89PNG'))
                    captcha = next(e for e in images if e['tag']=='img' and e['width']==97)
                    self.assertIn('form', captcha['selector']['value'])
                    child = data['frames'][1]['elements'][0]
                    self.assertEqual(child['selector']['frame'], '#child')
                    self.assertEqual(await locate(page, child['selector']).count(), 1)
                    self.assertNotIn('src=', str(data))
                finally:
                    await browser.close()
        asyncio.run(scenario())
