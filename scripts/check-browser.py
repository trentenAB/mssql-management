"""Optional real-browser smoke check against a running DEMO instance."""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
base = os.getenv('BROWSER_TEST_URL', 'http://127.0.0.1:8000')
with sync_playwright() as p:
    executable = os.getenv('CHROMIUM_PATH')
    browser = p.chromium.launch(headless=True, executable_path=executable, args=['--no-sandbox'])
    page = browser.new_page(viewport={'width':1440,'height':1100})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(base)
    assert page.locator('h1').inner_text() == 'ActiveCustomers'
    assert page.locator('.diff-line.insert').count() > 0
    page.locator('#object-search').fill('tax')
    assert page.locator('.object-item:visible').count() == 1
    page.locator('#object-search').fill('')
    page.get_by_role('button', name='Procs', exact=True).click()
    assert page.locator('.object-item:visible').count() == 1
    page.get_by_role('button', name='All', exact=True).click()
    page.locator('#left-version').select_option('1')
    page.locator('#right-version').select_option('3')
    page.get_by_role('button', name='Compare', exact=True).click()
    assert page.locator('.diff-line.insert').count() == 4
    page.locator('#swap-versions').click()
    assert page.locator('#left-version').input_value() == '3'
    page.get_by_role('button', name='Compare', exact=True).click()
    assert page.locator('.diff-line.delete').count() == 4
    for name in ('CalculateTax','Customers','GetOrderSummary'):
        page.locator(f'.object-item[data-name="dbo.{name}"]').click()
        assert page.locator('h1').inner_text() == name
    page.goto(base)
    page.screenshot(path=str(root/'screenshot-desktop.png'), full_page=True)
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.screenshot(path=str(root/'screenshot-mobile.png'), full_page=True)
    assert not errors, errors
    browser.close()
print('Browser passed: object history, search, filters, diff, reverse comparison, mobile layout; no JavaScript errors.')
