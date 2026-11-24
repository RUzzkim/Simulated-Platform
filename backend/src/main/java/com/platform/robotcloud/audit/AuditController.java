package com.platform.robotcloud.audit;

import org.springframework.data.domain.PageRequest;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;
import java.util.List;

@RestController
@RequestMapping("/api/audit-logs")
public class AuditController {

    private static final LocalDateTime MIN_TIME = LocalDateTime.of(1970, 1, 1, 0, 0);
    private static final LocalDateTime MAX_TIME = LocalDateTime.of(9999, 1, 1, 0, 0);

    private final AuditLogRepository repository;

    public AuditController(AuditLogRepository repository) {
        this.repository = repository;
    }

    @GetMapping
    public List<AuditLog> list(
            @RequestParam(required = false) String action,
            @RequestParam(required = false) String actorType,
            @RequestParam(required = false) String targetId,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) LocalDateTime from,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) LocalDateTime to,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size) {
        int cappedSize = Math.min(Math.max(size, 1), 200);
        return repository.search(blankToEmpty(action), blankToEmpty(actorType), blankToEmpty(targetId),
                from == null ? MIN_TIME : from, to == null ? MAX_TIME : to,
                PageRequest.of(Math.max(page, 0), cappedSize));
    }

    @GetMapping("/actions")
    public List<String> actions() {
        return repository.distinctActions();
    }

    private static String blankToEmpty(String value) {
        return value == null ? "" : value.trim();
    }
}