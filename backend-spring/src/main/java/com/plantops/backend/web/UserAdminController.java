package com.plantops.backend.web;

import com.plantops.backend.model.ApiPayloads;
import com.plantops.backend.model.DomainTypes;
import com.plantops.backend.service.AuthStorageService;
import com.plantops.backend.service.CatalogService;
import com.plantops.backend.service.SessionAuthService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class UserAdminController {

    private final SessionAuthService sessionAuthService;
    private final AuthStorageService authStorageService;
    private final CatalogService catalogService;

    public UserAdminController(
        SessionAuthService sessionAuthService,
        AuthStorageService authStorageService,
        CatalogService catalogService
    ) {
        this.sessionAuthService = sessionAuthService;
        this.authStorageService = authStorageService;
        this.catalogService = catalogService;
    }

    @GetMapping("/users")
    public ApiPayloads.ApiResponse<ApiPayloads.UsersData> listUsers(
        @RequestHeader(value = "X-Auth-Token", required = false) String token
    ) {
        DomainTypes.AppUser currentUser = sessionAuthService.requireAdmin(token);
        return catalogService.buildUsersResponse(currentUser, "用户列表已就绪");
    }

    @PostMapping("/admin/users/{userId}/disabled")
    public ApiPayloads.ApiResponse<ApiPayloads.UsersData> setUserDisabled(
        @PathVariable int userId,
        @RequestBody ApiPayloads.ToggleValueRequest request,
        @RequestHeader(value = "X-Auth-Token", required = false) String token
    ) {
        DomainTypes.AppUser currentUser = sessionAuthService.requireAdmin(token);
        DomainTypes.AppUser targetUser = authStorageService.getUserById(userId);
        if (targetUser == null) {
            throw new PlantApiException(org.springframework.http.HttpStatus.NOT_FOUND, "用户不存在：" + userId);
        }
        if (targetUser.id() == currentUser.id()) {
            throw new PlantApiException(org.springframework.http.HttpStatus.BAD_REQUEST, "不能封禁当前登录的管理员账号");
        }
        if ("admin".equals(targetUser.role())) {
            throw new PlantApiException(org.springframework.http.HttpStatus.BAD_REQUEST, "不能封禁管理员账号");
        }
        DomainTypes.AppUser updatedUser = authStorageService.setUserDisabled(userId, request.value());
        String action = request.value() ? "已封禁用户：" : "已解除封禁：";
        return catalogService.buildUsersResponse(currentUser, action + updatedUser.username());
    }

    @PostMapping("/admin/users/{userId}/flagged")
    public ApiPayloads.ApiResponse<ApiPayloads.UsersData> setUserFlagged(
        @PathVariable int userId,
        @RequestBody ApiPayloads.ToggleValueRequest request,
        @RequestHeader(value = "X-Auth-Token", required = false) String token
    ) {
        DomainTypes.AppUser currentUser = sessionAuthService.requireAdmin(token);
        DomainTypes.AppUser targetUser = authStorageService.getUserById(userId);
        if (targetUser == null) {
            throw new PlantApiException(org.springframework.http.HttpStatus.NOT_FOUND, "用户不存在：" + userId);
        }
        DomainTypes.AppUser updatedUser = authStorageService.setUserFlagged(userId, request.value());
        String action = request.value() ? "已标记重点关注：" : "已取消重点关注：";
        return catalogService.buildUsersResponse(currentUser, action + updatedUser.username());
    }
}