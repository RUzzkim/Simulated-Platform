#!/bin/bash
# 边端节点一键部署脚本（Linux 边缘节点）
#
# 用法:
#   ./deploy.sh              # 构建并启动
#   ./deploy.sh stop         # 停止容器
#   ./deploy.sh logs         # 查看日志
#   ./deploy.sh restart      # 重启
#
# 前置条件: 已安装 Docker + docker compose plugin
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

CMD="${1:-up}"

case "${CMD}" in
    up)
        echo "[deploy] 构建并启动边端节点..."
        docker compose up -d --build
        echo "[deploy] 启动完成，查看日志: ./deploy.sh logs"
        ;;
    stop)
        echo "[deploy] 停止边端节点..."
        docker compose down
        ;;
    restart)
        echo "[deploy] 重启边端节点..."
        docker compose down
        docker compose up -d
        ;;
    logs)
        docker compose logs -f --tail=100 edge_node
        ;;
    status)
        docker compose ps
        ;;
    *)
        echo "用法: $0 {up|stop|restart|logs|status}"
        exit 1
        ;;
esac
