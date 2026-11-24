package com.platform.robotcloud.simulation;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.platform.robotcloud.device.DeviceLookupService;
import com.platform.robotcloud.event.FaultEvent;
import com.platform.robotcloud.event.FaultEventRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * 把边端 state 报文里随帧携带的 {@code faults[]} 落成 fault_event 记录。
 *
 * <p>关键差别：边端给的 <b>不是事件流，而是「该帧的活动故障」</b>——10Hz 上报，
 * 故障消失后下一帧就是空数组。直接入库会变成每秒 10 条重复记录，所以这里做
 * 边沿检测：只在下述两个时刻写库
 * <ul>
 *   <li>活动故障出现（inactive → active）：插入一条 fault_event</li>
 *   <li>活动故障消失（active → inactive）：在该条记录的 detail 上补「已恢复，持续 Ns」</li>
 * </ul>
 * 故障键取 {@code deviceId|faultType|jointIndex}，同一故障持续期间不重复写。
 */
@Component
public class SimulationFaultTracker {

    private static final Logger log = LoggerFactory.getLogger(SimulationFaultTracker.class);

    /** 活动故障表上限，防止设备狂报不同故障把内存撑满。 */
    private static final int MAX_ACTIVE = 4096;

    private static final String RECOVERED_MARK = "（已恢复";

    private final FaultEventRepository repository;
    private final DeviceLookupService deviceLookupService;
    private final ObjectMapper mapper = new ObjectMapper();
    private final Map<String, ActiveFault> active = new ConcurrentHashMap<>();
    private final AtomicLong recoveredCount = new AtomicLong();

    public SimulationFaultTracker(FaultEventRepository repository, DeviceLookupService deviceLookupService) {
        this.repository = repository;
        this.deviceLookupService = deviceLookupService;
    }

    public void record(String robotId, String simulationId, List<JsonNode> faults, LocalDateTime occurredAt) {
        Long deviceId = deviceLookupService.findOrCreateId(robotId);
        String prefix = deviceId + "|";
        Set<String> seen = new HashSet<>();
        for (JsonNode fault : faults) {
            String type = text(fault, "faultType", "UNKNOWN");
            JsonNode index = fault.path("jointIndex");
            int jointIndex = index.isInt() ? index.asInt() : -1;
            String key = prefix + type + "|" + jointIndex;
            if (!seen.add(key)) {
                continue;
            }
            if (active.size() >= MAX_ACTIVE) {
                log.warn("活动故障表已满（{}），丢弃 {} 的新故障 {}", MAX_ACTIVE, robotId, type);
                continue;
            }
            active.computeIfAbsent(key, k -> insert(deviceId, robotId, simulationId, jointIndex, fault, occurredAt));
        }
        closeRecovered(prefix, seen, occurredAt);
    }

    /** 当前活动的故障数（排查用）。 */
    public int activeCount() {
        return active.size();
    }

    public long recoveredCount() {
        return recoveredCount.get();
    }

    private ActiveFault insert(Long deviceId, String robotId, String simulationId, int jointIndex,
                               JsonNode fault, LocalDateTime occurredAt) {
        FaultEvent event = new FaultEvent();
        event.setDeviceId(deviceId);
        event.setEventType(text(fault, "faultType", "UNKNOWN"));
        event.setLevel(text(fault, "severity", "WARNING"));
        event.setDetail(text(fault, "detail", null));
        event.setContextPayload(context(robotId, simulationId, jointIndex));
        event.setOccurredAt(occurredAt);
        FaultEvent saved = repository.save(event);
        log.info("边端故障入库：robot={} sim={} type={} level={} joint={}",
                robotId, simulationId, saved.getEventType(), saved.getLevel(), jointIndex);
        return new ActiveFault(saved, occurredAt);
    }

    /** 本帧没出现的活动故障 = 已恢复。只处理本设备（key 前缀即 deviceId）。 */
    private void closeRecovered(String prefix, Set<String> seen, LocalDateTime at) {
        for (Iterator<Map.Entry<String, ActiveFault>> it = active.entrySet().iterator(); it.hasNext(); ) {
            Map.Entry<String, ActiveFault> entry = it.next();
            if (!entry.getKey().startsWith(prefix) || seen.contains(entry.getKey())) {
                continue;
            }
            it.remove();
            markRecovered(entry.getValue(), at);
        }
    }

    private void markRecovered(ActiveFault fault, LocalDateTime at) {
        FaultEvent event = fault.event();
        try {
            String detail = event.getDetail() == null ? "" : event.getDetail();
            if (detail.contains(RECOVERED_MARK)) {
                return;
            }
            long seconds = Math.max(Duration.between(fault.firstSeen(), at).getSeconds(), 0);
            event.setDetail(detail + RECOVERED_MARK + "，持续 " + seconds + "s）");
            repository.save(event);
            recoveredCount.incrementAndGet();
            log.info("边端故障恢复：robot={} type={} 持续 {}s",
                    event.getDeviceId(), event.getEventType(), seconds);
        } catch (Exception ex) {
            log.warn("标记故障恢复失败：{}", ex.getMessage());
        }
    }

    private String context(String robotId, String simulationId, int jointIndex) {
        ObjectNode node = mapper.createObjectNode();
        node.put("robotId", robotId);
        node.put("simulationId", simulationId);
        node.put("jointIndex", jointIndex);
        return node.toString();
    }

    private static String text(JsonNode json, String field, String fallback) {
        JsonNode node = json.path(field);
        if (node.isMissingNode() || node.isNull()) {
            return fallback;
        }
        String value = node.asText().trim();
        return value.isEmpty() ? fallback : value;
    }

    private record ActiveFault(FaultEvent event, LocalDateTime firstSeen) {
    }
}