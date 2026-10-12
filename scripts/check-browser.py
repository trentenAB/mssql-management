"""Optional real-browser smoke check against a running DEMO instance."""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

root = Path(__file__).resolve().parents[1]
base = os.getenv('BROWSER_TEST_URL', 'http://127.0.0.1:8000')
with sync_playwright() as p:
    executable = os.getenv('CHROMIUM_PATH')
    browser = p.chromium.launch(headless=True, executable_path=executable, args=['--no-sandbox'])
    page = browser.new_page(viewport={'width':1440,'height':1100},
                            permissions=['clipboard-read', 'clipboard-write'])
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

    # Filters compose without changing version labels or the compare selection.
    history = page.locator('.history-row:visible')
    page.locator('#history-version').fill('#2')
    expect(history.locator('.version-link')).to_have_text(['#2'])
    page.locator('#history-version').fill('')
    page.locator('#history-change').fill('al')
    expect(history).to_have_count(2)
    page.locator('#history-actor').fill('MAYA')
    expect(history.locator('.version-link')).to_have_text(['#2'])
    page.locator('#history-date-from').fill('2026-02-03')
    page.locator('#history-date-to').fill('2026-02-03')
    expect(history).to_have_count(1)  # Both date boundaries include the entire UTC day.
    page.locator('#history-status').select_option('applied')
    expect(history).to_have_count(0)
    expect(page.locator('#history-no-matches')).to_be_visible()
    page.get_by_role('button', name='Clear filters', exact=True).click()
    expect(history).to_have_count(3)
    expect(page.locator('#history-filter-status')).to_have_text('Showing 3 of 3 versions')
    expect(page.locator('#history-date-from')).to_have_value('')
    expect(page.locator('#history-date-to')).to_have_value('')
    expect(page.locator('#history-status')).to_have_value('')
    page.locator('#history-status').select_option('applied')
    expect(history.locator('.version-link')).to_have_text(['#3'])
    page.locator('#history-status').select_option('definition')
    expect(history).to_have_count(2)
    page.get_by_role('button', name='Clear filters', exact=True).click()
    page.locator('#history-date-from').fill('2026-02-18')
    expect(history.locator('.version-link')).to_have_text(['#3'])
    page.locator('#history-date-to').fill('2026-01-12')
    expect(history).to_have_count(0)
    expect(page.locator('#history-filter-status')).to_have_text('Start date must be on or before end date.')
    page.get_by_role('button', name='Clear filters', exact=True).click()
    page.locator('#history-date-to').fill('2026-01-12')
    expect(history.locator('.version-link')).to_have_text(['#1'])
    page.get_by_role('button', name='Clear filters', exact=True).click()

    # Exercise the real Clipboard API and timer, including successive clicks.
    copy_button = page.locator('#copy-definition')
    copy_button.click()
    expect(copy_button).to_have_text('Copied')
    assert page.evaluate('navigator.clipboard.readText()') == page.locator('#selected-definition').text_content()
    expect(copy_button).to_have_text('Copy SQL', timeout=5000)
    page.clock.install()
    copy_button.click()
    expect(copy_button).to_have_text('Copied')
    page.clock.run_for(2000)
    copy_button.click()
    expect(copy_button).to_have_text('Copied')
    page.clock.run_for(1000)
    expect(copy_button).to_have_text('Copied')  # Earlier reset must have been cancelled.
    page.clock.run_for(2000)
    expect(copy_button).to_have_text('Copy SQL')
    page.evaluate("Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async () => { throw new Error('Clipboard denied'); } } })")
    copy_button.click()
    expect(copy_button).to_have_text('Select SQL to copy')
    page.clock.run_for(3000)
    expect(copy_button).to_have_text('Copy SQL')
    page.locator('#left-version').select_option('1')
    page.locator('#right-version').select_option('3')
    page.get_by_role('button', name='Compare', exact=True).click()
    assert page.locator('.diff-line.insert').count() == 4
    page.locator('#swap-versions').click()
    assert page.locator('#left-version').input_value() == '3'
    page.get_by_role('button', name='Compare', exact=True).click()
    assert page.locator('.diff-line.delete').count() == 4
    for name, count in (('CalculateTax', 1), ('Customers', 3), ('GetOrderSummary', 2)):
        page.locator(f'.object-item[data-name="dbo.{name}"]').click()
        assert page.locator('h1').inner_text() == name
        expect(page.locator('.history-row .version-link')).to_have_text([f'#{n}' for n in range(count, 0, -1)])
        assert page.locator('#right-version option').first.text_content().startswith(f'#{count} ·')
        expect(page.locator('.definition-panel h2')).to_have_text(f'Selected version #{count}')
        page.locator('.history-row .version-link').last.click()
        expect(page.locator('.definition-panel h2')).to_have_text('Selected version #1')
        if name == 'Customers':
            page.locator('#history-status').select_option('activity')
            expect(page.locator('.history-row:visible .version-link')).to_have_text(['#3', '#1'])
    page.goto(base)
    page.screenshot(path=str(root/'screenshot-desktop.png'), full_page=True)
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.locator('#history-actor').fill('maya')
    expect(page.locator('.history-row:visible .version-link')).to_have_text(['#2'])
    page.get_by_role('button', name='Clear filters', exact=True).click()
    expect(page.locator('.history-row:visible')).to_have_count(3)
    page.screenshot(path=str(root/'screenshot-mobile.png'), full_page=True)
    assert not errors, errors
    browser.close()
print('Browser passed: object-local versions, history filters/date ranges, copy feedback/reset, comparison, and mobile layout; no JavaScript errors.')
