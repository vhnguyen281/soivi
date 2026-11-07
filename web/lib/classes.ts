// Short names of the VNCMA asset classes used in lessons and planners.
export const CLASS_NAMES: Record<string, { vi: string; en: string }> = {
  cash_vnd: { vi: "Tiền gửi", en: "Deposits" },
  gov_bond: { vi: "Trái phiếu chính phủ", en: "Government bonds" },
  corp_bond: { vi: "Trái phiếu doanh nghiệp", en: "Corporate bonds" },
  eq_large: { vi: "Cổ phiếu VN30", en: "VN30 shares" },
  eq_midsmall: { vi: "Cổ phiếu vừa và nhỏ", en: "Mid and small caps" },
  gold: { vi: "Vàng", en: "Gold" },
  usd: { vi: "Đô la Mỹ", en: "US dollar" },
};

export type ClassStat = { id: string; name: string; ret: number; vol: number };
