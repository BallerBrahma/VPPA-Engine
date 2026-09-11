"""Ingest layer: pull raw data from external sources.

Configures a CA bundle for urllib-based fetches. gridstatus reaches ERCOT
through `requests` on most paths (which bundles its own CA store), but falls
back to urllib for some zip downloads -- and this python.org framework build
has no system CA bundle configured, so those fail certificate verification.
Pointing SSL_CERT_FILE at certifi fixes verification properly; never disable
it instead.
"""

import os

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())
