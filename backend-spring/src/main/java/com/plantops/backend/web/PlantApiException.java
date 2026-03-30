package com.plantops.backend.web;

import org.springframework.http.HttpStatus;

public class PlantApiException extends RuntimeException {

    private final HttpStatus status;

    public PlantApiException(HttpStatus status, String message) {
        super(message);
        this.status = status;
    }

    public HttpStatus getStatus() {
        return status;
    }
}