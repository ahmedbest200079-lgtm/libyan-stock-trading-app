// منطق المحاكاة: الفحص الشرعي، تنفيذ الأوامر، تقييم المحفظة، وحركة الأسعار.
// كل الدوال هنا نقية (لا تعتمد على المتصفح) لكي يمكن اختبارها في Node.

export const DEFAULT_CONFIG = {
  initialCash: 100000,      // الرصيد الافتراضي الابتدائي (د.ل)
  commissionRate: 0.0015,   // عمولة الوساطة كنسبة من قيمة الصفقة (قابلة للتعديل)
  minCommission: 1,         // الحد الأدنى للعمولة (د.ل)
  priceBand: 0.10,          // أقصى تغير يومي عن سعر الإغلاق المرجعي (قابل للتعديل)
  shariaMode: 'warn',       // 'warn' = تنبيه فقط، 'block' = منع شراء الأسهم غير المتوافقة
};

// معايير الفحص الشرعي وفق معيار هيئة المحاسبة والمراجعة (AAOIFI) رقم 21
export const SHARIA_LIMITS = {
  debtToMarketCap: 0.30,      // القروض الربوية / القيمة السوقية
  depositsToMarketCap: 0.30,  // الودائع الربوية / القيمة السوقية
  nonPermissibleIncome: 0.05, // الإيراد غير المباح / إجمالي الإيرادات
};

const round2 = (n) => Math.round(n * 100) / 100;

export function screenSharia(company) {
  const f = company.financials;
  const marketCap = company.refPrice * f.sharesOutstanding;
  const ratios = {
    debt: f.interestBearingDebt / marketCap,
    deposits: f.interestBearingDeposits / marketCap,
    income: f.totalRevenue > 0 ? f.nonPermissibleIncome / f.totalRevenue : 0,
  };
  const reasons = [];
  if (company.activity !== 'permissible') reasons.push('النشاط الأساسي غير مباح');
  if (ratios.debt >= SHARIA_LIMITS.debtToMarketCap) reasons.push('نسبة القروض الربوية تتجاوز 30%');
  if (ratios.deposits >= SHARIA_LIMITS.depositsToMarketCap) reasons.push('نسبة الودائع الربوية تتجاوز 30%');
  if (ratios.income >= SHARIA_LIMITS.nonPermissibleIncome) reasons.push('الإيراد غير المباح يتجاوز 5%');
  return {
    compliant: reasons.length === 0,
    ratios,
    reasons,
    // مقدار التطهير لكل سهم = الإيراد غير المباح ÷ عدد الأسهم
    purificationPerShare: f.nonPermissibleIncome / f.sharesOutstanding,
  };
}

export function commissionFor(value, config = DEFAULT_CONFIG) {
  return round2(Math.max(value * config.commissionRate, config.minCommission));
}

export function createPortfolio(config = DEFAULT_CONFIG) {
  return { cash: config.initialCash, holdings: {}, orders: [], realizedPnL: 0 };
}

// ينفذ أمراً بسعر السوق ويعيد حالة جديدة دون تعديل الحالة القديمة.
export function executeOrder(state, order, config = DEFAULT_CONFIG, company = null) {
  const { symbol, side, price } = order;
  const qty = Number(order.qty);
  if (!Number.isInteger(qty) || qty <= 0) return { ok: false, error: 'الكمية يجب أن تكون عدداً صحيحاً موجباً' };
  if (!(price > 0)) return { ok: false, error: 'سعر غير صالح' };
  if (side !== 'buy' && side !== 'sell') return { ok: false, error: 'نوع الأمر غير معروف' };

  const value = round2(qty * price);
  const commission = commissionFor(value, config);
  const holdings = { ...state.holdings };
  const pos = holdings[symbol] ? { ...holdings[symbol] } : { qty: 0, avgCost: 0 };
  let cash = state.cash;
  let realizedPnL = state.realizedPnL;
  let pnl = 0;

  if (side === 'buy') {
    if (company && config.shariaMode === 'block' && !screenSharia(company).compliant) {
      return { ok: false, error: 'السهم غير متوافق مع الضوابط الشرعية (وضع المنع مفعّل)' };
    }
    const total = round2(value + commission);
    if (total > cash + 1e-9) return { ok: false, error: 'الرصيد النقدي غير كافٍ' };
    // متوسط التكلفة يشمل العمولة
    pos.avgCost = (pos.avgCost * pos.qty + total) / (pos.qty + qty);
    pos.qty += qty;
    cash = round2(cash - total);
    holdings[symbol] = pos;
  } else {
    if (qty > pos.qty) return { ok: false, error: 'الكمية المطلوبة أكبر من الأسهم المملوكة' };
    const proceeds = round2(value - commission);
    pnl = round2(proceeds - pos.avgCost * qty);
    realizedPnL = round2(realizedPnL + pnl);
    cash = round2(cash + proceeds);
    pos.qty -= qty;
    if (pos.qty === 0) delete holdings[symbol];
    else holdings[symbol] = pos;
  }

  const fill = {
    id: state.orders.length + 1,
    time: order.time ?? Date.now(),
    symbol, side, qty, price, value, commission, pnl,
  };
  return { ok: true, fill, state: { cash, holdings, realizedPnL, orders: [...state.orders, fill] } };
}

export function valuePortfolio(state, prices, companies = []) {
  const bySymbol = Object.fromEntries(companies.map((c) => [c.symbol, c]));
  let marketValue = 0;
  let costBasis = 0;
  let purification = 0;
  const positions = Object.entries(state.holdings).map(([symbol, pos]) => {
    const price = prices[symbol] ?? 0;
    const mv = pos.qty * price;
    const cost = pos.qty * pos.avgCost;
    marketValue += mv;
    costBasis += cost;
    const company = bySymbol[symbol];
    const purify = company ? screenSharia(company).purificationPerShare * pos.qty : 0;
    purification += purify;
    return { symbol, qty: pos.qty, avgCost: pos.avgCost, price, marketValue: mv, unrealized: mv - cost, purification: purify };
  });
  return {
    positions,
    marketValue,
    unrealized: marketValue - costBasis,
    totalValue: state.cash + marketValue,
    purification,
  };
}

// مولد أرقام عشوائية قابل للتكرار (للاختبارات ولإعادة إنتاج المحاكاة)
export function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// حركة عشوائية للأسعار محصورة ضمن النطاق السعري اليومي
export function tickPrices(prices, companies, rng = Math.random, config = DEFAULT_CONFIG) {
  const next = {};
  for (const c of companies) {
    const current = prices[c.symbol] ?? c.refPrice;
    const shock = (rng() * 2 - 1) * c.volatility;
    const lo = c.refPrice * (1 - config.priceBand);
    const hi = c.refPrice * (1 + config.priceBand);
    next[c.symbol] = round2(Math.min(hi, Math.max(lo, current * (1 + shock))));
  }
  return next;
}
