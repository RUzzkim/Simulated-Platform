package com.platform.robotcloud.telemetry;

import org.springframework.data.domain.PageRequest;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;
import java.util.List;

@RestController
@RequestMapping("/api/devices/{id}/telemetry")
public class TelemetryController {

    private static final LocalDateTime MIN_TIME = LocalDateTime.of(1970, 1, 1, 0, 0);
    private static final LocalDateTime MAX_TIME = LocalDateTime.of(9999, 1, 1, 0, 0);
    private static final int MAX_SERIES_POINTS = 2000;

    private final TelemetryRepository repository;
    private final TelemetrySeriesService seriesService;
    private final TelemetryArchiveService archiveService;

    public TelemetryController(TelemetryRepository repository,
                               TelemetrySeriesService seriesService,
                               TelemetryArchiveService archiveService) {
        this.repository = repository;
        this.seriesService = seriesService;
        this.archiveService = archiveService;
    }

    @GetMapping("/latest")
    public TelemetryData latest(@PathVariable Long id) {
        return repository.findFirstByDeviceIdOrderByReportedAtDesc(id).orElse(null);
    }

    @GetMapping
    public List<TelemetryData> list(
            @PathVariable Long id,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) LocalDateTime from,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) LocalDateTime to) {
        if (from == null && to == null) {
            return repository.findByDeviceIdOrderByReportedAtDesc(id, PageRequest.of(page, size));
        }
        return repository.findRangeDesc(id, from == null ? MIN_TIME : from, to == null ? MAX_TIME : to,
                PageRequest.of(page, size));
    }

    /**
     * 历史曲线。downsample=true 时按等时间分桶取均值，点数是 limit（默认 300），
     * 用于设备跑久之后曲线不被原始采样密度挤爆；语义是「桶内平均」，不是原始采样点。
     */
    @GetMapping("/series")
    public List<TelemetryData> series(
            @PathVariable Long id,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) LocalDateTime from,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) LocalDateTime to,
            @RequestParam(defaultValue = "300") int limit,
            @RequestParam(defaultValue = "false") boolean downsample) {
        int capped = Math.min(Math.max(limit, 1), MAX_SERIES_POINTS);
        return seriesService.series(id, from == null ? MIN_TIME : from, to == null ? MAX_TIME : to,
                capped, downsample);
    }

    /** 归档后的小时桶（明细被归档后看长期趋势用）。 */
    @GetMapping("/hourly")
    public List<TelemetryHourly> hourly(
            @PathVariable Long id,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) LocalDateTime from,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) LocalDateTime to) {
        return archiveService.hourly(id, from == null ? MIN_TIME : from, to == null ? MAX_TIME : to);
    }
}