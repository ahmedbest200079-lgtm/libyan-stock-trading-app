import { COMPANIES } from './data.js';
import {
  DEFAULT_CONFIG, screenSharia, createPortfolio, executeOrder,
  valuePortfolio, tickPrices, commissionFor,
} from './engine.js';

const STORAGE_KEY = 'lsm-sim-v1';
const TICK_MS = 3000;
const $ = (id) => document.getElementById(id);
// عزل اتجاه الأرقام (LRI…PDI) حتى تظهر الإشارة السالبة بشكل صحيح داخل النص العربي
const fmt = (n, d = 2) => `\u2066${Number(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })}\u2069`;
const lyd = (n) => `${fmt(n)} د.ل`;
const pct = (n) => `\u2066${n >= 0 ? '+' : ''}${(n * 100).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%\u2069`;
const cls = (n) => (n > 0 ? 'up' : n < 0 ? 'down' : '');
const bySymbol = Object.fromEntries(COMPANIES.map((c) => [c.symbol, c]));
const sharia = Object.fromEntries(COMPANIES.map((c) => [c.symbol, screenSharia(c)]));

let config = { ...DEFAULT_CONFIG };
let portfolio = createPortfolio(config);
let prices = Object.fromEntries(COMPANIES.map((c) => [c.symbol, c.refPrice]));
let running = true;
let activeSymbol = null;

function load() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (saved) {
      config = { ...DEFAULT_CONFIG, ...saved.config };
      portfolio = saved.portfolio ?? portfolio;
      prices = { ...prices, ...saved.prices };
    }
  } catch { /* التخزين غير متاح: نبدأ بمحفظة جديدة */ }
}
function save() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify({ config, portfolio, prices })); } catch { /* تجاهل */ }
}

