package com.platform.robotcloud.security;

import jakarta.servlet.http.HttpServletResponse;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

import java.io.IOException;

/**
 * 无状态 JWT 鉴权：REST 走用户令牌（ADMIN/OPERATOR/VIEWER），边缘上报走 edge token（ROLE_EDGE）。
 */
@Configuration
@EnableWebSecurity
@EnableMethodSecurity
public class SecurityConfig {

    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    @Bean
    public SecurityFilterChain securityFilterChain(HttpSecurity http, TokenAuthFilter tokenAuthFilter) throws Exception {
        http
                .csrf(AbstractHttpConfigurer::disable)
                .httpBasic(AbstractHttpConfigurer::disable)
                .formLogin(AbstractHttpConfigurer::disable)
                .logout(AbstractHttpConfigurer::disable)
                .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(auth -> auth
                        .requestMatchers(HttpMethod.OPTIONS, "/**").permitAll()
                        .requestMatchers("/api/auth/login", "/api/auth/register", "/api/health").permitAll()
                        // 边缘端：只能访问自己的上报通道
                        .requestMatchers("/api/edge/**").hasAuthority(TokenAuthFilter.ROLE_EDGE)
                        // 用户自助改密
                        .requestMatchers(HttpMethod.POST, "/api/auth/password").authenticated()
                        // 遥测归档会删明细，仅 ADMIN 可触发（定时任务由配置开关控制）
                        .requestMatchers("/api/system/archive").hasRole("ADMIN")
                        // 账号管理仅 ADMIN
                        .requestMatchers("/api/users/**").hasRole("ADMIN")
                        // 审计查询：ADMIN 与 OPERATOR 可看
                        .requestMatchers(HttpMethod.GET, "/api/audit-logs/**").hasAnyRole("ADMIN", "OPERATOR")
                        // 设备接入凭据属于敏感操作
                        .requestMatchers("/api/devices/*/credentials/**").hasAnyRole("ADMIN", "OPERATOR")
                        // 其余写操作需要 ADMIN/OPERATOR，读操作登录即可
                        .requestMatchers(HttpMethod.POST, "/api/**").hasAnyRole("ADMIN", "OPERATOR")
                        .requestMatchers(HttpMethod.PUT, "/api/**").hasAnyRole("ADMIN", "OPERATOR")
                        .requestMatchers(HttpMethod.PATCH, "/api/**").hasAnyRole("ADMIN", "OPERATOR")
                        .requestMatchers(HttpMethod.DELETE, "/api/**").hasAnyRole("ADMIN", "OPERATOR")
                        // 其余接口只认云端账号：设备令牌（ROLE_EDGE）只能走 /api/edge/**
                        .anyRequest().hasAnyRole("ADMIN", "OPERATOR", "VIEWER"))
                .exceptionHandling(handling -> handling
                        .authenticationEntryPoint((request, response, ex) ->
                                writeError(response, HttpServletResponse.SC_UNAUTHORIZED, "unauthorized"))
                        .accessDeniedHandler((request, response, ex) ->
                                writeError(response, HttpServletResponse.SC_FORBIDDEN, "forbidden: 当前角色无权执行该操作")))
                .addFilterBefore(tokenAuthFilter, UsernamePasswordAuthenticationFilter.class);
        return http.build();
    }

    private static void writeError(HttpServletResponse response, int status, String message) throws IOException {
        if (response.isCommitted()) {
            return;
        }
        response.setStatus(status);
        response.setContentType("application/json;charset=UTF-8");
        response.setCharacterEncoding("UTF-8");
        response.getWriter().write("{\"error\":\"" + message.replace("\"", "'") + "\"}");
    }
}