package com.platform.robotcloud.audit;

import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.LocalDateTime;
import java.util.List;

public interface AuditLogRepository extends JpaRepository<AuditLog, Long> {

    /**
     * 空串表示“不过滤”，避免 JPQL 里出现 null 参数比较。
     */
    @Query("select a from AuditLog a "
            + "where (:action = '' or a.action = :action) "
            + "and (:actorType = '' or a.actorType = :actorType) "
            + "and (:targetId = '' or a.targetId = :targetId) "
            + "and a.occurredAt between :from and :to "
            + "order by a.occurredAt desc, a.id desc")
    List<AuditLog> search(@Param("action") String action,
                          @Param("actorType") String actorType,
                          @Param("targetId") String targetId,
                          @Param("from") LocalDateTime from,
                          @Param("to") LocalDateTime to,
                          Pageable pageable);

    @Query("select distinct a.action from AuditLog a order by a.action")
    List<String> distinctActions();

    long countByResult(String result);
}