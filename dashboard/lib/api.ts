const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { next: { revalidate: 30 } });
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

export interface Overview {
  tracked_wallets: number;
  total_trades: number;
  open_positions: number;
  win_rate: number;
  total_pnl_usd: number;
}

export interface WalletRow {
  id: number;
  address: string;
  label: string | null;
  group_name: string | null;
  score: number | null;
  enabled: boolean;
  flags: string[];
  chains: string[];
}

export interface Trade {
  id: number;
  wallet_id: number;
  chain_id: number;
  token_id: number;
  tx_hash: string | null;
  side: string | null;
  roi_percent: number | null;
  realized_pnl_usd: number | null;
  value_usd: number | null;
  timestamp: string | null;
}

export interface Position {
  id: number;
  wallet_id: number;
  token_id: number;
  status: string;
  average_entry_usd: number | null;
  current_price_usd: number | null;
  current_value_usd: number | null;
  total_invested_usd: number | null;
  realized_pnl_usd: number | null;
  unrealized_pnl_usd: number | null;
  roi_percent: number | null;
  percentage_sold: number | null;
}

export const api = {
  overview: () => get<Overview>("/analytics/overview"),
  wallets: () => get<WalletRow[]>("/wallets/"),
  wallet: (id: number) => get<WalletRow & { metrics: Record<string, number> | null }>(`/wallets/${id}`),
  topTrades: (minRoi = 50) => get<Trade[]>(`/analytics/top_trades?min_roi=${minRoi}`),
  positions: (walletId?: number) =>
    get<Position[]>(`/analytics/positions${walletId ? `?wallet_id=${walletId}` : ""}`),
  ranking: (limit = 20) => get<WalletRow[]>(`/analytics/ranking?limit=${limit}`),
  health: () => get<{ status: string; checks: Record<string, string> }>("/health/"),
};
