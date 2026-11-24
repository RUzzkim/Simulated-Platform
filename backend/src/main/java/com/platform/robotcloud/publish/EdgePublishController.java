package com.platform.robotcloud.publish;

import com.platform.robotcloud.security.CurrentUserService;
import com.platform.robotcloud.security.EdgePrincipal;
import com.platform.robotcloud.support.ForbiddenException;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 边缘端拉取「本设备当前应生效的参数/策略/模型」。
 *
 * <p>用于边缘端启动或断线重连后与云端对齐：云端下发的实时命令在 /api/edge/commands 里，
 * 这里给的是最终状态（回执成功 = ACTIVE），两者互补。
 */
@RestController
@RequestMapping("/api/edge")
public class EdgePublishController {

    private final PublishService publishService;

    public EdgePublishController(PublishService publishService) {
        this.publishService = publishService;
    }

    @GetMapping("/publishables")
    public PublishablesView publishables() {
        EdgePrincipal edge = CurrentUserService.edge()
                .orElseThrow(() -> new ForbiddenException("需要设备接入令牌（edge token）"));
        return publishService.activeForDevice(edge.deviceId(), edge.deviceCode());
    }
}