function toast(msg) {
  const t = $('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.remove('show'), 2500);
}

function renderStats() {
  const v = valuePortfolio(portfolio, prices, COMPANIES);
  const ret = (v.totalValue - config.initialCash) / config.initialCash;
  $('stat-cash').textContent = lyd(portfolio.cash);
  $('stat-mv').textContent = lyd(v.marketValue);
  $('stat-total').textContent = lyd(v.totalValue);
  const r = $('stat-return');
  r.textContent = pct(ret);
  r.className = cls(ret);
  return v;
}

function renderMarket() {
  const onlyOk = $('filter-compliant').checked;
  $('market-body').innerHTML = COMPANIES
    .filter((c) => !onlyOk || sharia[c.symbol].compliant)
    .map((c) => {
      const p = prices[c.symbol];
      const ch = (p - c.refPrice) / c.refPrice;
      const s = sharia[c.symbol];
      return `<tr>
        <td><strong>${c.symbol}</strong></td><td>${c.name}</td><td>${c.sector}</td>
        <td class="num">${fmt(p)}</td><td class="num ${cls(ch)}">${pct(ch)}</td>
        <td><span class="badge ${s.compliant ? 'ok' : 'no'}">${s.compliant ? 'متوافق' : 'غير متوافق'}</span></td>
        <td><button class="btn small" data-trade="${c.symbol}">تداول</button></td>
      </tr>`;
    }).join('');
}

function renderPortfolio(v) {
  const body = $('portfolio-body');
  if (!v.positions.length) {
    body.innerHTML = '<tr><td colspan="8" class="empty">لا توجد أسهم في المحفظة بعد. ابدأ من تبويب السوق.</td></tr>';
  } else {
    body.innerHTML = v.positions.map((p) => `<tr>
      <td><strong>${p.symbol}</strong></td><td class="num">${fmt(p.qty, 0)}</td>
      <td class="num">${fmt(p.avgCost, 3)}</td><td class="num">${fmt(p.price)}</td>
      <td class="num">${fmt(p.marketValue)}</td><td class="num ${cls(p.unrealized)}">${fmt(p.unrealized)}</td>
      <td class="num">${fmt(p.purification)}</td>
      <td><button class="btn small ghost" data-trade="${p.symbol}">تداول</button></td>
    </tr>`).join('');
  }
  $('portfolio-summary').innerHTML =
    `ربح/خسارة غير محققة: <span class="${cls(v.unrealized)}">${lyd(v.unrealized)}</span> · ` +
    `ربح/خسارة محققة: <span class="${cls(portfolio.realizedPnL)}">${lyd(portfolio.realizedPnL)}</span> · ` +
    `إجمالي مبلغ التطهير التقديري: ${lyd(v.purification)}`;
}

function renderHistory() {
  const body = $('history-body');
  if (!portfolio.orders.length) {
    body.innerHTML = '<tr><td colspan="9" class="empty">لا توجد أوامر منفذة.</td></tr>';
    return;
  }
  body.innerHTML = [...portfolio.orders].reverse().map((o) => `<tr>
    <td>${o.id}</td><td>${new Date(o.time).toLocaleString('ar-LY')}</td>
    <td class="${o.side === 'buy' ? 'up' : 'down'}">${o.side === 'buy' ? 'شراء' : 'بيع'}</td>
    <td>${o.symbol}</td><td class="num">${fmt(o.qty, 0)}</td><td class="num">${fmt(o.price)}</td>
    <td class="num">${fmt(o.value)}</td><td class="num">${fmt(o.commission)}</td>
    <td class="num ${cls(o.pnl)}">${o.side === 'sell' ? fmt(o.pnl) : '—'}</td>
  </tr>`).join('');
}

function render() {
  const v = renderStats();
  renderMarket();
  renderPortfolio(v);
  renderHistory();
}

// ===== نافذة التداول =====
function shariaHtml(c) {
  const s = sharia[c.symbol];
  const line = (label, val, limit) => `${label}: <strong class="${val >= limit ? 'down' : 'up'}">${fmt(val * 100)}%</strong> (الحد ${limit * 100}%)`;
  return `<span class="badge ${s.compliant ? 'ok' : 'no'}">${s.compliant ? 'متوافق مع الضوابط الشرعية' : 'غير متوافق'}</span><br>
    النشاط: ${c.activity === 'permissible' ? 'مباح' : 'غير مباح'}<br>
    ${line('القروض الربوية / القيمة السوقية', s.ratios.debt, 0.3)}<br>
    ${line('الودائع الربوية / القيمة السوقية', s.ratios.deposits, 0.3)}<br>
    ${line('الإيراد غير المباح / الإيرادات', s.ratios.income, 0.05)}<br>
    التطهير لكل سهم: ${fmt(s.purificationPerShare, 4)} د.ل
    ${s.reasons.length ? `<br><span class="down">${s.reasons.join(' · ')}</span>` : ''}`;
}

function updatePreview() {
  if (!activeSymbol) return;
  const form = $('trade-form');
  const qty = Number(form.qty.value) || 0;
  const side = form.side.value;
  const price = prices[activeSymbol];
  const value = qty * price;
  const comm = qty > 0 ? commissionFor(value, config) : 0;
  const held = portfolio.holdings[activeSymbol]?.qty ?? 0;
  $('trade-title').textContent = `${bySymbol[activeSymbol].name} (${activeSymbol}) — ${fmt(price)} د.ل`;
  $('trade-preview').innerHTML =
    `القيمة: ${lyd(value)} · العمولة: ${lyd(comm)} · ${side === 'buy' ? 'الإجمالي المدفوع' : 'صافي المتحصل'}: <strong>${lyd(side === 'buy' ? value + comm : value - comm)}</strong><br>` +
    `المملوك حالياً: ${fmt(held, 0)} سهم · النقد المتاح: ${lyd(portfolio.cash)}`;
}

function openTrade(symbol) {
  activeSymbol = symbol;
  $('sharia-box').innerHTML = shariaHtml(bySymbol[symbol]);
  $('trade-error').textContent = '';
  updatePreview();
  $('trade-dialog').showModal();
}

function submitTrade(e) {
  e.preventDefault();
  const form = $('trade-form');
  const side = form.side.value;
  const c = bySymbol[activeSymbol];
  const res = executeOrder(portfolio, { symbol: activeSymbol, side, qty: Number(form.qty.value), price: prices[activeSymbol] }, config, c);
  if (!res.ok) { $('trade-error').textContent = res.error; return; }
  portfolio = res.state;
  save();
  $('trade-dialog').close();
  const warn = side === 'buy' && !sharia[activeSymbol].compliant ? ' — تنبيه: السهم غير متوافق شرعياً' : '';
  toast(`تم ${side === 'buy' ? 'شراء' : 'بيع'} ${fmt(res.fill.qty, 0)} سهم ${activeSymbol}${warn}`);
  render();
}

// ===== الإعدادات =====
function fillSettings() {
  const f = $('settings-form');
  f.commissionRate.value = +(config.commissionRate * 100).toFixed(4);
  f.minCommission.value = config.minCommission;
  f.priceBand.value = +(config.priceBand * 100).toFixed(2);
  f.shariaMode.value = config.shariaMode;
}

function bind() {
  document.querySelectorAll('.tab').forEach((b) => b.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((x) => x.classList.toggle('active', x === b));
    document.querySelectorAll('.panel').forEach((p) => p.classList.toggle('active', p.id === `tab-${b.dataset.tab}`));
  }));
  document.body.addEventListener('click', (e) => {
    const t = e.target.closest('[data-trade]');
    if (t) openTrade(t.dataset.trade);
  });
  $('filter-compliant').addEventListener('change', renderMarket);
  $('toggle-sim').addEventListener('click', () => {
    running = !running;
    $('toggle-sim').textContent = running ? 'إيقاف الحركة' : 'تشغيل الحركة';
  });
  $('trade-form').addEventListener('submit', submitTrade);
  $('trade-form').addEventListener('input', updatePreview);
  $('trade-cancel').addEventListener('click', () => $('trade-dialog').close());
  $('trade-dialog').addEventListener('close', () => { activeSymbol = null; });
  $('settings-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const f = e.target;
    config = {
      ...config,
      commissionRate: Math.max(0, Number(f.commissionRate.value) / 100),
      minCommission: Math.max(0, Number(f.minCommission.value)),
      priceBand: Math.min(0.5, Math.max(0.01, Number(f.priceBand.value) / 100)),
      shariaMode: f.shariaMode.value,
    };
    save();
    toast('تم حفظ الإعدادات');
  });
  $('reset').addEventListener('click', () => {
    if (!confirm('سيتم حذف جميع الصفقات وإعادة الرصيد إلى القيمة الابتدائية. متابعة؟')) return;
    portfolio = createPortfolio(config);
    prices = Object.fromEntries(COMPANIES.map((c) => [c.symbol, c.refPrice]));
    save();
    render();
    toast('تمت إعادة تعيين المحفظة');
  });
}

load();
bind();
fillSettings();
render();
setInterval(() => {
  if (!running) return;
  prices = tickPrices(prices, COMPANIES, Math.random, config);
  save();
  renderStats();
  renderMarket();
  if (document.querySelector('#tab-portfolio.active')) renderPortfolio(valuePortfolio(portfolio, prices, COMPANIES));
  updatePreview();
}, TICK_MS);
