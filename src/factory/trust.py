"""Bootstrap trust for Etched's internal PKI.

THE PROBLEM
-----------
``eos.core.etched.com`` presents a leaf issued by ``ca.core.etched.com``, which
is signed by the FreeIPA root ``O=IDM.ETCHED.COM, CN=Certificate Authority``.
That root is in no public trust store, and the server does not send it — the
third certificate it does send (``Etched RSA Corporate Root CA``) is not the
issuer of the second, so the chain cannot be completed by anyone. ``curl`` and
browsers fail exactly like Python does.

THE BOOTSTRAP PARADOX
---------------------
The missing root is published by FreeIPA over HTTPS on a host with the *same*
untrusted PKI, so the fetch itself cannot be TLS-verified. Rather than shrug at
that, this module authenticates the download **out of band**: the bundle must
contain the ``Etched RSA Corporate Root CA`` whose SHA-256 matches the copy
already installed in the machine's system keychain by MDM. An attacker who could
MITM the fetch still could not produce a bundle carrying that fingerprint.

If no keychain copy is available (Linux, CI), pass an expected fingerprint
explicitly — never skip the check silently.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import ssl
import subprocess
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple

from . import config

log = logging.getLogger(__name__)

PEM_BLOCK = re.compile(
    r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", re.DOTALL
)


class TrustError(RuntimeError):
    """The CA bundle could not be fetched or could not be authenticated."""


# ------------------------------------------------------------------ primitives

def split_pem(text: str) -> List[str]:
    return PEM_BLOCK.findall(text)


def der_of(pem: str) -> bytes:
    return ssl.PEM_cert_to_DER_cert(pem)


def fingerprint(pem: str) -> str:
    """Uppercase colon-free SHA-256 of a certificate, as keychains print it."""
    return hashlib.sha256(der_of(pem)).hexdigest().upper()


def subject_of(pem: str) -> str:
    """Best-effort subject line, via openssl if present."""
    if not shutil.which("openssl"):
        return "(openssl unavailable)"
    result = subprocess.run(
        ["openssl", "x509", "-noout", "-subject"],
        input=pem, capture_output=True, text=True,
    )
    return result.stdout.strip().replace("subject=", "").strip() or "(unknown)"


# ----------------------------------------------------------- keychain anchor

def keychain_fingerprints(common_name: str = config.CORPORATE_ROOT_CN) -> List[str]:
    """SHA-256 fingerprints of certs matching ``common_name`` in macOS keychains.

    Returns an empty list on non-macOS or when the cert is not installed; the
    caller decides whether that is fatal.
    """
    if not shutil.which("security"):
        return []

    found = []
    for keychain in ([], ["/Library/Keychains/System.keychain"]):
        result = subprocess.run(
            ["security", "find-certificate", "-a", "-c", common_name, "-Z"] + keychain,
            capture_output=True, text=True,
        )
        for line in result.stdout.splitlines():
            if line.strip().startswith("SHA-256 hash:"):
                found.append(line.split(":", 1)[1].strip().upper())
    return sorted(set(found))


# ------------------------------------------------------------------- fetching

def fetch_bundle(url: str = config.IPA_CA_URL, timeout: float = 30.0) -> str:
    """Download the FreeIPA CA bundle.

    Verification is disabled *for this one request only*, because the endpoint
    that serves the missing trust anchor is itself protected by it. The result is
    worthless until :func:`authenticate` accepts it — never write it to the trust
    path before then.
    """
    context = ssl._create_unverified_context()  # noqa: SLF001 - see docstring
    log.info("fetching CA bundle from %s (unverified; will be authenticated)", url)
    try:
        with urllib.request.urlopen(url, timeout=timeout, context=context) as response:
            payload = response.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - any failure here is the same story
        raise TrustError(
            "could not reach {} ({}). Are you on the corporate network or VPN?".format(url, exc)
        ) from exc

    certs = split_pem(payload)
    if not certs:
        raise TrustError("{} did not return PEM certificates".format(url))
    return "\n".join(certs) + "\n"


def authenticate(bundle: str, expected: Optional[str] = None) -> Tuple[str, str]:
    """Check the bundle against a fingerprint we already trust.

    ``expected`` overrides the keychain lookup. Returns ``(fingerprint, source)``
    of the anchor that matched.
    """
    present = {fingerprint(pem): pem for pem in split_pem(bundle)}

    if expected:
        wanted = expected.replace(":", "").strip().upper()
        if wanted not in present:
            raise TrustError(
                "the downloaded bundle does not contain the expected certificate.\n"
                "  expected: {}\n  found:    {}".format(wanted, ", ".join(present) or "none")
            )
        return wanted, "--fingerprint"

    anchors = keychain_fingerprints()
    if not anchors:
        raise TrustError(
            "cannot authenticate the download: '{}' is not in this machine's "
            "keychain (or this is not macOS).\n"
            "Re-run with --fingerprint <sha256> using a value obtained from IT "
            "over a trusted channel. Refusing to install an unverified CA."
            .format(config.CORPORATE_ROOT_CN)
        )

    for anchor in anchors:
        if anchor in present:
            return anchor, "system keychain"

    raise TrustError(
        "MISMATCH — the downloaded bundle does not contain the corporate root "
        "installed on this machine. Treat this as a possible interception and "
        "do not install it.\n  keychain: {}\n  download: {}"
        .format(", ".join(anchors), ", ".join(present) or "none")
    )


def verify_endpoint(bundle_path: Path, url: str) -> None:
    """Prove the bundle actually fixes the connection, with verification ON."""
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=str(bundle_path))
    try:
        urllib.request.urlopen(url, timeout=30, context=context)
    except urllib.error.HTTPError:
        pass  # an HTTP status means the TLS handshake and verification succeeded
    except Exception as exc:  # noqa: BLE001
        raise TrustError("bundle installed but {} still fails: {}".format(url, exc)) from exc


def install(
    url: str = config.IPA_CA_URL,
    destination: Optional[Path] = None,
    expected: Optional[str] = None,
) -> Path:
    """Fetch, authenticate, and write the internal CA bundle. Returns its path."""
    target = destination or config.DEFAULT_CA_BUNDLE
    bundle = fetch_bundle(url)
    matched, source = authenticate(bundle, expected)

    log.info("authenticated against %s: %s", source, matched)
    for pem in split_pem(bundle):
        log.info("  trust anchor: %s", subject_of(pem))

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(bundle, encoding="utf-8")
    target.chmod(0o644)

    base = config.base_url()
    verify_endpoint(target, base.split("/api/")[0] + "/")
    return target
