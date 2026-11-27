// Optional browser regression. Start the fixture with:
// PYTHONPATH=. streamlit run tests/browser/atomic_refresh_fixture.py --server.port 8858
// Then run: node tests/browser/atomic_refresh.cjs
const assert = require('node:assert/strict');
const { chromium } = require('playwright');

async function capture(page, action, first, second) {
  await page.evaluate(({first,second}) => {
    window.__samples = [];
    const tick = () => {
      const read = (selector) => {
        const node = document.querySelector(selector);
        return node?.checkVisibility({visibilityProperty: true, opacityProperty: true})
          ? node.textContent : '';
      };
      const app = document.querySelector('[data-testid="stApp"]');
      window.__samples.push({
        first: read(first),
        second: read(second),
        shell: !!read('.setta-inv-top'),
        loader: !!read('.setta-inv-route-loader'),
        state: app?.dataset.testScriptState,
        covered: document.documentElement.hasAttribute('data-setta-page-updating'),
      });
      window.__sampleFrame = requestAnimationFrame(tick);
    };
    tick();
  }, {first,second});
  await action();
  await page.waitForTimeout(950);
  return page.evaluate(() => {
    cancelAnimationFrame(window.__sampleFrame);
    return window.__samples;
  });
}

(async () => {
  const browser = await chromium.launch({
    ...(process.env.CHROMIUM_PATH ? {executablePath: process.env.CHROMIUM_PATH} : {})
  });
  try {
    for (const width of [1363, 390]) {
      const page = await browser.newPage({viewport:{width, height:850}});
      await page.goto(process.env.APP_URL || 'http://127.0.0.1:8858');
      await page.getByText('Original · Segunda parte').waitFor();
      const test = async (label, action, first, second) => {
        const frames = await capture(page, action, first, second);
        assert.ok(frames.some(f => f.loader), label + ': no progress indication');
        const leaks = frames.filter(f =>
          Boolean(f.first) !== Boolean(f.second) ||
          (first !== ".setta-inv-intro h1" && f.first && f.first.split(' · ')[0] !== f.second.split(' · ')[0]) ||
          !f.shell);
        assert.deepEqual(leaks.slice(0, 3), [], label + ': mixed/partial frame');
        assert.ok(frames.at(-1).first && frames.at(-1).second && !frames.at(-1).covered,
          label + ': result never unveiled');
        console.log(width, label, frames.length, 'frames');
      };

      const local = await capture(page, () => page.getByText('Filtros', {exact:true}).click(),
        '#first-part', '#second-part');
      assert.equal(local.some(f => f.covered || f.loader), false, 'Local expansion must not show loading');
      await test('Unlisted toggle triggers full rerun',
        () => page.getByText('Detalhes do período',{exact:true}).click(), '#first-part', '#second-part');
      await page.getByText('Novo · Segunda parte').waitFor();

      await page.getByRole('textbox',{name:'Buscar OP'}).fill('260001');
      await test('Enter submits fragment',
        () => page.getByRole('textbox',{name:'Buscar OP'}).press('Enter'), '#fragment-first', '#fragment-second');
      await page.getByText('260001 · Resultado completo').waitFor();

      await test('Route changes with atomic title and body', async () => {
        await page.getByRole('button',{name:'Abrir menu lateral'}).click();
        await page.getByRole('button',{name:'Kardex',exact:true}).click();
      }, '.setta-inv-intro h1', '#second-part');
      await page.getByRole('heading',{name:'Kardex',exact:true}).waitFor();
      await page.close();
    }
  } finally { await browser.close(); }
})().catch(e => {console.error(e); process.exitCode = 1;});
