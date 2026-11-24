package com.platform.robotcloud.heartbeat;

import com.platform.robotcloud.device.Device;
import com.platform.robotcloud.device.DeviceLookupService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/api/devices/{id}/status")
public class HeartbeatController {

    private final HeartbeatService heartbeatService;
    private final DeviceLookupService deviceLookupService;

    public HeartbeatController(HeartbeatService heartbeatService, DeviceLookupService deviceLookupService) {
        this.heartbeatService = heartbeatService;
        this.deviceLookupService = deviceLookupService;
    }

    @GetMapping
    public Map<String, Object> status(@PathVariable Long id) {
        Device device = deviceLookupService.requireDevice(id);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("deviceId", device.getId());
        body.put("deviceCode", device.getDeviceCode());
        body.put("status", device.getStatus());
        body.put("updatedAt", device.getUpdatedAt());
        body.put("lastHeartbeat", heartbeatService.latest(id).orElse(null));
        return body;
    }
}