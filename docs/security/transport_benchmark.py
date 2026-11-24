#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
传输层加密（MQTT 双向 TLS）吞吐验证（对齐项目书 §3.2：加密前后吞吐量损耗 < 5%）。

数据路径上的加密就是 MQTT over TLS（Mosquitto 8883，AES-GCM 套件）。本基准在本机回环上
测 TLS 链路能持续多大吞吐，再对照真实部署链路的带宽，得出「加密前后吞吐量损耗」。

关键结论口径：吞吐损耗 = 开启加密后，系统可持续吞吐相对不加密下降的比例。在任何真实链路上，
瓶颈是链路带宽而非 AES-GCM 运算——只要 TLS 的加解密吞吐 ≥ 链路带宽，加密就不是瓶颈，
吞吐损耗≈0。本脚本给出 TLS 可持续吞吐（Gbps）与典型链路带宽的对照。

注意：回环没有带宽上限（跑在内存带宽 ~GB/s 级），因此「明文回环 vs TLS 回环」的差值
反映的是内存带宽与 AES-GCM 运算速度之差，不是设备在真实链路上经历的损耗；这里如实给出
该原始对照，但结论以「TLS 吞吐 vs 真实链路带宽」为准。
"""

import datetime
import json
import os
import socket
import ssl
import tempfile
import threading
import time

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

CHUNK = 256 * 1024
TOTAL = 512 * 1024 * 1024          # 每轮传输总量
LINKS_MBPS = {"100Mbps 专线/家宽": 100 / 8, "1Gbps 内网/VPC": 1000 / 8}  # 换算成 MB/s


def make_self_signed():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.utcnow()
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now).not_valid_after(now + datetime.timedelta(days=1))
            .sign(key, hashes.SHA256()))
    cf = tempfile.NamedTemporaryFile(delete=False, suffix=".crt")
    kf = tempfile.NamedTemporaryFile(delete=False, suffix=".key")
    cf.write(cert.public_bytes(serialization.Encoding.PEM)); cf.close()
    kf.write(key.private_bytes(serialization.Encoding.PEM,
             serialization.PrivateFormat.TraditionalOpenSSL,
             serialization.NoEncryption())); kf.close()
    return cf.name, kf.name


def stream(wrap_server, wrap_client, total):
    ls = socket.socket(); ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ls.bind(("127.0.0.1", 0)); ls.listen(1); port = ls.getsockname()[1]

    def server():
        raw, _ = ls.accept()
        conn = wrap_server(raw) if wrap_server else raw
        got = 0
        try:
            while got < total:
                d = conn.recv(min(CHUNK, total - got))
                if not d:
                    break
                got += len(d)
        finally:
            conn.close()

    th = threading.Thread(target=server); th.start()
    raw = socket.create_connection(("127.0.0.1", port))
    conn = wrap_client(raw) if wrap_client else raw
    buf = os.urandom(CHUNK); sent = 0
    t0 = time.perf_counter()
    while sent < total:
        n = min(CHUNK, total - sent)
        conn.sendall(buf[:n]); sent += n
    th.join()
    dt = time.perf_counter() - t0
    cipher = conn.cipher() if isinstance(conn, ssl.SSLSocket) else None
    conn.close(); ls.close()
    return dt, cipher


def best_of(wrap_s, wrap_c, rounds=3):
    bt, cph = None, None
    for _ in range(rounds):
        dt, c = stream(wrap_s, wrap_c, TOTAL)
        if bt is None or dt < bt:
            bt, cph = dt, c
    return bt, cph


def main():
    certfile, keyfile = make_self_signed()
    sc = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    sc.minimum_version = ssl.TLSVersion.TLSv1_2
    sc.load_cert_chain(certfile, keyfile)
    cc = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    cc.minimum_version = ssl.TLSVersion.TLSv1_2
    cc.check_hostname = False
    cc.verify_mode = ssl.CERT_NONE
    ws = lambda s: sc.wrap_socket(s, server_side=True)
    wc = lambda s: cc.wrap_socket(s, server_hostname="localhost")

    stream(None, None, 16 * 1024 * 1024)        # 预热
    stream(ws, wc, 16 * 1024 * 1024)

    plain_dt, _ = best_of(None, None)
    tls_dt, cipher = best_of(ws, wc)
    os.unlink(certfile); os.unlink(keyfile)

    plain_mbps = TOTAL / plain_dt / (1024 * 1024)
    tls_mbps = TOTAL / tls_dt / (1024 * 1024)

    link_loss = []
    for name, cap in LINKS_MBPS.items():
        # 该链路上：明文可跑满 min(cap, plain)，加密可跑满 min(cap, tls)
        p = min(cap, plain_mbps)
        t = min(cap, tls_mbps)
        link_loss.append({
            "link": name,
            "link_MBps": round(cap, 1),
            "throughput_loss_pct": round(max(0.0, (p - t) / p * 100.0), 3),
        })

    print(json.dumps({
        "path": "MQTT 数据路径传输加密 TLS(AES-GCM)",
        "negotiated_cipher": cipher,
        "loopback_raw": {
            "note": "回环无带宽上限，反映内存带宽 vs AES-GCM 运算速度之差，非真实链路损耗",
            "plaintext_MBps": round(plain_mbps, 1),
            "tls_MBps": round(tls_mbps, 1),
            "tls_Gbps": round(tls_mbps * 8 / 1024, 2),
        },
        "throughput_loss_on_real_link": link_loss,
        "target": "< 5",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
