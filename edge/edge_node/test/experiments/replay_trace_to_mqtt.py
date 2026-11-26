"""把官方任务恢复实验的原始轨迹按 100Hz 回放到 MQTT sim_state，用于端→边→云链路验证。

只读取 run_task_recovery.py 产出的 *.csv.gz，不改动轨迹内容。
"""
import argparse
import csv
import gzip
import json
import ssl
import time

import paho.mqtt.client as mqtt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('trace')
    ap.add_argument('--broker', default='ssl://127.0.0.1:8884')
    ap.add_argument('--ca', required=True)
    ap.add_argument('--cert', required=True)
    ap.add_argument('--key', required=True)
    ap.add_argument('--topic', default='simulation/SIM-001/sim_state')
    ap.add_argument('--rate', type=float, default=100.0)
    args = ap.parse_args()

    rows = []
    with gzip.open(args.trace, 'rt', encoding='utf-8', newline='') as f:
        for row in csv.DictReader(f):
            rows.append(row)
    if not rows:
        raise SystemExit('empty trace')

    host_port = args.broker.split('://', 1)[-1]
    host, _, port = host_port.partition(':')
    secure = args.broker.startswith(('ssl://', 'mqtts://', 'tls://'))
    client = mqtt.Client(client_id='v2-trace-replay', protocol=mqtt.MQTTv311)
    if secure:
        ctx = ssl.create_default_context(cafile=args.ca)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(args.cert, args.key)
        client.tls_set_context(ctx)
    client.connect(host, int(port or 8884), keepalive=60)
    client.loop_start()

    interval = 1.0 / args.rate
    epoch_base_ms = int(time.time() * 1000)
    start = time.perf_counter()
    for k, row in enumerate(rows):
        # 边端要求毫秒级 Unix 时间戳；轨迹里的 t_s 是相对时间，叠加回放起始 epoch。
        stamp_ns = (epoch_base_ms + int(float(row['t_s']) * 1000)) * 1_000_000
        payload = {
            'simulationId': 'SIM-001',
            'robotId': 'ROBOT-001',
            'jointPosition': [float(row[f'q{i}']) for i in range(6)],
            'jointVelocity': [float(row[f'qd{i}']) for i in range(6)],
            'jointTorque': [float(row[f'tau{i}']) for i in range(6)],
            'stampNanosec': stamp_ns,
        }
        client.publish(args.topic, json.dumps(payload), qos=1)
        target_t = start + (k + 1) * interval
        delay = target_t - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
    time.sleep(0.5)
    client.loop_stop()
    client.disconnect()
    print(f'published {len(rows)} rows in {time.perf_counter() - start:.2f}s')


if __name__ == '__main__':
    main()
