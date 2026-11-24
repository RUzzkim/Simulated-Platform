package com.platform.robotcloud.telemetry;

import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;

/**
 * 遥测批量落库：MQTT 线程只入队，单线程攒批后走 JDBC batchUpdate，
 * 避免逐条 save 在 1–10 Hz × 多设备场景下把连接和事务打满。
 * 队列满时丢弃并计数（遥测允许丢帧，但不允许阻塞上报线程）。
 */
@Component
public class TelemetryBatchWriter {

    private static final Logger log = LoggerFactory.getLogger(TelemetryBatchWriter.class);

    private static final String INSERT_SQL = "insert into telemetry_data "
            + "(device_id, reported_at, state, control_mode, joint_payload, end_effector_payload) "
            + "values (?, ?, ?, ?, ?, ?)";

    private static final int CAPACITY = 20000;
    private static final int MAX_BATCH = 500;
    private static final long POLL_MILLIS = 200;

    private final BlockingQueue<TelemetryData> queue = new LinkedBlockingQueue<>(CAPACITY);
    private final JdbcTemplate jdbcTemplate;

    private final AtomicLong enqueued = new AtomicLong();
    private final AtomicLong inserted = new AtomicLong();
    private final AtomicLong dropped = new AtomicLong();
    private final AtomicLong flushCount = new AtomicLong();
    private final AtomicLong lastFlushMicros = new AtomicLong();
    private final AtomicLong lastBatchSize = new AtomicLong();
    private final AtomicLong failedFlushes = new AtomicLong();

    private volatile boolean running = true;
    private Thread worker;

    public TelemetryBatchWriter(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public record Stats(int queueSize, long enqueued, long inserted, long dropped, long flushCount,
                        long lastFlushMicros, long lastBatchSize, long failedFlushes, int capacity) {
    }

    @PostConstruct
    void start() {
        worker = new Thread(this::loop, "telemetry-batch-writer");
        worker.setDaemon(true);
        worker.start();
        log.info("telemetry batch writer started (capacity={}, maxBatch={})", CAPACITY, MAX_BATCH);
    }

    @PreDestroy
    void stop() {
        running = false;
        if (worker != null) {
            worker.interrupt();
            try {
                worker.join(5000);
            } catch (InterruptedException ex) {
                Thread.currentThread().interrupt();
            }
        }
        log.info("telemetry batch writer stopped: {}", stats());
    }

    /** 入队；队列满时返回 false（调用方可据此记录丢弃）。 */
    public boolean enqueue(TelemetryData data) {
        if (queue.offer(data)) {
            enqueued.incrementAndGet();
            return true;
        }
        long total = dropped.incrementAndGet();
        if (total == 1 || total % 100 == 0) {
            log.warn("telemetry queue is full, dropped {} frames so far", total);
        }
        return false;
    }

    public Stats stats() {
        return new Stats(queue.size(), enqueued.get(), inserted.get(), dropped.get(), flushCount.get(),
                lastFlushMicros.get(), lastBatchSize.get(), failedFlushes.get(), CAPACITY);
    }

    private void loop() {
        List<TelemetryData> batch = new ArrayList<>(MAX_BATCH);
        while (running) {
            try {
                TelemetryData first = queue.poll(POLL_MILLIS, TimeUnit.MILLISECONDS);
                if (first == null) {
                    continue;
                }
                batch.add(first);
                queue.drainTo(batch, MAX_BATCH - 1);
                flush(batch);
            } catch (InterruptedException ex) {
                Thread.currentThread().interrupt();
                break;
            } catch (Exception ex) {
                log.error("unexpected error in telemetry batch loop", ex);
            } finally {
                batch.clear();
            }
        }
        drainRemaining(batch);
    }

    private void drainRemaining(List<TelemetryData> batch) {
        while (!queue.isEmpty()) {
            queue.drainTo(batch, MAX_BATCH);
            if (!batch.isEmpty()) {
                flush(batch);
                batch.clear();
            }
        }
    }

    private void flush(List<TelemetryData> batch) {
        long start = System.nanoTime();
        int size = batch.size();
        try {
            jdbcTemplate.batchUpdate(INSERT_SQL, batch, size, (statement, data) -> {
                statement.setLong(1, data.getDeviceId());
                statement.setTimestamp(2, Timestamp.valueOf(data.getReportedAt()));
                statement.setString(3, data.getState());
                statement.setString(4, data.getControlMode());
                statement.setString(5, data.getJointPayload());
                statement.setString(6, data.getEndEffectorPayload());
            });
            inserted.addAndGet(size);
            touchDevices(batch);
        } catch (Exception ex) {
            failedFlushes.incrementAndGet();
            log.error("failed to flush {} telemetry frames: {}", size, ex.getMessage());
        } finally {
            lastFlushMicros.set((System.nanoTime() - start) / 1000);
            lastBatchSize.set(size);
            flushCount.incrementAndGet();
        }
    }

    /**
     * 批量结束后再刷新设备状态，每台设备只更新一次（取批内最新上报时间），
     * 语义与逐条 touch 一致：只把离线设备拉回 ONLINE，不覆盖心跳写入的状态。
     */
    private void touchDevices(List<TelemetryData> batch) {
        Map<Long, LocalDateTime> latest = new HashMap<>();
        for (TelemetryData data : batch) {
            latest.merge(data.getDeviceId(), data.getReportedAt(),
                    (left, right) -> right.isAfter(left) ? right : left);
        }
        latest.forEach((deviceId, reportedAt) -> jdbcTemplate.update(
                "update device set updated_at = ?, status = case when status = 'ONLINE' then status else 'ONLINE' end "
                        + "where id = ? and updated_at < ?",
                Timestamp.valueOf(reportedAt), deviceId, Timestamp.valueOf(reportedAt)));
    }
}