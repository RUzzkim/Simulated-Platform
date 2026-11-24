package com.platform.robotcloud.telemetry;

import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

public interface TelemetryRepository extends JpaRepository<TelemetryData, Long> {

    Optional<TelemetryData> findFirstByDeviceIdOrderByReportedAtDesc(Long deviceId);

    List<TelemetryData> findByDeviceIdOrderByReportedAtDesc(Long deviceId, Pageable pageable);

    /**
     * 分页列表带时间区间时使用：保持与无区间一致的倒序语义。
     */
    @Query("select t from TelemetryData t "
            + "where t.deviceId = :deviceId and t.reportedAt between :from and :to "
            + "order by t.reportedAt desc")
    List<TelemetryData> findRangeDesc(@Param("deviceId") Long deviceId,
                                      @Param("from") LocalDateTime from,
                                      @Param("to") LocalDateTime to,
                                      Pageable pageable);

    /** 归档用：保留期之前的明细，按时间正序按批取。 */
    List<TelemetryData> findByReportedAtBeforeOrderByReportedAtAsc(LocalDateTime cutoff, Pageable pageable);

    long countByReportedAtBefore(LocalDateTime cutoff);

    /**
     * 详情页历史曲线用：按时间正序返回区间内的遥测帧。
     */
    @Query("select t from TelemetryData t "
            + "where t.deviceId = :deviceId and t.reportedAt between :from and :to "
            + "order by t.reportedAt asc")
    List<TelemetryData> findSeries(@Param("deviceId") Long deviceId,
                                   @Param("from") LocalDateTime from,
                                   @Param("to") LocalDateTime to,
                                   Pageable pageable);
}