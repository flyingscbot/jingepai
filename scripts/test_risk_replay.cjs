'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, 'static/home/js', file), 'utf8');
const engine = require('../static/home/js/risk_replay_engine.js');
const dataContext = { window: {} };
vm.runInNewContext(read('risk_history_data.js'), dataContext);
const data = JSON.parse(JSON.stringify(dataContext.window.RISK_HISTORY));
assert.equal(data.cases.length, 4);
for (const source of data.cases) {
    const history = engine.prepareCase(source);
    assert(source.candles.every(candle => candle.volume > 0));
    const first = engine.snapshot(history, 0);
    assert.equal(first.price, 100);
    assert.equal(first.candles.length, 1);
    assert.equal(first.candles[0].high, first.candles[0].open);
    assert.equal(first.candles[0].low, first.candles[0].open);
    const last = engine.snapshot(history, 600);
    assert.deepEqual(last.candles, history.candles);
    assert.equal(last.completed, source.candles.length);
    const scale = 100 / source.candles[0].open;
    source.candles.forEach((candle, index) => {
        for (const key of ['open', 'high', 'low', 'close']) {
            assert.equal(last.candles[index][key], candle[key] * scale);
        }
    });
    for (let elapsed = 0; elapsed < 600; elapsed += .5) {
        const snapshot = engine.snapshot(history, elapsed);
        assert.equal(snapshot.candles.length, snapshot.completed + 1);
        assert.deepEqual(snapshot.candles.slice(0, snapshot.completed), history.candles.slice(0, snapshot.completed));
        const partial = snapshot.candles.at(-1), original = history.candles[snapshot.completed];
        assert(partial.high <= original.high + 1e-9);
        assert(partial.low >= original.low - 1e-9);
        assert(partial.close <= partial.high && partial.close >= partial.low);
    }
}
const synthetic = engine.prepareCase({candles: [
    {date:'2020-01-01', open:100, high:120, low:80, close:110},
    {date:'2020-01-02', open:50, high:60, low:40, close:45},
]});
assert.equal(engine.snapshot(synthetic, 300).price, 50); // Preserve the overnight gap.
assert.equal(engine.snapshot(synthetic, 0).candles[0].high, 100); // No future daily high.
assert.throws(() => engine.prepareCase({candles: [
    {date:'2020-01-01', open:100, high:90, low:80, close:110},
    {date:'2020-01-02', open:50, high:60, low:40, close:45},
]}));

function uiHarness(missingData = false) {
    let now = 0, interval = null;
    const elements = {}, listeners = {};
    const element = () => ({ style:{}, disabled:true, hidden:false, textContent:'', children:[], attrs:{},
        addEventListener(event, fn){this[event]=fn;}, append(...children){this.children.push(...children);},
        setAttribute(key, value){this.attrs[key]=value;}, focus(){}, scrollIntoView(){} });
    const document = { getElementById(id){return elements[id] ||= element();},
        createElement:element, addEventListener(event, fn){listeners[event]=fn;} };
    const window = {RiskReplay:engine};
    if (!missingData) window.RISK_HISTORY = data;
    vm.runInNewContext(read('risk_education.js'), {document, window, Date:{now:()=>now},
        setInterval(fn){interval=fn;return 1;}, clearInterval(){interval=null;} });
    return {elements, advance(ms){now=ms;if(interval)interval();}, background(ms){now=ms;listeners.visibilitychange();}};
}
for (const [index, outcome] of [[3, '亏损'], [1, '盈利']]) {
    const ui = uiHarness(), el = ui.elements;
    assert(el.riskBuy.disabled && el.riskSell.disabled);
    el.riskCases.children[index].click();
    el.riskStart.click();
    assert(el.riskCases.children.every(button => button.disabled));
    const name = el.riskStockName.textContent;
    el.riskCases.children[(index+1)%4].click();
    assert.equal(el.riskStockName.textContent, name);
    el.riskBuy.click();
    assert.equal(el.riskShares.textContent, '1000 股');
    assert.equal(el.riskCash.textContent, '¥0.00');
    ui.background(600000);
    assert.equal(el.riskTimer.textContent, '00:00');
    assert.equal(el.riskWarning.hidden, false);
    assert(el.riskResult.textContent.includes(outcome));
    assert(el.riskBuy.disabled && el.riskSell.disabled);
    const equity = el.riskEquity.textContent;
    el.riskSell.click(); assert.equal(el.riskEquity.textContent, equity);
    el.riskStart.click();
    assert.equal(el.riskWarning.hidden, true);
    assert.equal(el.riskShares.textContent, '0 股');
    assert.equal(el.riskCash.textContent, '¥100,000.00');
    assert.equal(el.riskTimer.textContent, '10:00');
    el.riskBuy.click(); el.riskSell.click();
    assert.equal(el.riskCash.textContent, '¥100,000.00');
    assert.equal(el.riskShares.textContent, '0 股');
}
const missing = uiHarness(true);
assert(missing.elements.riskStart.disabled && missing.elements.riskBuy.disabled);
assert(missing.elements.riskCaseDescription.textContent.includes('无法载入'));
console.log('PASS: 4 real datasets, exact completed OHLC, partial candles without future extrema, gaps, win/loss warnings, trading, expiry, case lock, restart and missing-data handling.');
