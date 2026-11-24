package com.platform.robotcloud.device;

import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/devices")
public class DeviceController {

    private final DeviceRepository repository;
    private final DeviceLookupService deviceLookupService;

    public DeviceController(DeviceRepository repository, DeviceLookupService deviceLookupService) {
        this.repository = repository;
        this.deviceLookupService = deviceLookupService;
    }

    /**
     * 不传 page/size 时返回全量，避免既有页面被默认分页截断。
     */
    @GetMapping
    public List<Device> list(
            @RequestParam(required = false) String status,
            @RequestParam(required = false) Integer page,
            @RequestParam(required = false) Integer size) {
        return deviceLookupService.list(status, page, size);
    }

    @GetMapping("/{id}")
    public Device detail(@PathVariable Long id) {
        return deviceLookupService.requireDevice(id);
    }

    @PostMapping
    public Device register(@Valid @RequestBody DeviceRequest request) {
        return deviceLookupService.register(request.deviceCode(), request.name());
    }

    @PutMapping("/{id}")
    public Device rename(@PathVariable Long id, @Valid @RequestBody DeviceRenameRequest request) {
        return deviceLookupService.rename(id, request.name());
    }
}