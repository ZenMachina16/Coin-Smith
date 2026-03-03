"""
Coin Smith — CLI entry point.

Reads a fixture JSON, performs coin selection, builds an unsigned PSBT,
and writes a JSON report to the output file.
"""

import json
import math
import sys
import traceback
import base64

import bitcointx
from bitcointx.core import CTxIn, CTxOut, CMutableTransaction, COutPoint, lx
from bitcointx.core.script import CScript
from bitcointx.core.psbt import PartiallySignedTransaction

# ─────────────────────────── constants ────────────────────────────────────────

DUST_THRESHOLD = 546  # satoshis

# Weight units per script type for vbytes estimation.
# vbytes = ceil(weight / 4).  We keep values already in vbytes (wu/4).
INPUT_VBYTES = {
    "p2wpkh":      68.0,
    "p2tr":        57.5,
    "p2pkh":      148.0,
    "p2sh":        91.0,
    "p2sh-p2wpkh": 91.0,
    "p2wsh":      104.0,
}
OUTPUT_VBYTES = {
    "p2wpkh": 31.0,
    "p2tr":   43.0,
    "p2pkh":  34.0,
    "p2sh":   32.0,
    "p2wsh":  43.0,
}
TX_OVERHEAD_VBYTES = 10.5   # version(4) + locktime(4) + segwit marker/flag(0.5) + vin/vout counts(2)

SEGWIT_TYPES = {"p2wpkh", "p2tr", "p2wsh", "p2sh-p2wpkh"}

# ─────────────────────────── error handling ───────────────────────────────────

def write_error(output_path: str, code: str, message: str) -> None:
    payload = {"ok": False, "error": {"code": code, "message": message}}
    with open(output_path, "w") as f:
        json.dump(payload, f, indent=2)
    sys.stderr.write(f"Error [{code}]: {message}\n")


def die(output_path: str, code: str, message: str) -> None:
    """Write error JSON and exit 1."""
    write_error(output_path, code, message)
    sys.exit(1)


# ─────────────────────────── fixture parsing ──────────────────────────────────

REQUIRED_FIXTURE_KEYS = ["network", "utxos", "payments", "fee_rate_sat_vb"]


