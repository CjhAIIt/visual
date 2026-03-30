package com.plantops.backend.service;

import com.plantops.backend.model.DomainTypes;
import com.plantops.backend.web.PlantApiException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

@Service
public class SessionAuthService {

    private final AuthStorageService authStorageService;

    public SessionAuthService(AuthStorageService authStorageService) {
        this.authStorageService = authStorageService;
    }

    public DomainTypes.AppUser resolveOptionalUser(String token) {
        if (token == null || token.isBlank()) {
            return null;
        }
        return authStorageService.getUserByToken(token);
    }

    public DomainTypes.AppUser requireUser(String token) {
        DomainTypes.AppUser user = resolveOptionalUser(token);
        if (user == null) {
            throw new PlantApiException(HttpStatus.UNAUTHORIZED, "登录已失效或尚未登录，请重新登录");
        }
        return user;
    }

    public DomainTypes.AppUser requireAdmin(String token) {
        DomainTypes.AppUser user = requireUser(token);
        if (!"admin".equals(user.role())) {
            throw new PlantApiException(HttpStatus.FORBIDDEN, "只有管理员可以访问该接口");
        }
        return user;
    }
}