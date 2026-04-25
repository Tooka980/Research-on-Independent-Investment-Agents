# Virtual Order History

All records are simulated inside this application. No broker API or real order is used.

## Orders
- `vord-643a7eec8f564a0cb3ba0c3503950cf1` 6758.T buy/market status=approved_for_simulation created=2026/04/24 22:22:19 executed=pending decision=dc-virtual-6758-t evidence=ev-price-6758.T, ev-analysis-6758.T
- `vord-643a7eec8f564a0cb3ba0c3503950cf1` 6758.T buy/market status=simulated_filled created=2026/04/24 22:22:19 executed=2026/04/24 22:22:19 decision=dc-virtual-6758-t evidence=ev-price-6758.T, ev-analysis-6758.T
- `vord-59ef947d3b0141b49fb7382418617212` 9984.T buy/rebalance status=approved_for_simulation created=2026/04/24 22:55:33 executed=pending decision=dc-research-9984-t evidence=ev-news-9984-t-0, ev-company-9984-t
- `vord-59ef947d3b0141b49fb7382418617212` 9984.T buy/rebalance status=scheduled_for_next_session created=2026/04/24 22:55:33 executed=pending decision=dc-research-9984-t evidence=ev-news-9984-t-0, ev-company-9984-t
- `vord-5b8b812da75645839f8e6088d5f668af` 8035.T buy/rebalance status=approved_for_simulation created=2026/04/24 23:08:30 executed=pending decision=dc-research-8035-t evidence=ev-news-8035-t-0, ev-company-8035-t
- `vord-5b8b812da75645839f8e6088d5f668af` 8035.T buy/rebalance status=scheduled_for_next_session created=2026/04/24 23:08:30 executed=pending decision=dc-research-8035-t evidence=ev-news-8035-t-0, ev-company-8035-t

## Decision Trace
- `dlog-3eab4f76c40f47a2a51adc08a868bc98` outcome=simulated_filled decision=dc-virtual-6758-t order=vord-643a7eec8f564a0cb3ba0c3503950cf1 execution=vexec-687e7bd2ee51487f8564b4720432e315 at=2026/04/24 22:22:19
- `dlog-41849d2eee224502841f0d3b4cc73c60` outcome=scheduled_for_next_session decision=dc-research-9984-t order=vord-59ef947d3b0141b49fb7382418617212 execution=None at=2026/04/24 22:55:33
- `dlog-e4b51d88b3e546eb8073ebbc37313213` outcome=scheduled_for_next_session decision=dc-research-8035-t order=vord-5b8b812da75645839f8e6088d5f668af execution=None at=2026/04/24 23:08:30