def parse_fixture(fixture_path: str, output_path: str) -> dict:
    """Load and validate the fixture JSON. Dies on errors."""
    try:
        with open(fixture_path, "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        die(output_path, "FILE_NOT_FOUND", f"Fixture file not found: {fixture_path}")
    except json.JSONDecodeError as exc:
        die(output_path, "INVALID_FIXTURE", f"JSON parse error: {exc}")

    for key in REQUIRED_FIXTURE_KEYS:
        if key not in data:
            die(output_path, "INVALID_FIXTURE", f"Missing required key: '{key}'")

    if not isinstance(data["utxos"], list) or len(data["utxos"]) == 0:
        die(output_path, "INVALID_FIXTURE", "'utxos' must be a non-empty array")

    if not isinstance(data["payments"], list) or len(data["payments"]) == 0:
        die(output_path, "INVALID_FIXTURE", "'payments' must be a non-empty array")

    return data


# ─────────────────────────── RBF / Locktime ───────────────────────────────────

def compute_nsequence(rbf: bool, locktime_value: int) -> int:
    """Return nSequence per the BIP-125 + locktime interaction matrix."""
    if rbf:
        return 0xFFFFFFFD
    if locktime_value > 0:
        return 0xFFFFFFFE   # enables locktime without RBF
    return 0xFFFFFFFF


def compute_nlocktime(rbf: bool, locktime: int | None, current_height: int | None) -> int:
    """Return nLockTime per spec:
    - explicit locktime wins
    - anti-fee-sniping: rbf=true + current_height → current_height
    - default: 0
    """
    if locktime is not None:
        return locktime
    if rbf and current_height is not None:
        return current_height
    return 0


def locktime_type_label(n_locktime: int) -> str:
    if n_locktime == 0:
        return "none"
    if n_locktime < 500_000_000:
        return "block_height"
    return "unix_timestamp"


# ─────────────────────────── fee / vbytes estimation ─────────────────────────

def estimate_vbytes(input_types: list[str], output_types: list[str]) -> int:
    """Deterministic vbytes estimate for a transaction with the given script types."""
    v = TX_OVERHEAD_VBYTES
    for st in input_types:
        v += INPUT_VBYTES.get(st.lower(), 68.0)
    for st in output_types:
        v += OUTPUT_VBYTES.get(st.lower(), 31.0)
    return math.ceil(v)


def min_fee(vbytes: int, fee_rate: float) -> int:
    return math.ceil(vbytes * fee_rate)


# ─────────────────────────── coin selection ───────────────────────────────────

def select_coins(
    utxos: list[dict],
    payments: list[dict],
    change_template: dict | None,
    fee_rate: float,
    max_inputs: int,
    output_path: str,
) -> tuple[list[dict], int, int, bool]:
    """
    Greedy coin selection (largest-first).

    Returns:
        (selected_inputs, final_fee, final_vbytes, is_send_all)
    """
    # Sort UTXOs by value descending
    sorted_utxos = sorted(utxos, key=lambda u: u.get("value_sats", 0), reverse=True)

    payment_types = [p.get("script_type", "p2wpkh") for p in payments]
    payment_total = sum(p.get("value_sats", 0) for p in payments)

    selected: list[dict] = []
    selected_value = 0

    for utxo in sorted_utxos:
        selected.append(utxo)
        selected_value += utxo.get("value_sats", 0)

        if len(selected) > max_inputs:
            die(output_path, "POLICY_VIOLATION",
                f"Cannot fund payments within policy.max_inputs={max_inputs}")

        input_types = [u.get("script_type", "p2wpkh") for u in selected]

        # ── Try WITH change ───────────────────────────────────────────────────
        if change_template:
            change_type = change_template.get("script_type", "p2wpkh")
            vbytes_w = estimate_vbytes(input_types, payment_types + [change_type])
            fee_w = min_fee(vbytes_w, fee_rate)
            leftover = selected_value - payment_total - fee_w
            if leftover >= DUST_THRESHOLD:
                return selected, fee_w, vbytes_w, False

        # ── Try WITHOUT change (send-all) ─────────────────────────────────────
        vbytes_n = estimate_vbytes(input_types, payment_types)
        fee_n = min_fee(vbytes_n, fee_rate)
        if selected_value >= payment_total + fee_n:
            # Entire leftover goes to fee
            actual_fee = selected_value - payment_total
            return selected, actual_fee, vbytes_n, True

    # Exhausted all UTXOs
    die(output_path, "INSUFFICIENT_FUNDS",
        "Not enough funds in available UTXOs to cover payments and fee")


# ─────────────────────────── output construction ─────────────────────────────

def build_outputs(
    payments: list[dict],
    change_template: dict | None,
    selected_value: int,
    target_value: int,
    final_fee: int,
    is_send_all: bool,
) -> tuple[list[dict], int | None]:
    """Build the output list and return (outputs_json, change_index)."""
    outputs_json = []
    idx = 0

    for p in payments:
        outputs_json.append({
            "n": idx,
            "value_sats": p["value_sats"],
            "script_pubkey_hex": p.get("script_pubkey_hex", ""),
            "script_type": p.get("script_type", ""),
            "address": p.get("address", ""),
            "is_change": False,
        })
        idx += 1

    change_index = None
    if not is_send_all and change_template:
        change_amount = selected_value - target_value - final_fee
        if change_amount > 0:
            outputs_json.append({
                "n": idx,
                "value_sats": change_amount,
                "script_pubkey_hex": change_template.get("script_pubkey_hex", ""),
                "script_type": change_template.get("script_type", ""),
                "address": change_template.get("address", ""),
                "is_change": True,
            })
            change_index = idx

    return outputs_json, change_index


# ─────────────────────────── warnings ────────────────────────────────────────

def collect_warnings(
    final_fee: int,
    final_vbytes: int,
    is_send_all: bool,
    rbf_signaling: bool,
    outputs: list[dict],
) -> list[dict]:
    warnings = []

    if is_send_all:
        warnings.append({"code": "SEND_ALL"})

    if rbf_signaling:
        warnings.append({"code": "RBF_SIGNALING"})

    # HIGH_FEE: absolute OR rate
    rate = final_fee / final_vbytes if final_vbytes else 0
    if final_fee > 1_000_000 or rate > 200:
        warnings.append({"code": "HIGH_FEE"})

    # DUST_CHANGE: change output below threshold (defensive, shouldn't happen)
    for o in outputs:
        if o.get("is_change") and o["value_sats"] < DUST_THRESHOLD:
            warnings.append({"code": "DUST_CHANGE"})

    return warnings


# ─────────────────────────── PSBT builder ─────────────────────────────────────

def _is_legacy_type(script_type: str) -> bool:
    return script_type.lower() not in SEGWIT_TYPES


def _build_mock_prev_tx(value_sats: int, spk_hex: str, vout_index: int) -> CMutableTransaction:
    """
    Build a minimal fake previous transaction so we can attach it as
    non_witness_utxo for legacy (P2PKH / bare P2SH) inputs.

    We place the real output at the required vout_index, padding with
    zero-value OP_RETURN outputs before it if needed.
    """
    fake_tx = CMutableTransaction()
    # Pad outputs up to the required index with zero-value OP_RETURN
    for _ in range(vout_index):
        fake_tx.vout.append(CTxOut(0, CScript(b'\x6a')))  # OP_RETURN
    # Place the real UTXO output
    fake_tx.vout.append(CTxOut(value_sats, CScript(bytes.fromhex(spk_hex))))
    return fake_tx


def build_psbt(
    selected_inputs: list[dict],
    outputs_json: list[dict],
    n_locktime: int,
    n_sequence: int,
    output_path: str,
) -> str:
    """Construct and serialize a PSBT. Returns base64 string."""
    try:
        # ── Build unsigned transaction ────────────────────────────────────────
        tx = CMutableTransaction()
        tx.nVersion = 2
        tx.nLockTime = n_locktime

        for utxo in selected_inputs:
            txin = CTxIn(
                COutPoint(lx(utxo["txid"]), utxo["vout"]),
                nSequence=n_sequence,
            )
            tx.vin.append(txin)

        for out in outputs_json:
            tx.vout.append(CTxOut(
                out["value_sats"],
                CScript(bytes.fromhex(out["script_pubkey_hex"])),
            ))

        # ── Wrap in PSBT ──────────────────────────────────────────────────────
        psbt = PartiallySignedTransaction(unsigned_tx=tx, relaxed_sanity_checks=True)

        # ── Attach prevout metadata to each input ─────────────────────────────
        for i, utxo in enumerate(selected_inputs):
            val = utxo["value_sats"]
            spk_hex = utxo["script_pubkey_hex"]
            script_type = utxo.get("script_type", "p2wpkh")
            ctx_out = CTxOut(val, CScript(bytes.fromhex(spk_hex)))

            if _is_legacy_type(script_type):
                pass
            else:
                # Segwit input: witness_utxo (just the CTxOut) is sufficient
                psbt.set_utxo(ctx_out, i, force_witness_utxo=True, relaxed_sanity_checks=True)

        return base64.b64encode(psbt.serialize()).decode("ascii")

    except Exception as exc:
        die(output_path, "PSBT_BUILD_ERROR", str(exc))


# ─────────────────────────── main ────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) < 3:
        sys.stderr.write("Usage: python cli.py <fixture.json> <output.json>\n")
        sys.exit(1)

    fixture_path = sys.argv[1]
    output_path = sys.argv[2]

    # ── Parse ─────────────────────────────────────────────────────────────────
    data = parse_fixture(fixture_path, output_path)

    network = data.get("network", "mainnet")
    bitcointx.select_chain_params("bitcoin" if network == "mainnet" else "bitcoin/testnet")

    utxos: list[dict] = data["utxos"]
    payments: list[dict] = data["payments"]
    change_template: dict | None = data.get("change")
    fee_rate: float = float(data["fee_rate_sat_vb"])
    rbf: bool = bool(data.get("rbf", False))
    locktime_raw: int | None = data.get("locktime")
    current_height: int | None = data.get("current_height")
    policy: dict = data.get("policy") or {}
    max_inputs: int = int(policy.get("max_inputs", len(utxos)))

    # ── RBF / Locktime ────────────────────────────────────────────────────────
    n_locktime = compute_nlocktime(rbf, locktime_raw, current_height)
    n_sequence = compute_nsequence(rbf, n_locktime)
    lt_type = locktime_type_label(n_locktime)
    rbf_signaling = n_sequence <= 0xFFFFFFFD

    # ── Coin selection ────────────────────────────────────────────────────────
    selected_inputs, final_fee, final_vbytes, is_send_all = select_coins(
        utxos, payments, change_template, fee_rate, max_inputs, output_path
    )
    selected_value = sum(u["value_sats"] for u in selected_inputs)
    target_value = sum(p["value_sats"] for p in payments)

    # ── Outputs ───────────────────────────────────────────────────────────────
    outputs_json, change_index = build_outputs(
        payments, change_template, selected_value, target_value, final_fee, is_send_all
    )

    # ── Warnings ──────────────────────────────────────────────────────────────
    warnings = collect_warnings(final_fee, final_vbytes, is_send_all, rbf_signaling, outputs_json)

    # ── PSBT ─────────────────────────────────────────────────────────────────
    psbt_base64 = build_psbt(selected_inputs, outputs_json, n_locktime, n_sequence, output_path)

    # ── Report ────────────────────────────────────────────────────────────────
    report = {
        "ok": True,
        "network": network,
        "strategy": "greedy",
        "selected_inputs": selected_inputs,
        "outputs": outputs_json,
        "change_index": change_index,
        "fee_sats": final_fee,
        "fee_rate_sat_vb": round(final_fee / final_vbytes, 4),
        "vbytes": final_vbytes,
        "rbf_signaling": rbf_signaling,
        "locktime": n_locktime,
        "locktime_type": lt_type,
        "psbt_base64": psbt_base64,
        "warnings": warnings,
    }

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        # Best-effort error output — output_path may not be defined
        if len(sys.argv) >= 3:
            write_error(sys.argv[2], "UNKNOWN_ERROR", str(exc))
        sys.exit(1)
