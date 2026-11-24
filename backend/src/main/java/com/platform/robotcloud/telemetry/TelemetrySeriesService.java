package com.platform.robotcloud.telemetry;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 历史曲线的降采样。
 *
 * <p>设备跑久了以后一小时窗口就是几万帧，直接取 300 条会把中间的过程丢掉（看上去像跳变）。
 * 这里改成等时间分桶 + 桶内均值：曲线形状保留、点数可控，语义是「这一段时间的平均水平」，
 * 所以详情页把降采样标成 AVG 标签，不假装是原始采样点。
 */
@Service
public class TelemetrySeriesService {

    private static final Logger log = LoggerFactory.getLogger(TelemetrySeriesService.class);

    /** 一次最多扫多少原始帧，防止区间过大时把内存拉满。 */
    private static final int MAX_RAW_SCAN = 20000;
    private static final int MAX_POINTS = 2000;

    private final TelemetryRepository repository;
    private final ObjectMapper mapper = new ObjectMapper();

    public TelemetrySeriesService(TelemetryRepository repository) {
        this.repository = repository;
    }

    public List<TelemetryData> series(Long deviceId, LocalDateTime from, LocalDateTime to,
                                      int limit, boolean downsample) {
        int capped = Math.min(Math.max(limit, 1), MAX_POINTS);
        List<TelemetryData> raw = repository.findSeries(deviceId, from, to, PageRequest.of(0, MAX_RAW_SCAN));
        if (!downsample || raw.size() <= capped) {
            return raw.size() > capped ? raw.subList(0, capped) : raw;
        }
        return bucket(raw, capped);
    }

    /** 等时间分桶 + 桶内均值；只对 position/velocity/effort 求均值。 */
    List<TelemetryData> bucket(List<TelemetryData> raw, int buckets) {
        LocalDateTime start = raw.get(0).getReportedAt();
        LocalDateTime end = raw.get(raw.size() - 1).getReportedAt();
        long span = Duration.between(start, end).toMillis();
        if (span <= 0) {
            return raw;
        }
        Map<Integer, Map<String, double[]>> bucketsById = new LinkedHashMap<>();
        Map<Integer, int[]> frameCounts = new LinkedHashMap<>();
        Map<Integer, String[]> lastMeta = new LinkedHashMap<>();
        for (TelemetryData frame : raw) {
            long offset = Duration.between(start, frame.getReportedAt()).toMillis();
            int index = (int) Math.min(buckets - 1, Math.max(0, offset * buckets / span));
            Map<String, double[]> joints = bucketsById.computeIfAbsent(index, key -> new LinkedHashMap<>());
            frameCounts.computeIfAbsent(index, key -> new int[1])[0]++;
            lastMeta.put(index, new String[]{frame.getState(), frame.getControlMode()});
            JsonNode payload = parse(frame.getJointPayload());
            if (payload == null || !payload.isArray()) {
                continue;
            }
            for (JsonNode joint : payload) {
                String name = joint.path("name").asText(null);
                if (name == null) {
                    continue;
                }
                double[] acc = joints.computeIfAbsent(name, key -> new double[4]);
                acc[0] += joint.path("position").asDouble(0);
                acc[1] += joint.path("velocity").asDouble(0);
                acc[2] += joint.path("effort").asDouble(0);
                acc[3] += 1;
            }
        }
        List<TelemetryData> result = new ArrayList<>(bucketsById.size());
        for (Map.Entry<Integer, Map<String, double[]>> entry : bucketsById.entrySet()) {
            int index = entry.getKey();
            long bucketMillis = span / buckets;
            TelemetryData point = new TelemetryData();
            point.setDeviceId(raw.get(0).getDeviceId());
            point.setReportedAt(start.plus(Duration.ofMillis(bucketMillis * index + bucketMillis / 2)));
            String[] meta = lastMeta.get(index);
            if (meta != null) {
                point.setState(meta[0]);
                point.setControlMode(meta[1]);
            }
            ArrayNode joints = mapper.createArrayNode();
            for (Map.Entry<String, double[]> joint : entry.getValue().entrySet()) {
                double[] acc = joint.getValue();
                if (acc[3] <= 0) {
                    continue;
                }
                ObjectNode node = mapper.createObjectNode();
                node.put("name", joint.getKey());
                node.put("position", round(acc[0] / acc[3]));
                node.put("velocity", round(acc[1] / acc[3]));
                node.put("effort", round(acc[2] / acc[3]));
                node.put("samples", (int) acc[3]);
                joints.add(node);
            }
            point.setJointPayload(joints.toString());
            result.add(point);
        }
        log.debug("downsampled {} raw frames into {} buckets", raw.size(), result.size());
        return result;
    }

    private JsonNode parse(String raw) {
        if (raw == null || raw.isBlank()) {
            return null;
        }
        try {
            return mapper.readTree(raw);
        } catch (Exception ex) {
            return null;
        }
    }

    private static double round(double value) {
        return Math.round(value * 1000.0) / 1000.0;
    }
}