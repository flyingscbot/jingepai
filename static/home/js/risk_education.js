(() => {
    'use strict';
    const duration = 600, initialCash = 100000;
    const byId = id => document.getElementById(id);
    const money = value => '¥' + value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const rounded = value => Math.round(value * 100) / 100;
    const chart = byId('riskChart'), buy = byId('riskBuy'), sell = byId('riskSell'), start = byId('riskStart');
    let cases;
    try {
        cases = window.RISK_HISTORY.cases.map(window.RiskReplay.prepareCase);
        if (!cases.length) throw new Error('没有历史案例');
    } catch (error) {
        byId('riskCaseDescription').textContent = '历史行情暂时无法载入，请刷新页面后重试。';
        return;
    }
    let selected = cases[0], state = 'ready', cash = initialCash, shares = 0;
    let started = 0, elapsed = 0, timer = null, tradeCount = 0;
    let market = window.RiskReplay.snapshot(selected, 0);
    const caseButtons = [];
    cases.forEach(history => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'risk-case-option';
        const title = document.createElement('strong'), subtitle = document.createElement('span');
        title.textContent = history.name;
        subtitle.textContent = history.label;
        button.append(title, subtitle);
        button.addEventListener('click', () => {
            if (state !== 'running') select(history);
        });
        byId('riskCases').append(button);
        caseButtons.push({ button, history });
    });
    function draw() {
        const candles = market.candles;
        const low = Math.min(...candles.map(c => c.low)) * .9;
        const high = Math.max(...candles.map(c => c.high)) * 1.1;
        const y = value => 300 - (value - low) / (high - low) * 270;
        const step = 720 / selected.candles.length;
        let markup = '';
        for (let row = 0; row < 5; row++) {
            const value = low + (high - low) * row / 4;
            markup += `<line x1="12" x2="736" y1="${y(value)}" y2="${y(value)}" stroke="#ffffff12"/><text x="744" y="${y(value) + 4}" fill="#999" font-size="11">${value.toFixed(1)}</text>`;
        }
        candles.forEach((c, index) => {
            const x = 12 + (index + .5) * step, width = Math.min(14, step * .65);
            const color = c.close >= c.open ? '#f16c75' : '#4dcc9b';
            markup += `<line x1="${x}" x2="${x}" y1="${y(c.high)}" y2="${y(c.low)}" stroke="${color}"/><rect x="${x - width / 2}" y="${Math.min(y(c.open), y(c.close))}" width="${width}" height="${Math.max(1.5, Math.abs(y(c.open) - y(c.close)))}" fill="${color}"/>`;
        });
        chart.innerHTML = markup;
    }
    function render() {
        const price = market.price, profit = rounded(cash + shares * price - initialCash);
        const remaining = Math.ceil(duration - elapsed);
        byId('riskTimer').textContent = `${String(Math.floor(remaining / 60)).padStart(2, '0')}:${String(remaining % 60).padStart(2, '0')}`;
        byId('riskPrice').textContent = money(price);
        byId('riskChange').textContent = `${price >= 100 ? '+' : ''}${(price - 100).toFixed(2)}%`;
        byId('riskChange').style.color = price >= 100 ? '#f16c75' : '#4dcc9b';
        byId('riskCash').textContent = money(cash);
        byId('riskShares').textContent = `${shares} 股`;
        byId('riskEquity').textContent = money(cash + shares * price);
        byId('riskProfit').textContent = (profit > 0 ? '+' : '') + money(profit);
        byId('riskReplayDate').textContent = `${market.date} · 已回放 ${market.completed} / ${market.total} 个交易日`;
        buy.disabled = state !== 'running' || shares > 0 || cash < price;
        sell.disabled = state !== 'running' || shares === 0;
        draw();
    }
    function select(history) {
        selected = history;
        state = 'ready'; cash = initialCash; shares = 0; elapsed = 0; tradeCount = 0;
        market = window.RiskReplay.snapshot(selected, 0);
        byId('riskStockName').textContent = history.name;
        byId('riskStockMeta').textContent = `${history.symbol} · 历史日线 / 虚拟记账`;
        byId('riskCaseDescription').textContent = history.description;
        byId('riskRangeStart').textContent = history.candles[0].date;
        byId('riskRangeEnd').textContent = history.candles[history.candles.length - 1].date;
        byId('riskCandleSpeed').textContent = `约 ${(duration / history.candles.length).toFixed(1)} 秒 / 历史交易日`;
        byId('riskState').textContent = '准备体验';
        byId('riskFeedback').textContent = '点击开始，使用虚拟资金体验这段历史。';
        byId('riskWarning').hidden = true;
        byId('riskDataSource').href = history.historySource;
        byId('riskEventSource').href = history.eventSource;
        byId('riskEventSource').textContent = history.eventSourceLabel;
        byId('riskDataSnapshot').textContent = `数据快照：${window.RISK_HISTORY.retrievedAt.slice(0, 10)} · ${history.candles.length} 根真实日 K 线。`;
        chart.setAttribute('aria-label', `${history.name}历史行情 K 线回放`);
        caseButtons.forEach(({ button, history: item }) => {
            button.disabled = false;
            button.setAttribute('aria-pressed', String(item.id === history.id));
        });
        start.disabled = false; start.hidden = false;
        start.textContent = '开始 10 分钟体验';
        render();
    }
    function finish() {
        state = 'ended';
        clearInterval(timer); timer = null;
        const equity = rounded(cash + shares * market.price);
        const outcome = equity === initialCash ? '盈亏持平' : `${equity > initialCash ? '盈利' : '亏损'} ${money(Math.abs(equity - initialCash))}`;
        byId('riskResult').textContent = `本次模拟总资产 ${money(equity)}，${outcome}（${((equity / initialCash - 1) * 100).toFixed(2)}%）。完成 ${tradeCount} 次买卖；剩余持仓按结束价格估值。`;
        byId('riskCaseLesson').textContent = selected.lesson;
        byId('riskFeedback').textContent = '体验已结束，交易已停止。即使盈利，也请阅读风险警示。';
        byId('riskState').textContent = '体验结束';
        caseButtons.forEach(({ button }) => { button.disabled = false; });
        start.hidden = false; start.disabled = false; start.textContent = '重新体验 10 分钟';
        const warning = byId('riskWarning');
        warning.hidden = false;
        warning.focus({ preventScroll: true });
        warning.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    function sync() {
        if (state !== 'running') return;
        elapsed = Math.min(duration, Math.max(elapsed, (Date.now() - started) / 1000));
        market = window.RiskReplay.snapshot(selected, elapsed);
        if (elapsed >= duration) finish();
        render();
    }
    start.addEventListener('click', () => {
        if (state === 'running') return;
        select(selected);
        state = 'running'; started = Date.now();
        start.hidden = true; start.disabled = true;
        caseButtons.forEach(({ button }) => { button.disabled = true; });
        byId('riskState').textContent = '回放进行中';
        byId('riskFeedback').textContent = '行情回放已开始。你会追涨，还是能承受下跌？';
        timer = setInterval(sync, 1000);
        render();
    });
    buy.addEventListener('click', () => {
        sync();
        if (buy.disabled) return;
        shares = Math.floor(cash / market.price);
        cash = rounded(cash - shares * market.price);
        tradeCount++;
        byId('riskFeedback').textContent = `已按虚拟价格 ${money(market.price)} 买入 ${shares} 股。上涨之后，你能承受下跌吗？`;
        render();
    });
    sell.addEventListener('click', () => {
        sync();
        if (sell.disabled) return;
        cash = rounded(cash + shares * market.price); shares = 0; tradeCount++;
        byId('riskFeedback').textContent = `已按虚拟价格 ${money(market.price)} 全部卖出。频繁追涨杀跌可能放大损失。`;
        render();
    });
    document.addEventListener('visibilitychange', sync);
    select(selected);
})();
