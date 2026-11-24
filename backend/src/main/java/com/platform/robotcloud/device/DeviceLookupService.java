package com.platform.robotcloud.device;

import com.platform.robotcloud.audit.AuditAction;
import com.platform.robotcloud.audit.AuditService;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

@Service
public class DeviceLookupService {

    /** 高频遥测每秒都会查一次 device_code -> id，这里做进程内缓存，避免每条消息打一次库。 */
    private static final int CACHE_LIMIT = 10000;

    private final DeviceRepository repository;
    private final AuditService auditService;
    private final Map<String, Long> deviceIdCache = new ConcurrentHashMap<>();
    /** 设备 -> 仿真实例 的绑定缓存，高频遥测每帧都会读，避免每帧写库。 */
    private final Map<String, String> simulationBindingCache = new ConcurrentHashMap<>();

    public DeviceLookupService(DeviceRepository repository, AuditService auditService) {
        this.repository = repository;
        this.auditService = auditService;
    }

    /**
     * 设备列表：status 可选过滤，不传 page/size 时返回全量。
     */
    public List<Device> list(String status, Integer page, Integer size) {
        boolean filterByStatus = status != null && !status.isBlank();
        String normalizedStatus = filterByStatus ? status.trim().toUpperCase() : null;
        if (page == null || size == null) {
            return filterByStatus
                    ? repository.findByStatusOrderByIdAsc(normalizedStatus)
                    : repository.findAll(Sort.by(Sort.Direction.ASC, "id"));
        }
        Pageable pageable = PageRequest.of(Math.max(page, 0), Math.max(size, 1), Sort.by(Sort.Direction.ASC, "id"));
        return filterByStatus
                ? repository.findByStatus(normalizedStatus, pageable)
                : repository.findAll(pageable).getContent();
    }

    public Long findOrCreateId(String deviceCode) {
        Long cached = deviceIdCache.get(deviceCode);
        if (cached != null) {
            return cached;
        }
        Device device = findByCode(deviceCode);
        if (deviceIdCache.size() >= CACHE_LIMIT) {
            deviceIdCache.clear();
        }
        deviceIdCache.put(device.getDeviceCode(), device.getId());
        return device.getId();
    }

    /**
     * 记录设备属于哪个仿真实例（边端 simulation 契约的 simulationId）。
     * <p>边端每帧遥测都会带着 simulationId，命中缓存直接返回，只有变化时才写库。
     */
    public void bindSimulation(String deviceCode, String simulationId) {
        if (deviceCode == null || simulationId == null || simulationId.isBlank()) {
            return;
        }
        if (simulationId.equals(simulationBindingCache.get(deviceCode))) {
            return;
        }
        Device device = findByCode(deviceCode);
        if (!simulationId.equals(device.getSimulationId())) {
            device.setSimulationId(simulationId);
            device.setUpdatedAt(LocalDateTime.now());
            repository.save(device);
        }
        if (simulationBindingCache.size() >= CACHE_LIMIT) {
            simulationBindingCache.clear();
        }
        simulationBindingCache.put(device.getDeviceCode(), simulationId);
    }

    public Device findByCode(String deviceCode) {
        return repository.findByDeviceCode(deviceCode).orElseGet(() -> {
            Device device = new Device();
            device.setDeviceCode(deviceCode);
            device.setName(deviceCode);
            device.setStatus("ONLINE");
            device.setCreatedAt(LocalDateTime.now());
            device.setUpdatedAt(LocalDateTime.now());
            return repository.save(device);
        });
    }

    /**
     * 注册设备，已存在时更新名称，便于用中文名覆盖历史乱码数据。
     */
    public Device register(String deviceCode, String name) {
        Device device = repository.findByDeviceCode(deviceCode).orElseGet(() -> {
            Device created = new Device();
            created.setDeviceCode(deviceCode);
            created.setStatus("OFFLINE");
            created.setCreatedAt(LocalDateTime.now());
            return created;
        });
        device.setName(displayName(name, deviceCode));
        device.setUpdatedAt(LocalDateTime.now());
        Device saved = repository.save(device);
        deviceIdCache.put(saved.getDeviceCode(), saved.getId());
        auditService.userAction(AuditAction.DEVICE_REGISTER, "device", saved.getDeviceCode(),
                "注册/更新设备 " + saved.getName());
        return saved;
    }

    public Device rename(Long id, String name) {
        if (name == null || name.isBlank()) {
            throw new IllegalArgumentException("name must not be blank");
        }
        Device device = requireDevice(id);
        String previous = device.getName();
        device.setName(name.trim());
        device.setUpdatedAt(LocalDateTime.now());
        Device saved = repository.save(device);
        auditService.userAction(AuditAction.DEVICE_RENAME, "device", saved.getDeviceCode(),
                "设备重命名：" + previous + " -> " + saved.getName());
        return saved;
    }

    public Device requireDevice(Long id) {
        return repository.findById(id)
                .orElseThrow(() -> new IllegalArgumentException("device not found: " + id));
    }

    /**
     * 心跳到达时刷新在线状态。
     */
    public void markOnline(Long deviceId, String status, LocalDateTime reportedAt) {
        repository.findById(deviceId).ifPresent(device -> {
            device.setStatus(status == null ? "ONLINE" : status);
            device.setUpdatedAt(reportedAt);
            repository.save(device);
        });
    }

    /**
     * 遥测到达只代表有活动，仅把离线设备拉回在线，避免覆盖心跳写入的状态。
     */
    public void touch(Long deviceId, LocalDateTime reportedAt) {
        repository.findById(deviceId).ifPresent(device -> {
            if (!"ONLINE".equals(device.getStatus())) {
                device.setStatus("ONLINE");
            }
            device.setUpdatedAt(reportedAt);
            repository.save(device);
        });
    }

    private static String displayName(String name, String fallback) {
        return (name == null || name.isBlank()) ? fallback : name.trim();
    }
}