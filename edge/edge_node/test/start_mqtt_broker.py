"""启动 amqtt MQTT broker（监听 1883），用于端到端联调"""
import asyncio
import logging

from amqtt.broker import Broker

logging.basicConfig(level=logging.INFO)

config = {
    "listeners": {
        "default": {
            "type": "tcp",
            "bind": "0.0.0.0:1883",
        },
    },
    "sys_interval": 0,
    "auth": {"allow-anonymous": True},
}


async def main():
    broker = Broker(config)
    await broker.start()
    print("MQTT broker started on 0.0.0.0:1883", flush=True)
    try:
        await asyncio.Future()  # run forever
    except KeyboardInterrupt:
        await broker.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
