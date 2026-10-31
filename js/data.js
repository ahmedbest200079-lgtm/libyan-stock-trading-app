// بيانات تجريبية لشركات افتراضية — ليست بيانات حقيقية لأي شركة مدرجة.
// لاستخدام بيانات سوق ليبيا للأوراق المالية الفعلية استبدل هذه القائمة بنفس البنية.
// القيم المالية بالدينار الليبي.

export const COMPANIES = [
  {
    symbol: 'RYAD', name: 'مصرف الريادة الإسلامي', sector: 'المصارف',
    refPrice: 12.40, volatility: 0.006, activity: 'permissible',
    financials: { sharesOutstanding: 50_000_000, interestBearingDebt: 0, interestBearingDeposits: 0, totalRevenue: 95_000_000, nonPermissibleIncome: 0 },
  },
  {
    symbol: 'AHLI', name: 'المصرف الأهلي التجاري', sector: 'المصارف',
    refPrice: 8.75, volatility: 0.007, activity: 'permissible',
    financials: { sharesOutstanding: 80_000_000, interestBearingDebt: 260_000_000, interestBearingDeposits: 40_000_000, totalRevenue: 120_000_000, nonPermissibleIncome: 14_000_000 },
  },
  {
    symbol: 'TKFL', name: 'الوطنية للتأمين التكافلي', sector: 'التأمين',
    refPrice: 5.20, volatility: 0.008, activity: 'permissible',
    financials: { sharesOutstanding: 20_000_000, interestBearingDebt: 0, interestBearingDeposits: 3_000_000, totalRevenue: 30_000_000, nonPermissibleIncome: 600_000 },
  },
  {
    symbol: 'ARIN', name: 'العربية للتأمين التقليدي', sector: 'التأمين',
    refPrice: 3.90, volatility: 0.009, activity: 'impermissible',
    financials: { sharesOutstanding: 25_000_000, interestBearingDebt: 5_000_000, interestBearingDeposits: 10_000_000, totalRevenue: 28_000_000, nonPermissibleIncome: 4_000_000 },
  },
  {
    symbol: 'JBCM', name: 'أسمنت الجبل', sector: 'الصناعة',
    refPrice: 15.60, volatility: 0.010, activity: 'permissible',
    financials: { sharesOutstanding: 30_000_000, interestBearingDebt: 115_000_000, interestBearingDeposits: 20_000_000, totalRevenue: 210_000_000, nonPermissibleIncome: 4_200_000 },
  },
  {
    symbol: 'OFQT', name: 'شبكة الأفق للاتصالات', sector: 'الاتصالات',
    refPrice: 21.00, volatility: 0.009, activity: 'permissible',
    financials: { sharesOutstanding: 40_000_000, interestBearingDebt: 310_000_000, interestBearingDeposits: 15_000_000, totalRevenue: 400_000_000, nonPermissibleIncome: 6_000_000 },
  },
  {
    symbol: 'SHRA', name: 'طاقة الصحراء للخدمات النفطية', sector: 'الطاقة',
    refPrice: 9.30, volatility: 0.012, activity: 'permissible',
    financials: { sharesOutstanding: 60_000_000, interestBearingDebt: 90_000_000, interestBearingDeposits: 10_000_000, totalRevenue: 330_000_000, nonPermissibleIncome: 1_650_000 },
  },
  {
    symbol: 'KHIR', name: 'الخير للصناعات الغذائية', sector: 'السلع الاستهلاكية',
    refPrice: 6.45, volatility: 0.007, activity: 'permissible',
    financials: { sharesOutstanding: 35_000_000, interestBearingDebt: 20_000_000, interestBearingDeposits: 5_000_000, totalRevenue: 140_000_000, nonPermissibleIncome: 700_000 },
  },
];
