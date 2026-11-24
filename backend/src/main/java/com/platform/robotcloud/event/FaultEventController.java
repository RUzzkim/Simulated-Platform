package com.platform.robotcloud.event;

import org.springframework.data.domain.PageRequest;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;
import java.util.List;

@RestController
public class FaultEventController {

    private final FaultEventRepository repository;
    private final FaultEventService service;

    public FaultEventController(FaultEventRepository repository, FaultEventService service) {
        this.repository = repository;
        this.service = service;
    }

    @GetMapping("/api/fault-events")
    public List<FaultEvent> list(
            @RequestParam(required = false) Long deviceId,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size) {
        PageRequest pageable = PageRequest.of(page, size);
        return deviceId == null
                ? repository.findAllByOrderByOccurredAtDesc(pageable)
                : repository.findByDeviceIdOrderByOccurredAtDesc(deviceId, pageable);
    }

    @GetMapping("/api/fault-events/statistics")
    public FaultStatistics statistics(
            @RequestParam(required = false) Long deviceId,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) LocalDateTime from,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) LocalDateTime to) {
        return service.statistics(deviceId, from, to);
    }

    @GetMapping("/api/fault-events/{id}")
    public FaultEvent detail(@PathVariable Long id) {
        return service.require(id);
    }
}