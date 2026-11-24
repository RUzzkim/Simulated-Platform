package com.platform.robotcloud.publish;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 一台设备当前应生效的配置（回执成功 = ACTIVE）。边缘端启动/重连后拉一次即可对齐云端。
 */
public record PublishablesView(String deviceCode, ParameterView parameter, List<StrategyView> strategies,
                               List<ModelView> models, LocalDateTime generatedAt) {
}