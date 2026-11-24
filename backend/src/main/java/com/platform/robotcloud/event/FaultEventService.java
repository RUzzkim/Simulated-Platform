package com.platform.robotcloud.event;

import com.fasterxml.jackson.databind.JsonNode;
import com.platform.robotcloud.device.Device;
import com.platform.robotcloud.device.DeviceLookupService;
import com.platform.robotcloud.device.DeviceRepository;
import com.platform.robotcloud.support.Payloads;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

@Service
public class FaultEventService {

    /** 不限定设备的哨兵值，与 FaultEventRepository 的 JPQL 保持一致。 */
    static final long ALL_DEVICES = -1L;
    static final LocalDateTime MIN_TIME = LocalDateTime.of(1970, 1, 1, 0, 0);
    static final LocalDateTime MAX_TIME = LocalDateTime.of(9999, 1, 1, 0, 0);

    private final FaultEventRepository repository;
    private final DeviceRepository deviceRepository;
    private final DeviceLookupService deviceLookupService;

    public FaultEventService(FaultEventRepository repository,
                             DeviceRepository deviceRepository,
                             DeviceLookupService deviceLookupService) {
        this.repository = repository;
        this.deviceRepository = deviceRepository;
        this.deviceLookupService = deviceLookupService;
    }

    public FaultEvent saveEvent(JsonNode json) {
        String deviceCode = Payloads.deviceCode(json);
        if (deviceCode == null) {
            throw new IllegalArgumentException("event payload has no deviceId");
        }
        FaultEvent event = new FaultEvent();
        event.setDeviceId(deviceLookupService.findOrCreateId(deviceCode));
        event.setEventType(Payloads.text(json, "type", "UNKNOWN"));
        event.setLevel(Payloads.text(json, "level", "WARNING"));
        event.setDetail(Payloads.text(json, "detail", null));
        event.setContextPayload(Payloads.jsonOrNull(json, "context"));
        event.setOccurredAt(Payloads.reportedAt(json));
        return repository.save(event);
    }

    public FaultEvent require(Long id) {
        return repository.findById(id)
                .orElseThrow(() -> new IllegalArgumentException("fault event not found: " + id));
    }

    /**
     * 按等级 / 类型 / 日期 / 设备四个维度统计故障数量，deviceId 为空表示全量。
     */
    public FaultStatistics statistics(Long deviceId, LocalDateTime from, LocalDateTime to) {
        long deviceFilter = deviceId == null ? ALL_DEVICES : deviceId;
        LocalDateTime start = from == null ? MIN_TIME : from;
        LocalDateTime end = to == null ? MAX_TIME : to;

        long total = repository.countInRange(deviceFilter, start, end);
        List<FaultStatItem> byLevel = repository.countByLevel(deviceFilter, start, end).stream()
                .map(item -> new FaultStatItem(item.getKey(), item.getTotal()))
                .toList();
        List<FaultStatItem> byType = repository.countByType(deviceFilter, start, end).stream()
                .map(item -> new FaultStatItem(item.getKey(), item.getTotal()))
                .toList();
        List<FaultStatItem> byDay = repository.countByDay(deviceFilter, start, end).stream()
                .map(item -> new FaultStatItem(String.valueOf(item.getDay()), item.getTotal()))
                .toList();
        List<DeviceFaultStat> byDevice = toDeviceStats(repository.countByDevice(deviceFilter, start, end));

        return new FaultStatistics(total, start, end, byLevel, byType, byDay, byDevice);
    }

    private List<DeviceFaultStat> toDeviceStats(List<FaultEventRepository.DeviceCount> counts) {
        if (counts.isEmpty()) {
            return List.of();
        }
        List<Long> deviceIds = counts.stream().map(FaultEventRepository.DeviceCount::getDeviceId).toList();
        Map<Long, Device> devices = deviceRepository.findAllById(deviceIds).stream()
                .collect(Collectors.toMap(Device::getId, Function.identity()));
        return counts.stream()
                .map(count -> {
                    Device device = devices.get(count.getDeviceId());
                    return new DeviceFaultStat(
                            count.getDeviceId(),
                            device == null ? null : device.getDeviceCode(),
                            device == null ? null : device.getName(),
                            count.getTotal());
                })
                .toList();
    }
}