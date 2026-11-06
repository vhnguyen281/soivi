"""Market and macro data for VNCMA (docs/vncma/spec.md).

Every vnstock call goes through `pipeline.market.client`; no other module imports
vnstock. Tests never hit the network: they pass a fake client.
"""
