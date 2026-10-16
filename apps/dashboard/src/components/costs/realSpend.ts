import type { CostBreakdownRow, CostOverview, CreditBalance } from "@cineforge/schemas";

/** Mock providers are named ``mock-*``. Everything else is real (paid or free). */
export function isMockProvider(name: string): boolean {
  return name.startsWith("mock-");
}

function sumField(rows: CostBreakdownRow[], field: "estimated" | "reserved" | "actual"): number {
  return rows.reduce((total, row) => total + (Number(row[field]) || 0), 0);
}

export type RealSpendOverview = CostOverview & {
  /** Mock-provider actual spend hidden from the main totals (0 when nothing was hidden). */
  excluded_mock_actual: number;
};

/**
 * When any real provider has been used, show only that spend on the Costs page.
 * Pure mock tenants still see the full simulated ledger (with the Simulated badge).
 */
export function realSpendOverview(data: CostOverview): RealSpendOverview {
  const providers = data.by_provider ?? [];
  const real = providers.filter((row) => !isMockProvider(row.key));
  const mock = providers.filter((row) => isMockProvider(row.key));
  const mockActual = sumField(mock, "actual");

  if (data.simulated !== false || real.length === 0) {
    return { ...data, excluded_mock_actual: 0 };
  }

  return {
    ...data,
    total_estimated: sumField(real, "estimated"),
    total_reserved: sumField(real, "reserved"),
    total_actual: sumField(real, "actual"),
    by_provider: real,
    // Per-production / per-agent rows still mix mock events; hide until the API splits them.
    by_production: [],
    by_agent: [],
    credit_balances: realCreditBalances(data.credit_balances),
    excluded_mock_actual: mockActual,
  };
}

export function realCreditBalances(balances: CreditBalance[] | undefined): CreditBalance[] {
  return (balances ?? []).filter((b) => !isMockProvider(b.provider));
}
