import sys
import os
import json
import pytest

# Add the directory containing cli.py to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cli import (
    compute_nsequence,
    compute_nlocktime,
    locktime_type_label,
    estimate_vbytes,
    min_fee,
    select_coins,
    build_outputs,
    collect_warnings,
    DUST_THRESHOLD,
)

# ── RBF & Locktime Tests (5 tests) ──────────────────────────────────────────

def test_nsequence_rbf_true():
    assert compute_nsequence(rbf=True, locktime_value=0) == 0xFFFFFFFD
    assert compute_nsequence(rbf=True, locktime_value=123) == 0xFFFFFFFD

def test_nsequence_rbf_false_with_locktime():
    assert compute_nsequence(rbf=False, locktime_value=123) == 0xFFFFFFFE

def test_nsequence_rbf_false_no_locktime():
    assert compute_nsequence(rbf=False, locktime_value=0) == 0xFFFFFFFF

def test_nlocktime_explicit_locktime():
    assert compute_nlocktime(rbf=False, locktime=850000, current_height=None) == 850000
    assert compute_nlocktime(rbf=True, locktime=850000, current_height=800000) == 850000

def test_nlocktime_anti_fee_sniping():
    # If rbf=true and current_height is passed, and no explicit locktime, it should use current_height
    assert compute_nlocktime(rbf=True, locktime=None, current_height=800000) == 800000

def test_locktime_type_label():
    assert locktime_type_label(0) == "none"
    assert locktime_type_label(499999999) == "block_height"
    assert locktime_type_label(500000000) == "unix_timestamp"

# ── Fee & vBytes Estimation Tests (3 tests) ─────────────────────────────────

def test_estimate_vbytes_p2wpkh_basic():

    assert estimate_vbytes(["p2wpkh"], ["p2wpkh"]) == 110

def test_estimate_vbytes_complex():

    assert estimate_vbytes(["p2tr", "p2tr"], ["p2sh", "p2wpkh"]) == 189

def test_min_fee():
    assert min_fee(100, 1.0) == 100
    assert min_fee(100, 1.5) == 150
    assert min_fee(141, 5.0) == 705

# ── Coin Selection & Outputs Tests (5 tests) ────────────────────────────────

def test_select_coins_with_change():
    utxos = [{"value_sats": 50000, "script_type": "p2wpkh"}, {"value_sats": 100000, "script_type": "p2wpkh"}]
    payments = [{"value_sats": 70000, "script_type": "p2wpkh"}]
    change_template = {"script_type": "p2wpkh"}
    selected, fee, vbytes, is_send_all = select_coins(utxos, payments, change_template, 5.0, 10, "")
    assert len(selected) == 1
    assert selected[0]["value_sats"] == 100000
    assert fee == 705
    assert not is_send_all

def test_select_coins_send_all_dust_change():
    utxos = [{"value_sats": 71000, "script_type": "p2wpkh"}]
    payments = [{"value_sats": 70000, "script_type": "p2wpkh"}]
    change_template = {"script_type": "p2wpkh"}
    selected, fee, vbytes, is_send_all = select_coins(utxos, payments, change_template, 5.0, 10, "")
    assert len(selected) == 1
    assert fee == 1000
    assert is_send_all

def test_select_coins_insufficient_funds():
    utxos = [{"value_sats": 70000, "script_type": "p2wpkh"}]
    payments = [{"value_sats": 70000, "script_type": "p2wpkh"}]
    with pytest.raises(SystemExit):
        select_coins(utxos, payments, None, 5.0, 10, os.devnull)

def test_build_outputs_with_change():
    payments = [{"value_sats": 70000, "script_type": "p2wpkh"}]
    change_template = {"script_pubkey_hex": "abcd", "script_type": "p2wpkh"}
    selected_value = 100000
    target_value = 70000
    final_fee = 705
    outputs_json, change_index = build_outputs(payments, change_template, selected_value, target_value, final_fee, False)
    assert len(outputs_json) == 2
    assert change_index == 1
    assert outputs_json[1]["value_sats"] == 100000 - 70000 - 705
    assert outputs_json[1]["is_change"]

def test_build_outputs_send_all():
    payments = [{"value_sats": 70000, "script_type": "p2wpkh"}]
    change_template = {"script_pubkey_hex": "abcd", "script_type": "p2wpkh"}
    selected_value = 71000
    target_value = 70000
    final_fee = 1000
    outputs_json, change_index = build_outputs(payments, change_template, selected_value, target_value, final_fee, True)
    assert len(outputs_json) == 1
    assert change_index is None

# ── Warnings Tests (2 tests) ────────────────────────────────────────────────

def test_collect_warnings_send_all():
    warnings = collect_warnings(final_fee=1000, final_vbytes=110, is_send_all=True, rbf_signaling=False, outputs=[])
    codes = [w["code"] for w in warnings]
    assert "SEND_ALL" in codes
    assert "RBF_SIGNALING" not in codes
    assert "HIGH_FEE" not in codes

def test_collect_warnings_high_fee():
    # High fee by rate (250 sat/vB > 200)
    warnings = collect_warnings(final_fee=50000, final_vbytes=200, is_send_all=False, rbf_signaling=True, outputs=[])
    codes = [w["code"] for w in warnings]
    assert "HIGH_FEE" in codes
    assert "RBF_SIGNALING" in codes
