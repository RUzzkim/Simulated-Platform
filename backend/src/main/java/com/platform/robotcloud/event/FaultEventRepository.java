package com.platform.robotcloud.event;

import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 统计查询统一用哨兵值代替 null：deviceId = -1 表示不限定设备，
 * from/to 取 MIN_TIME/MAX_TIME 覆盖全量，避免 JPQL 中出现空参数比较。
 */
public interface FaultEventRepository extends JpaRepository<FaultEvent, Long> {

    List<FaultEvent> findAllByOrderByOccurredAtDesc(Pageable pageable);

    List<FaultEvent> findByDeviceIdOrderByOccurredAtDesc(Long deviceId, Pageable pageable);

    @Query("select count(e) from FaultEvent e "
            + "where (:deviceId = -1L or e.deviceId = :deviceId) and e.occurredAt between :from and :to")
    long countInRange(@Param("deviceId") long deviceId,
                      @Param("from") LocalDateTime from,
                      @Param("to") LocalDateTime to);

    @Query("select e.level as key, count(e) as total from FaultEvent e "
            + "where (:deviceId = -1L or e.deviceId = :deviceId) and e.occurredAt between :from and :to "
            + "group by e.level order by count(e) desc")
    List<KeyCount> countByLevel(@Param("deviceId") long deviceId,
                                @Param("from") LocalDateTime from,
                                @Param("to") LocalDateTime to);

    @Query("select e.eventType as key, count(e) as total from FaultEvent e "
            + "where (:deviceId = -1L or e.deviceId = :deviceId) and e.occurredAt between :from and :to "
            + "group by e.eventType order by count(e) desc")
    List<KeyCount> countByType(@Param("deviceId") long deviceId,
                               @Param("from") LocalDateTime from,
                               @Param("to") LocalDateTime to);

    @Query("select function('date', e.occurredAt) as day, count(e) as total from FaultEvent e "
            + "where (:deviceId = -1L or e.deviceId = :deviceId) and e.occurredAt between :from and :to "
            + "group by function('date', e.occurredAt) order by function('date', e.occurredAt) asc")
    List<DayCount> countByDay(@Param("deviceId") long deviceId,
                              @Param("from") LocalDateTime from,
                              @Param("to") LocalDateTime to);

    @Query("select e.deviceId as deviceId, count(e) as total from FaultEvent e "
            + "where (:deviceId = -1L or e.deviceId = :deviceId) and e.occurredAt between :from and :to "
            + "group by e.deviceId order by count(e) desc")
    List<DeviceCount> countByDevice(@Param("deviceId") long deviceId,
                                    @Param("from") LocalDateTime from,
                                    @Param("to") LocalDateTime to);

    interface KeyCount {
        String getKey();

        long getTotal();
    }

    interface DayCount {
        Object getDay();

        long getTotal();
    }

    interface DeviceCount {
        Long getDeviceId();

        long getTotal();
    }
}