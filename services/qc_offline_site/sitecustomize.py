"""Loaded automatically by child Python processes started with services.qc_no_network.child_env():
re-installs the no-network guard so an offline QC's subprocesses cannot reach the network either."""
import os
import sys

if os.environ.get('BK_QC_OFFLINE') == '1':
    _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    from services.qc_no_network import install

    install()
