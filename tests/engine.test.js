import { test } from 'node:test';
import assert from 'node:assert/strict';
import { COMPANIES } from '../js/data.js';
import {
  DEFAULT_CONFIG, screenSharia, createPortfolio, executeOrder,
  valuePortfolio, tickPrices, mulberry32, commissionFor,
} from '../js/engine.js';

const get = (s) => COMPANIES.find((c) => c.symbol === s);

test('الفحص الشرعي: الشركات المتوافقة وغير المتوافقة', () => {
  assert.equal(screenSharia(get('RYAD')).compliant, true);
  assert.equal(screenSharia(get('JBCM')).compliant, true); // ديون 24.6% أقل من 30%
  const ahli = screenSharia(get('AHLI'));
  assert.equal(ahli.compliant, false);
  assert.ok(ahli.reasons.some((r) => r.includes('القروض')));
  assert.ok(screenSharia(get('ARIN')).reasons.includes('النشاط الأساسي غير مباح'));
  assert.equal(screenSharia(get('OFQT')).compliant, false);
});

test('التطهير لكل سهم', () => {
  // 4,200,000 / 30,000,000 = 0.14
  assert.equal(screenSharia(get('JBCM')).purificationPerShare, 0.14);
});

test('العمولة تحترم الحد الأدنى', () => {
  assert.equal(commissionFor(100), 1);
  assert.equal(commissionFor(10000), 15);
});

test('الشراء ثم البيع يحسب النقد والربح المحقق', () => {
  let s = createPortfolio();
  const buy = executeOrder(s, { symbol: 'RYAD', side: 'buy', qty: 1000, price: 10, time: 0 });
  assert.ok(buy.ok);
  s = buy.state;
  assert.equal(s.cash, 100000 - 10000 - 15);
  assert.equal(s.holdings.RYAD.qty, 1000);
  assert.equal(s.holdings.RYAD.avgCost, 10.015);

  const sell = executeOrder(s, { symbol: 'RYAD', side: 'sell', qty: 1000, price: 11, time: 1 });
  assert.ok(sell.ok);
  // متحصل 11000 - 16.5 = 10983.5 ، التكلفة 10015
  assert.equal(sell.fill.pnl, 968.5);
  assert.equal(sell.state.realizedPnL, 968.5);
  assert.equal(sell.state.holdings.RYAD, undefined);
  assert.equal(sell.state.orders.length, 2);
});

test('رفض الأوامر غير الصالحة', () => {
  const s = createPortfolio();
  assert.equal(executeOrder(s, { symbol: 'RYAD', side: 'buy', qty: 0, price: 10 }).ok, false);
  assert.equal(executeOrder(s, { symbol: 'RYAD', side: 'buy', qty: 1.5, price: 10 }).ok, false);
  assert.equal(executeOrder(s, { symbol: 'RYAD', side: 'buy', qty: 20000, price: 10 }).error, 'الرصيد النقدي غير كافٍ');
  assert.equal(executeOrder(s, { symbol: 'RYAD', side: 'sell', qty: 1, price: 10 }).ok, false);
});

test('وضع المنع يرفض شراء غير المتوافق ويسمح بالمتوافق', () => {
  const cfg = { ...DEFAULT_CONFIG, shariaMode: 'block' };
  const s = createPortfolio(cfg);
  assert.equal(executeOrder(s, { symbol: 'AHLI', side: 'buy', qty: 10, price: 8 }, cfg, get('AHLI')).ok, false);
  assert.equal(executeOrder(s, { symbol: 'RYAD', side: 'buy', qty: 10, price: 12 }, cfg, get('RYAD')).ok, true);
  // وضع التنبيه يسمح
  assert.equal(executeOrder(s, { symbol: 'AHLI', side: 'buy', qty: 10, price: 8 }, DEFAULT_CONFIG, get('AHLI')).ok, true);
});

test('الحالة الأصلية لا تتغير بعد التنفيذ', () => {
  const s = createPortfolio();
  executeOrder(s, { symbol: 'RYAD', side: 'buy', qty: 10, price: 12 });
  assert.equal(s.cash, 100000);
  assert.deepEqual(s.holdings, {});
});

test('تقييم المحفظة', () => {
  let s = createPortfolio();
  s = executeOrder(s, { symbol: 'JBCM', side: 'buy', qty: 100, price: 15 }).state;
  const v = valuePortfolio(s, { JBCM: 16 }, COMPANIES);
  assert.equal(v.marketValue, 1600);
  assert.equal(v.totalValue, s.cash + 1600);
  assert.ok(Math.abs(v.purification - 14) < 1e-9);
});

test('حركة الأسعار تبقى ضمن النطاق اليومي', () => {
  const rng = mulberry32(42);
  let prices = {};
  for (let i = 0; i < 2000; i++) prices = tickPrices(prices, COMPANIES, rng);
  for (const c of COMPANIES) {
    assert.ok(prices[c.symbol] >= c.refPrice * 0.9 - 0.01);
    assert.ok(prices[c.symbol] <= c.refPrice * 1.1 + 0.01);
  }
});
