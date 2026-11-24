package com.platform.robotcloud.security;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Date;

/**
 * 签发/校验两类无状态令牌（HS256）：
 * - 用户令牌：claims 里带 uid/role/name，走 REST 接口；
 * - 边缘令牌：claims 里带 scope=edge + dvc(设备ID) + tv(令牌版本，改版本即吊销)，走 /api/edge/** 与 MQTT 联调。
 */
@Service
public class JwtService {

    public static final String CLAIM_SCOPE = "scope";
    public static final String CLAIM_ROLE = "role";
    public static final String CLAIM_USER_ID = "uid";
    public static final String CLAIM_DISPLAY_NAME = "name";
    public static final String CLAIM_DEVICE_ID = "dvc";
    public static final String CLAIM_TOKEN_VERSION = "tv";
    public static final String SCOPE_EDGE = "edge";

    private final SecretKey key;
    private final long userTtlMinutes;
    private final long edgeTtlHours;

    public JwtService(@Value("${app.jwt.secret}") String secret,
                      @Value("${app.jwt.user-ttl-minutes:720}") long userTtlMinutes,
                      @Value("${app.jwt.edge-ttl-hours:720}") long edgeTtlHours) {
        byte[] bytes = secret == null ? new byte[0] : secret.getBytes(StandardCharsets.UTF_8);
        if (bytes.length < 32) {
            throw new IllegalStateException("app.jwt.secret 至少需要 32 字节（256 位），当前 " + bytes.length);
        }
        this.key = Keys.hmacShaKeyFor(bytes);
        this.userTtlMinutes = userTtlMinutes;
        this.edgeTtlHours = edgeTtlHours;
    }

    public String issueUserToken(AppUser user) {
        Instant now = Instant.now();
        return Jwts.builder()
                .subject(user.getUsername())
                .claim(CLAIM_USER_ID, user.getId())
                .claim(CLAIM_ROLE, user.getRole())
                .claim(CLAIM_DISPLAY_NAME, user.getDisplayName())
                .issuedAt(Date.from(now))
                .expiration(Date.from(now.plus(userTtlMinutes, ChronoUnit.MINUTES)))
                .signWith(key)
                .compact();
    }

    public String issueEdgeToken(Long deviceId, String deviceCode, int tokenVersion) {
        Instant now = Instant.now();
        return Jwts.builder()
                .subject(deviceCode)
                .claim(CLAIM_SCOPE, SCOPE_EDGE)
                .claim(CLAIM_DEVICE_ID, deviceId)
                .claim(CLAIM_TOKEN_VERSION, tokenVersion)
                .issuedAt(Date.from(now))
                .expiration(Date.from(now.plus(edgeTtlHours, ChronoUnit.HOURS)))
                .signWith(key)
                .compact();
    }

    /** 解析并校验签名与过期时间，失败抛 {@link JwtException}。 */
    public Claims parse(String token) throws JwtException {
        return Jwts.parser().verifyWith(key).build().parseSignedClaims(token).getPayload();
    }

    public long userTtlMinutes() { return userTtlMinutes; }

    public long edgeTtlHours() { return edgeTtlHours; }
}