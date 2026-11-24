package com.platform.robotcloud.credential;

import com.platform.robotcloud.audit.AuditAction;
import com.platform.robotcloud.audit.AuditService;
import com.platform.robotcloud.device.Device;
import com.platform.robotcloud.device.DeviceLookupService;
import org.springframework.web.bind.annotation.*;

/**
 * 设备接入凭据管理：给边缘端（ROS2）与仿真端（Gazebo）下发 MQTT 账号与 edge token。
 * 权限由 SecurityConfig 限定为 ADMIN/OPERATOR。
 */
@RestController
@RequestMapping("/api/devices/{id}/credentials")
public class DeviceCredentialController {

    private final CredentialService credentialService;
    private final DeviceLookupService deviceLookupService;
    private final AuditService auditService;

    public DeviceCredentialController(CredentialService credentialService,
                                      DeviceLookupService deviceLookupService,
                                      AuditService auditService) {
        this.credentialService = credentialService;
        this.deviceLookupService = deviceLookupService;
        this.auditService = auditService;
    }

    @GetMapping
    public CredentialService.CredentialView view(@PathVariable Long id) {
        Device device = deviceLookupService.requireDevice(id);
        var view = credentialService.view(id).orElse(null);
        auditService.userAction(AuditAction.CREDENTIAL_READ, "device", device.getDeviceCode(),
                view == null ? "查询接入凭据（尚未签发）" : "查询接入凭据 " + view.mqttUsername());
        return view;
    }

    @PostMapping
    public CredentialService.CredentialView issue(@PathVariable Long id) {
        return credentialService.issue(id);
    }

    @DeleteMapping
    public CredentialService.CredentialView revoke(@PathVariable Long id) {
        return credentialService.revoke(id);
    }
}