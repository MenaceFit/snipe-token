"""Initial schema

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chains",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chain_key", sa.String(50), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("chain_type", sa.String(20), nullable=False),
        sa.Column("native_token_address", sa.String(100), nullable=True),
        sa.Column("explorer_url", sa.String(200), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chain_key"),
    )

    op.create_table(
        "wallets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("address", sa.String(100), nullable=False),
        sa.Column("label", sa.String(200), nullable=True),
        sa.Column("group_name", sa.String(100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("smart_money_score", sa.Float(), nullable=True),
        sa.Column("risk_flags", postgresql.JSONB(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("address"),
    )
    op.create_index("ix_wallets_address", "wallets", ["address"])
    op.create_index("ix_wallets_score", "wallets", ["smart_money_score"])

    op.create_table(
        "wallet_chains",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("wallet_id", sa.Integer(), sa.ForeignKey("wallets.id"), nullable=False),
        sa.Column("chain_id", sa.Integer(), sa.ForeignKey("chains.id"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("address", sa.String(100), nullable=False),
        sa.Column("chain_id", sa.Integer(), sa.ForeignKey("chains.id"), nullable=False),
        sa.Column("symbol", sa.String(50), nullable=True),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("decimals", sa.Integer(), nullable=True),
        sa.Column("is_verified", sa.Boolean(), nullable=True),
        sa.Column("is_honeypot", sa.Boolean(), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("logo_url", sa.String(500), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("address", "chain_id", name="uq_token_address_chain"),
    )
    op.create_index("ix_tokens_address", "tokens", ["address"])

    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tx_hash", sa.String(100), nullable=False),
        sa.Column("chain_id", sa.Integer(), sa.ForeignKey("chains.id"), nullable=False),
        sa.Column("wallet_id", sa.Integer(), sa.ForeignKey("wallets.id"), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=True),
        sa.Column("block_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("gas_used", sa.BigInteger(), nullable=True),
        sa.Column("gas_price_wei", sa.BigInteger(), nullable=True),
        sa.Column("gas_cost_usd", sa.Float(), nullable=True),
        sa.Column("t0_block_ms", sa.BigInteger(), nullable=True),
        sa.Column("t1_received_ms", sa.BigInteger(), nullable=True),
        sa.Column("t2_parsed_ms", sa.BigInteger(), nullable=True),
        sa.Column("t3_classified_ms", sa.BigInteger(), nullable=True),
        sa.Column("t4_priced_ms", sa.BigInteger(), nullable=True),
        sa.Column("t5_stored_ms", sa.BigInteger(), nullable=True),
        sa.Column("t6_alerted_ms", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tx_hash", "chain_id", name="uq_tx_hash_chain"),
    )
    op.create_index("ix_transactions_tx_hash", "transactions", ["tx_hash"])
    op.create_index("ix_transactions_wallet", "transactions", ["wallet_id"])

    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.Integer(), sa.ForeignKey("transactions.id"), nullable=True),
        sa.Column("wallet_id", sa.Integer(), sa.ForeignKey("wallets.id"), nullable=False),
        sa.Column("chain_id", sa.Integer(), sa.ForeignKey("chains.id"), nullable=False),
        sa.Column("token_id", sa.Integer(), sa.ForeignKey("tokens.id"), nullable=False),
        sa.Column("tx_hash", sa.String(100), nullable=True),
        sa.Column("side", sa.String(10), nullable=True),
        sa.Column("trade_type", sa.String(20), nullable=True),
        sa.Column("quantity", sa.Float(), nullable=True),
        sa.Column("price_usd", sa.Float(), nullable=True),
        sa.Column("value_usd", sa.Float(), nullable=True),
        sa.Column("gas_cost_usd", sa.Float(), nullable=True),
        sa.Column("realized_pnl_usd", sa.Float(), nullable=True),
        sa.Column("roi_percent", sa.Float(), nullable=True),
        sa.Column("token_in_address", sa.String(100), nullable=True),
        sa.Column("token_out_address", sa.String(100), nullable=True),
        sa.Column("amount_in", sa.Float(), nullable=True),
        sa.Column("amount_out", sa.Float(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trades_wallet", "trades", ["wallet_id"])
    op.create_index("ix_trades_token", "trades", ["token_id"])
    op.create_index("ix_trades_timestamp", "trades", ["timestamp"])

    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("wallet_id", sa.Integer(), sa.ForeignKey("wallets.id"), nullable=False),
        sa.Column("token_id", sa.Integer(), sa.ForeignKey("tokens.id"), nullable=False),
        sa.Column("chain_id", sa.Integer(), sa.ForeignKey("chains.id"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
        sa.Column("quantity_remaining", sa.Float(), nullable=True),
        sa.Column("average_entry_usd", sa.Float(), nullable=True),
        sa.Column("current_price_usd", sa.Float(), nullable=True),
        sa.Column("current_value_usd", sa.Float(), nullable=True),
        sa.Column("total_invested_usd", sa.Float(), nullable=True),
        sa.Column("realized_pnl_usd", sa.Float(), nullable=True),
        sa.Column("unrealized_pnl_usd", sa.Float(), nullable=True),
        sa.Column("roi_percent", sa.Float(), nullable=True),
        sa.Column("percentage_sold", sa.Float(), nullable=True),
        sa.Column("fifo_lots", postgresql.JSONB(), nullable=True),
        sa.Column("first_buy_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_trade_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("wallet_id", "token_id", name="uq_position_wallet_token"),
    )
    op.create_index("ix_positions_wallet", "positions", ["wallet_id"])
    op.create_index("ix_positions_status", "positions", ["status"])

    op.create_table(
        "wallet_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("wallet_id", sa.Integer(), sa.ForeignKey("wallets.id"), nullable=False),
        sa.Column("chain_key", sa.String(50), nullable=True),
        sa.Column("total_trades", sa.Integer(), nullable=True),
        sa.Column("win_rate", sa.Float(), nullable=True),
        sa.Column("average_roi", sa.Float(), nullable=True),
        sa.Column("median_roi", sa.Float(), nullable=True),
        sa.Column("total_pnl_usd", sa.Float(), nullable=True),
        sa.Column("max_drawdown", sa.Float(), nullable=True),
        sa.Column("profit_factor", sa.Float(), nullable=True),
        sa.Column("best_trade_roi", sa.Float(), nullable=True),
        sa.Column("worst_trade_roi", sa.Float(), nullable=True),
        sa.Column("avg_hold_seconds", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("wallet_id", sa.Integer(), sa.ForeignKey("wallets.id"), nullable=True),
        sa.Column("trade_id", sa.Integer(), sa.ForeignKey("trades.id"), nullable=True),
        sa.Column("alert_type", sa.String(30), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "copy_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("wallet_id", sa.Integer(), sa.ForeignKey("wallets.id"), nullable=True),
        sa.Column("trade_id", sa.Integer(), sa.ForeignKey("trades.id"), nullable=True),
        sa.Column("token_id", sa.Integer(), sa.ForeignKey("tokens.id"), nullable=True),
        sa.Column("side", sa.String(10), nullable=True),
        sa.Column("mode", sa.String(10), nullable=True),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column("amount_usd", sa.Float(), nullable=True),
        sa.Column("executed_price_usd", sa.Float(), nullable=True),
        sa.Column("tx_hash", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "wallet_clusters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("wallet_ids", postgresql.JSONB(), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "risk_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("wallet_id", sa.Integer(), sa.ForeignKey("wallets.id"), nullable=True),
        sa.Column("token_id", sa.Integer(), sa.ForeignKey("tokens.id"), nullable=True),
        sa.Column("chain_id", sa.Integer(), sa.ForeignKey("chains.id"), nullable=True),
        sa.Column("risk_level", sa.String(20), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("flags", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    for table in (
        "risk_events", "wallet_clusters", "copy_orders", "alerts",
        "wallet_metrics", "positions", "trades", "transactions",
        "tokens", "wallet_chains", "wallets", "chains",
    ):
        op.drop_table(table)
