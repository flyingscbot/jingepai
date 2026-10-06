(() => {
    'use strict';
    const duration = 600;
    const initialCash = 100000;
    const byId = id => document.getElementById(id);
    const money = value => '¥' + value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    // Precompute an independent market: trades never change the price.
    const prices = [100];
    let direction = Math.random() < .5 ? -1 : 1;
    for (let second = 1; second <= duration; second++) {
        if (second % 22 === 0 || Math.random() < .045) direction *= -1;
        const shock = second % 37 === 0 ? -direction * (.12 + Math.random() * .12) : 0;
        const move = direction * (.007 + Math.random() * .012) + (Math.random() - .5) * .025 + shock;
        prices.push(Math.round(Math.max(8, Math.min(650, prices[second - 1] * (1 + move))) * 100) / 100);
    }
    let cash = initialCash, shares = 0, elapsed = 0, ended = false;
    const started = Date.now();
    const chart = byId('riskChart');
    const buy = byId('riskBuy'), sell = byId('riskSell');
    function draw() {
        const candles = [];
        for (let start = 0; start <= elapsed; start += 5) {
            const values = prices.slice(start, Math.min(start + 5, elapsed) + 1);
            candles.push({ open: values[0], close: values[values.length - 1], high: Math.max(...values), low: Math.min(...values) });
        }
        const low = Math.min(...candles.map(c => c.low)) * .9;
        const high = Math.max(...candles.map(c => c.high)) * 1.1;
        const y = value => 300 - (value - low) / (high - low) * 270;
        let markup = '';
        for (let row = 0; row < 5; row++) {
            const value = low + (high - low) * row / 4;
            markup += `<line x1="12" x2="736" y1="${y(value)}" y2="${y(value)}" stroke="#ffffff12"/><text x="744" y="${y(value) + 4}" fill="#999" font-size="11">${value.toFixed(1)}</text>`;
        }
        candles.forEach((c, index) => {
            const x = 16 + index * 5.9, color = c.close >= c.open ? '#f16c75' : '#4dcc9b';
            markup += `<line x1="${x}" x2="${x}" y1="${y(c.high)}" y2="${y(c.low)}" stroke="${color}"/><rect x="${x - 2}" y="${Math.min(y(c.open), y(c.close))}" width="4" height="${Math.max(1.5, Math.abs(y(c.open) - y(c.close)))}" fill="${color}"/>`;
        });
        chart.innerHTML = markup;
    }
    function render() {
        const price = prices[elapsed], profit = cash + shares * price - initialCash;
        byId('riskTimer').textContent = `${String(Math.floor((duration - elapsed) / 60)).padStart(2, '0')}:${String((duration - elapsed) % 60).padStart(2, '0')}`;
        byId('riskPrice').textContent = money(price);
        byId('riskChange').textContent = `${price >= 100 ? '+' : ''}${(price - 100).toFixed(2)}%`;
        byId('riskChange').style.color = price >= 100 ? '#f16c75' : '#4dcc9b';
        byId('riskCash').textContent = money(cash);
        byId('riskShares').textContent = `${shares} 股`;
        byId('riskEquity').textContent = money(cash + shares * price);
        byId('riskProfit').textContent = (profit > 0 ? '+' : '') + money(profit);
        buy.disabled = ended || shares > 0 || cash < price;
        sell.disabled = ended || shares === 0;
        draw();
    }
    function sync() {
        elapsed = Math.min(duration, Math.max(elapsed, Math.floor((Date.now() - started) / 1000)));
        if (elapsed === duration && !ended) {
            ended = true;
            const equity = cash + shares * prices[elapsed];
            byId('riskResult').textContent = `本次模拟总资产 ${money(equity)}，${equity >= initialCash ? '盈利' : '亏损'} ${money(Math.abs(equity - initialCash))}（${((equity / initialCash - 1) * 100).toFixed(2)}%）。持仓按结束价格估值。`;
            byId('riskFeedback').textContent = '体验已结束，交易已停止。请阅读下方风险警示。';
            const warning = byId('riskWarning');
            warning.hidden = false;
            warning.focus({ preventScroll: true });
            warning.scrollIntoView({ behavior: 'smooth', block: 'center' });
            clearInterval(timer);
        }
        render();
    }
    buy.addEventListener('click', () => {
        sync();
        if (buy.disabled) return;
        shares = Math.floor(cash / prices[elapsed]);
        cash = Math.round((cash - shares * prices[elapsed]) * 100) / 100;
        byId('riskFeedback').textContent = `已按 ${money(prices[elapsed])} 买入 ${shares} 股。上涨的冲动之后，你能承受下跌吗？`;
        render();
    });
    sell.addEventListener('click', () => {
        sync();
        if (sell.disabled) return;
        cash = Math.round((cash + shares * prices[elapsed]) * 100) / 100;
        shares = 0;
        byId('riskFeedback').textContent = `已按 ${money(prices[elapsed])} 全部卖出。频繁追涨杀跌可能放大损失。`;
        render();
    });
    const timer = setInterval(sync, 1000);
    document.addEventListener('visibilitychange', sync);
    render();
})();
