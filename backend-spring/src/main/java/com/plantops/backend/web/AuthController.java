package com.plantops.backend.web;

import com.plantops.backend.model.ApiPayloads;
import com.plantops.backend.model.DomainTypes;
import com.plantops.backend.service.AuthStorageService;
import com.plantops.backend.service.CatalogService;
import com.plantops.backend.service.SessionAuthService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class AuthController {

    private final AuthStorageService authStorageService;
    private final SessionAuthService sessionAuthService;
    private final CatalogService catalogService;

    public AuthController(
        AuthStorageService authStorageService,
        SessionAuthService sessionAuthService,
        CatalogService catalogService
    ) {
        this.authStorageService = authStorageService;
        this.sessionAuthService = sessionAuthService;
        this.catalogService = catalogService;
    }

    @PostMapping("/auth/login")
    public ApiPayloads.ApiResponse<ApiPayloads.AuthSessionData> login(
        @RequestBody ApiPayloads.AuthLoginRequest request
    ) {
        DomainTypes.AppUser user = authStorageService.authenticateUser(request.username(), request.password());
        if (user == null) {
            throw new PlantApiException(org.springframework.http.HttpStatus.UNAUTHORIZED, "用户名或密码错误");
        }
        String token = authStorageService.createSession(user.id());
        return new ApiPayloads.ApiResponse<>(
            true,
            "登录成功",
            new ApiPayloads.AuthSessionData(token, catalogService.buildUserProfile(user))
        );
    }

    @PostMapping("/auth/register")
    public ApiPayloads.ApiResponse<ApiPayloads.AuthSessionData> register(
        @RequestBody ApiPayloads.AuthRegisterRequest request
    ) {
        DomainTypes.AppUser user = authStorageService.createUser(
            request.username(),
            request.password(),
            "user",
            request.displayName(),
            false
        );
        String token = authStorageService.createSession(user.id());
        return new ApiPayloads.ApiResponse<>(
            true,
            "注册成功",
            new ApiPayloads.AuthSessionData(token, catalogService.buildUserProfile(user))
        );
    }

    @GetMapping("/auth/session")
    public ApiPayloads.ApiResponse<ApiPayloads.AuthSessionData> session(
        @RequestHeader(value = "X-Auth-Token", required = false) String token
    ) {
        DomainTypes.AppUser currentUser = sessionAuthService.requireUser(token);
        return new ApiPayloads.ApiResponse<>(
            true,
            "登录状态有效",
            new ApiPayloads.AuthSessionData(null, catalogService.buildUserProfile(currentUser))
        );
    }

    @PostMapping("/auth/logout")
    public ApiPayloads.ApiResponse<ApiPayloads.AuthSessionData> logout(
        @RequestHeader(value = "X-Auth-Token", required = false) String token
    ) {
        if (token != null && !token.isBlank()) {
            authStorageService.deleteSession(token);
        }
        return new ApiPayloads.ApiResponse<>(
            true,
            "退出登录成功",
            new ApiPayloads.AuthSessionData(null, null)
        );
    }
}