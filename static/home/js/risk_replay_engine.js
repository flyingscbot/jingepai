/* Historical candles remain exact; only the within-day teaching path is interpolated. */
(() => {
    'use strict';
    function prepareCase(source) {
        if (!source || !Array.isArray(source.candles) || source.candles.length < 2) throw new Error('缺少历史日线');
        let previousDate = '';
        source.candles.forEach(candle => {
            if (!/^\d{4}-\d{2}-\d{2}$/.test(candle.date) || candle.date <= previousDate) throw new Error('历史日期顺序错误');
            previousDate = candle.date;
            if (![candle.open, candle.high, candle.low, candle.close].every(value => Number.isFinite(value) && value > 0)
                || candle.low > Math.min(candle.open, candle.close) || candle.high < Math.max(candle.open, candle.close)) throw new Error('历史价格无效');
        });
        const scale = 100 / source.candles[0].open;
        const candles = source.candles.map(candle => ({ date: candle.date, open: candle.open * scale,
            high: candle.high * scale, low: candle.low * scale, close: candle.close * scale }));
        return { ...source, candles };
    }
    function snapshot(history, elapsed, duration = 600) {
        if (!Number.isFinite(elapsed) || !Number.isFinite(duration) || duration <= 0) throw new Error('回放时间无效');
        const count = history.candles.length;
        const position = Math.min(1, Math.max(0, elapsed / duration)) * count;
        const completed = Math.min(count, Math.floor(position));
        const shown = history.candles.slice(0, completed);
        let current = history.candles[count - 1];
        if (completed < count) {
            const original = history.candles[completed];
            // The order of intraday extrema is an assumption, not historical tick data.
            const path = original.close >= original.open
                ? [original.open, original.low, original.high, original.close]
                : [original.open, original.high, original.low, original.close];
            const progress = (position - completed) * 3;
            const segment = Math.min(2, Math.floor(progress));
            const price = path[segment] + (path[segment + 1] - path[segment]) * (progress - segment);
            const visited = [...path.slice(0, segment + 1), price];
            current = { date: original.date, open: original.open, close: price,
                high: Math.max(...visited), low: Math.min(...visited) };
            shown.push(current);
        }
        return { candles: shown, price: Math.round(current.close * 100) / 100,
            date: current.date, completed, total: count };
    }
    const api = Object.freeze({ prepareCase, snapshot });
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    else window.RiskReplay = api;
})();
