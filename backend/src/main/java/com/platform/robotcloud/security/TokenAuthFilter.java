package com.platform.robotcloud.security;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpHeaders;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.List;

/**
 * 解析 Authorization: Bearer &lt;token&gt;：
 * - 用户令牌 → CurrentUser（ROLE_ADMIN/ROLE_OPERATOR/ROLE_VIEWER）；
 * - 边缘令牌 → EdgePrincipal（ROLE_EDGE），并要求令牌版本与库里一致（轮换/吊销后立即失效）。
 * 解析失败时不直接报错，交给 SecurityConfig 的入口点统一返回 401 JSON。
 */
@Component
public class TokenAuthFilter extends OncePerRequestFilter {

    public static final String ROLE_EDGE = "ROLE_EDGE";

    private static final Logger log = LoggerFactory.getLogger(TokenAuthFilter.class);

    private final JwtService jwtService;
    private final EdgeTokenValidator edgeTokenValidator;

    public TokenAuthFilter(JwtService jwtService, EdgeTokenValidator edgeTokenValidator) {
        this.jwtService = jwtService;
        this.edgeTokenValidator = edgeTokenValidator;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String header = request.getHeader(HttpHeaders.AUTHORIZATION);
        if (header != null && header.regionMatches(true, 0, "Bearer ", 0, 7)) {
            String token = header.substring(7).trim();
            try {
                authenticate(jwtService.parse(token));
            } catch (JwtException | IllegalArgumentException ex) {
                SecurityContextHolder.clearContext();
                log.debug("rejected token for {}: {}", request.getRequestURI(), ex.getMessage());
            }
        }
        chain.doFilter(request, response);
    }

    private void authenticate(Claims claims) {
        if (JwtService.SCOPE_EDGE.equals(claims.get(JwtService.CLAIM_SCOPE, String.class))) {
            Long deviceId = claims.get(JwtService.CLAIM_DEVICE_ID, Number.class) == null
                    ? null
                    : claims.get(JwtService.CLAIM_DEVICE_ID, Number.class).longValue();
            Integer tokenVersion = claims.get(JwtService.CLAIM_TOKEN_VERSION, Number.class) == null
                    ? null
                    : claims.get(JwtService.CLAIM_TOKEN_VERSION, Number.class).intValue();
            if (deviceId == null || tokenVersion == null || claims.getSubject() == null) {
                SecurityContextHolder.clearContext();
                return;
            }
            if (!edgeTokenValidator.isTokenActive(deviceId, tokenVersion)) {
                SecurityContextHolder.clearContext();
                log.debug("edge token for device {} is revoked or rotated", deviceId);
                return;
            }
            EdgePrincipal principal = new EdgePrincipal(deviceId, claims.getSubject());
            SecurityContextHolder.getContext().setAuthentication(
                    new UsernamePasswordAuthenticationToken(principal, null,
                            List.of(new SimpleGrantedAuthority(ROLE_EDGE))));
            return;
        }

        String username = claims.getSubject();
        String role = claims.get(JwtService.CLAIM_ROLE, String.class);
        Number userId = claims.get(JwtService.CLAIM_USER_ID, Number.class);
        if (username == null || role == null) {
            SecurityContextHolder.clearContext();
            return;
        }
        CurrentUser user = new CurrentUser(userId == null ? null : userId.longValue(), username,
                claims.get(JwtService.CLAIM_DISPLAY_NAME, String.class), role);
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(user, null,
                        List.of(new SimpleGrantedAuthority(Role.of(role).authority()))));
    }
}